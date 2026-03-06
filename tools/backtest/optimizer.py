"""Strategy parameter optimisation using grid search and Bayesian methods."""

from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OptimisationResult:
    """Result from a single parameter evaluation."""

    params: Dict[str, Any]
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


@dataclass
class OptimisationReport:
    """Aggregated optimisation report."""

    best_params: Dict[str, Any]
    best_score: float
    all_results: List[OptimisationResult]
    method: str
    total_evaluations: int
    elapsed_seconds: float


class StrategyOptimizer:
    """
    Optimises strategy parameters using grid search or random search.

    For Bayesian optimisation, optionally delegates to ``scikit-optimize``
    when available.

    Parameters
    ----------
    objective_fn : callable
        Function with signature ``(params: dict) -> float`` where higher is
        better (e.g. Sharpe ratio).
    param_space : dict
        Mapping of parameter name → list of candidate values (grid search)
        or ``(low, high)`` tuple (random / Bayesian search).
    method : str
        "grid", "random", or "bayesian".
    n_trials : int
        Number of random/Bayesian evaluations (ignored for grid search).
    n_jobs : int
        Not used directly; reserved for future parallel execution.
    maximize : bool
        If True (default), maximise the objective; otherwise minimise.
    random_seed : int, optional
        Seed for reproducibility.
    """

    def __init__(
        self,
        objective_fn: Callable[[Dict[str, Any]], float],
        param_space: Dict[str, Any],
        method: str = "grid",
        n_trials: int = 50,
        n_jobs: int = 1,
        maximize: bool = True,
        random_seed: Optional[int] = None,
    ) -> None:
        self.objective_fn = objective_fn
        self.param_space = param_space
        self.method = method
        self.n_trials = n_trials
        self.n_jobs = n_jobs
        self.maximize = maximize
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> OptimisationReport:
        """
        Execute the optimisation and return a report.

        Returns
        -------
        OptimisationReport
        """
        t0 = time.perf_counter()
        if self.method == "grid":
            results = self._grid_search()
        elif self.method == "bayesian":
            results = self._bayesian_search()
        else:
            results = self._random_search()

        sign = -1 if not self.maximize else 1
        best = max(results, key=lambda r: sign * r.score)
        elapsed = time.perf_counter() - t0

        logger.info(
            "Optimisation complete: %d evals, best score=%.4f, method=%s, elapsed=%.1fs",
            len(results), best.score, self.method, elapsed,
        )
        return OptimisationReport(
            best_params=best.params,
            best_score=best.score,
            all_results=results,
            method=self.method,
            total_evaluations=len(results),
            elapsed_seconds=elapsed,
        )

    def results_to_dataframe(self, report: OptimisationReport) -> pd.DataFrame:
        """
        Convert all evaluation results into a DataFrame.

        Parameters
        ----------
        report : OptimisationReport

        Returns
        -------
        pd.DataFrame
            Columns = parameter names + "score" + "elapsed_seconds".
        """
        rows = []
        for r in report.all_results:
            row = dict(r.params)
            row["score"] = r.score
            row["elapsed_seconds"] = r.elapsed_seconds
            rows.append(row)
        df = pd.DataFrame(rows)
        return df.sort_values("score", ascending=not self.maximize).reset_index(drop=True)

    def sensitivity_analysis(
        self, report: OptimisationReport, top_n: int = 10
    ) -> pd.DataFrame:
        """
        Compute correlation between each parameter and the objective score.

        Parameters
        ----------
        report : OptimisationReport
        top_n : int
            Use the top-N results for the analysis.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns "parameter" and "correlation".
        """
        df = self.results_to_dataframe(report).head(top_n)
        numeric_cols = [c for c in df.columns if c not in ("score", "elapsed_seconds")]
        correlations = []
        for col in numeric_cols:
            try:
                corr = df[col].corr(df["score"])
                correlations.append({"parameter": col, "correlation": corr})
            except Exception:  # noqa: BLE001
                pass
        return pd.DataFrame(correlations).sort_values("correlation", key=abs, ascending=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _grid_search(self) -> List[OptimisationResult]:
        keys = list(self.param_space.keys())
        # Normalise: if a value is a 2-tuple of numbers, treat as range for grid
        grid_values = []
        for v in self.param_space.values():
            if isinstance(v, list):
                grid_values.append(v)
            else:
                grid_values.append([v])

        results: List[OptimisationResult] = []
        for combo in itertools.product(*grid_values):
            params = dict(zip(keys, combo))
            result = self._evaluate(params)
            results.append(result)
        return results

    def _random_search(self) -> List[OptimisationResult]:
        results: List[OptimisationResult] = []
        for _ in range(self.n_trials):
            params = self._sample_params()
            results.append(self._evaluate(params))
        return results

    def _bayesian_search(self) -> List[OptimisationResult]:
        try:
            from skopt import gp_minimize  # lazy import
            from skopt.space import Categorical, Integer, Real

            space, keys = [], []
            for k, v in self.param_space.items():
                keys.append(k)
                if isinstance(v, list):
                    space.append(Categorical(v, name=k))
                elif isinstance(v, tuple) and len(v) == 2:
                    lo, hi = v
                    space.append(
                        Integer(int(lo), int(hi), name=k)
                        if isinstance(lo, int) and isinstance(hi, int)
                        else Real(float(lo), float(hi), name=k)
                    )
                else:
                    space.append(Categorical([v], name=k))

            all_results: List[OptimisationResult] = []

            def sk_objective(values: list) -> float:
                params = dict(zip(keys, values))
                res = self._evaluate(params)
                all_results.append(res)
                return -res.score if self.maximize else res.score

            gp_minimize(sk_objective, space, n_calls=self.n_trials, random_state=42)
            return all_results

        except ImportError:
            logger.warning("scikit-optimize not available; falling back to random search.")
            return self._random_search()

    def _sample_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for k, v in self.param_space.items():
            if isinstance(v, list):
                params[k] = v[self.rng.integers(0, len(v))]
            elif isinstance(v, tuple) and len(v) == 2:
                lo, hi = v
                params[k] = (
                    int(self.rng.integers(int(lo), int(hi) + 1))
                    if isinstance(lo, int)
                    else float(self.rng.uniform(lo, hi))
                )
            else:
                params[k] = v
        return params

    def _evaluate(self, params: Dict[str, Any]) -> OptimisationResult:
        t0 = time.perf_counter()
        try:
            score = float(self.objective_fn(params))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Objective evaluation failed for %s: %s", params, exc)
            score = -np.inf if self.maximize else np.inf
        return OptimisationResult(
            params=params,
            score=score,
            elapsed_seconds=time.perf_counter() - t0,
        )

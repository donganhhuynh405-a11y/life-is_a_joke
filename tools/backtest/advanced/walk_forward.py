"""Walk-forward analysis for out-of-sample strategy validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    """A single in-sample / out-of-sample fold."""

    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    in_sample_metrics: Dict[str, float] = field(default_factory=dict)
    out_of_sample_metrics: Dict[str, float] = field(default_factory=dict)
    best_params: Dict[str, Any] = field(default_factory=dict)


class WalkForwardAnalyzer:
    """
    Performs walk-forward analysis to assess out-of-sample strategy robustness.

    The analyser splits the data into *n_splits* anchored or rolling windows,
    optimises strategy parameters on the in-sample window, and evaluates
    performance on the subsequent out-of-sample window.

    Parameters
    ----------
    n_splits : int
        Number of train/test folds.
    train_ratio : float
        Fraction of each window used for training (e.g. 0.7 = 70 % train).
    anchored : bool
        If True, the training window always starts from the beginning of the
        dataset (expanding window).  If False, use a rolling fixed-size window.
    """

    def __init__(
        self,
        n_splits: int = 5,
        train_ratio: float = 0.70,
        anchored: bool = True,
    ) -> None:
        self.n_splits = n_splits
        self.train_ratio = train_ratio
        self.anchored = anchored

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_folds(self, n_samples: int) -> List[WalkForwardFold]:
        """
        Generate fold index ranges for *n_samples* data points.

        Parameters
        ----------
        n_samples : int
            Total number of data rows.

        Returns
        -------
        list of WalkForwardFold
        """
        folds: List[WalkForwardFold] = []
        fold_size = n_samples // self.n_splits

        for i in range(self.n_splits):
            if self.anchored:
                train_start = 0
                train_end = int(fold_size * (i + self.train_ratio))
            else:
                train_start = fold_size * i
                train_end = train_start + int(fold_size * self.train_ratio)

            test_start = train_end
            test_end = min(test_start + int(fold_size * (1 - self.train_ratio)), n_samples)

            if test_start >= n_samples:
                break
            folds.append(
                WalkForwardFold(
                    fold_id=i,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
        return folds

    def run(
        self,
        data: pd.DataFrame,
        strategy_fn: Callable[[pd.DataFrame, Dict], pd.Series],
        param_grid: List[Dict[str, Any]],
        metric: str = "sharpe",
    ) -> List[WalkForwardFold]:
        """
        Execute the full walk-forward analysis.

        Parameters
        ----------
        data : pd.DataFrame
            Full historical dataset with at least a ``close`` column.
        strategy_fn : callable
            Function with signature ``(data_slice, params) -> returns_series``
            that returns a Series of period returns.
        param_grid : list of dict
            Parameter combinations to search over during the in-sample phase.
        metric : str
            Optimisation metric; one of "sharpe", "total_return", "calmar".

        Returns
        -------
        list of WalkForwardFold
            Folds populated with in-sample and out-of-sample metrics.
        """
        folds = self.generate_folds(len(data))
        for fold in folds:
            train_data = data.iloc[fold.train_start: fold.train_end]
            test_data = data.iloc[fold.test_start: fold.test_end]

            # --- In-sample optimisation ---
            best_score = -np.inf
            best_params: Dict[str, Any] = {}
            for params in param_grid:
                try:
                    returns = strategy_fn(train_data, params)
                    score = self._compute_metric(returns, metric)
                    if score > best_score:
                        best_score = score
                        best_params = params
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Param eval failed: %s", exc)

            fold.best_params = best_params
            fold.in_sample_metrics[metric] = best_score

            # --- Out-of-sample evaluation ---
            try:
                oos_returns = strategy_fn(test_data, best_params)
                fold.out_of_sample_metrics = self._all_metrics(oos_returns)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OOS evaluation failed for fold %d: %s", fold.fold_id, exc)

        return folds

    def summary(self, folds: List[WalkForwardFold]) -> pd.DataFrame:
        """
        Build a summary DataFrame of in-sample vs. out-of-sample metrics.

        Parameters
        ----------
        folds : list of WalkForwardFold
            Completed folds from :meth:`run`.

        Returns
        -------
        pd.DataFrame
        """
        rows = []
        for f in folds:
            row: Dict[str, Any] = {"fold": f.fold_id}
            row.update({f"is_{k}": v for k, v in f.in_sample_metrics.items()})
            row.update({f"oos_{k}": v for k, v in f.out_of_sample_metrics.items()})
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_metric(returns: pd.Series, metric: str) -> float:
        if returns.empty or returns.std() == 0:
            return -np.inf
        if metric == "sharpe":
            return float(returns.mean() / returns.std() * np.sqrt(252))
        if metric == "total_return":
            return float((1 + returns).prod() - 1)
        if metric == "calmar":
            total = (1 + returns).prod() - 1
            dd = (1 + returns).cumprod()
            max_dd = float((dd / dd.cummax() - 1).min())
            return total / abs(max_dd) if max_dd != 0 else -np.inf
        return float(returns.mean())

    def _all_metrics(self, returns: pd.Series) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        for m in ("sharpe", "total_return", "calmar"):
            metrics[m] = self._compute_metric(returns, m)
        return metrics

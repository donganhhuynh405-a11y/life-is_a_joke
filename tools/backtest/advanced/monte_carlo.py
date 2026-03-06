"""Monte Carlo simulation for strategy robustness testing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Aggregated result of a Monte Carlo simulation run."""

    n_simulations: int
    confidence_level: float
    mean_return: float
    median_return: float
    std_return: float
    var: float          # Value-at-Risk (loss exceeded in (1-CL) % of simulations)
    cvar: float         # Conditional VaR (expected loss beyond VaR)
    max_drawdown_mean: float
    max_drawdown_p95: float
    simulation_returns: np.ndarray = field(repr=False, default_factory=lambda: np.array([]))


class MonteCarloSimulator:
    """
    Monte Carlo simulator for assessing the distribution of strategy outcomes.

    Supports two simulation modes:

    * **bootstrap** – resamples historical returns with replacement.
    * **parametric** – draws from a fitted normal (or Student-t) distribution.

    Parameters
    ----------
    n_simulations : int
        Number of Monte Carlo paths to generate.
    n_periods : int
        Number of periods per path (e.g. trading days).
    confidence_level : float
        Confidence level for VaR / CVaR (e.g. 0.95 for 95 % VaR).
    mode : str
        "bootstrap" or "parametric".
    use_t_distribution : bool
        If True and mode is "parametric", use Student-t distribution to
        capture fat tails.
    random_seed : int, optional
        Seed for reproducibility.
    """

    def __init__(
        self,
        n_simulations: int = 1000,
        n_periods: int = 252,
        confidence_level: float = 0.95,
        mode: str = "bootstrap",
        use_t_distribution: bool = True,
        random_seed: Optional[int] = None,
    ) -> None:
        self.n_simulations = n_simulations
        self.n_periods = n_periods
        self.confidence_level = confidence_level
        self.mode = mode
        self.use_t_distribution = use_t_distribution
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, historical_returns: pd.Series) -> MonteCarloResult:
        """
        Run the Monte Carlo simulation.

        Parameters
        ----------
        historical_returns : pd.Series
            Historical period returns (not cumulative).

        Returns
        -------
        MonteCarloResult
        """
        returns_arr = historical_returns.dropna().values.astype(float)
        if len(returns_arr) == 0:
            raise ValueError("historical_returns must not be empty.")

        paths = self._generate_paths(returns_arr)
        terminal_returns = (1 + paths).prod(axis=1) - 1
        drawdowns = self._max_drawdowns(paths)

        var = self._compute_var(terminal_returns)
        cvar = self._compute_cvar(terminal_returns, var)

        return MonteCarloResult(
            n_simulations=self.n_simulations,
            confidence_level=self.confidence_level,
            mean_return=float(terminal_returns.mean()),
            median_return=float(np.median(terminal_returns)),
            std_return=float(terminal_returns.std()),
            var=var,
            cvar=cvar,
            max_drawdown_mean=float(drawdowns.mean()),
            max_drawdown_p95=float(np.percentile(drawdowns, 95)),
            simulation_returns=terminal_returns,
        )

    def percentile_returns(
        self, result: MonteCarloResult, percentiles: List[int]
    ) -> Dict[int, float]:
        """
        Extract return percentiles from a simulation result.

        Parameters
        ----------
        result : MonteCarloResult
        percentiles : list of int
            e.g. [5, 25, 50, 75, 95].

        Returns
        -------
        dict mapping percentile → return value.
        """
        return {p: float(np.percentile(result.simulation_returns, p)) for p in percentiles}

    def stress_test(
        self,
        historical_returns: pd.Series,
        shock_pct: float = -0.30,
        shock_duration: int = 5,
    ) -> MonteCarloResult:
        """
        Inject a market shock at a random point in each simulation path.

        Parameters
        ----------
        historical_returns : pd.Series
            Historical return series.
        shock_pct : float
            Cumulative return shock to inject (e.g. -0.30 for a 30 % crash).
        shock_duration : int
            Number of periods over which the shock is distributed.

        Returns
        -------
        MonteCarloResult
        """
        returns_arr = historical_returns.dropna().values.astype(float)
        paths = self._generate_paths(returns_arr)

        # Inject shock
        shock_per_period = (1 + shock_pct) ** (1 / shock_duration) - 1
        for path in paths:
            start = self.rng.integers(0, max(1, self.n_periods - shock_duration))
            path[start: start + shock_duration] += shock_per_period

        terminal_returns = (1 + paths).prod(axis=1) - 1
        drawdowns = self._max_drawdowns(paths)
        var = self._compute_var(terminal_returns)
        cvar = self._compute_cvar(terminal_returns, var)

        return MonteCarloResult(
            n_simulations=self.n_simulations,
            confidence_level=self.confidence_level,
            mean_return=float(terminal_returns.mean()),
            median_return=float(np.median(terminal_returns)),
            std_return=float(terminal_returns.std()),
            var=var,
            cvar=cvar,
            max_drawdown_mean=float(drawdowns.mean()),
            max_drawdown_p95=float(np.percentile(drawdowns, 95)),
            simulation_returns=terminal_returns,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_paths(self, returns_arr: np.ndarray) -> np.ndarray:
        """Generate simulation paths, shape (n_simulations, n_periods)."""
        if self.mode == "bootstrap":
            indices = self.rng.integers(
                0, len(returns_arr), size=(
                    self.n_simulations, self.n_periods))
            return returns_arr[indices]
        # Parametric
        mu = returns_arr.mean()
        sigma = returns_arr.std()
        if self.use_t_distribution:
            df = max(3, len(returns_arr) - 1)
            from scipy.stats import t as student_t  # lazy import
            samples = student_t.rvs(df=df, loc=mu, scale=sigma,
                                    size=(self.n_simulations, self.n_periods),
                                    random_state=int(self.rng.integers(0, 2**31)))
            return samples
        return self.rng.normal(mu, sigma, size=(self.n_simulations, self.n_periods))

    def _max_drawdowns(self, paths: np.ndarray) -> np.ndarray:
        """Compute maximum drawdown for each path."""
        cum = np.cumprod(1 + paths, axis=1)
        running_max = np.maximum.accumulate(cum, axis=1)
        drawdowns = cum / running_max - 1
        return drawdowns.min(axis=1)

    def _compute_var(self, terminal_returns: np.ndarray) -> float:
        """VaR at the configured confidence level (positive = loss)."""
        return float(-np.percentile(terminal_returns, (1 - self.confidence_level) * 100))

    def _compute_cvar(self, terminal_returns: np.ndarray, var: float) -> float:
        """Expected shortfall (CVaR) beyond VaR."""
        losses = -terminal_returns
        tail = losses[losses >= var]
        return float(tail.mean()) if len(tail) > 0 else var

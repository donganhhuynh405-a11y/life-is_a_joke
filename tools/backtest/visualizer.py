"""Backtest results visualisation (matplotlib-based, lazy import)."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class BacktestVisualizer:
    """
    Generates standard backtest visualisation charts.

    All matplotlib imports are deferred so the module can be imported in
    environments without a display without raising errors.

    Parameters
    ----------
    style : str
        Matplotlib style to apply (e.g. "seaborn-v0_8", "ggplot").
    figsize : tuple
        Default figure size (width, height) in inches.
    """

    def __init__(
        self,
        style: str = "ggplot",
        figsize: tuple = (14, 8),
    ) -> None:
        self.style = style
        self.figsize = figsize

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def equity_curve(
        self,
        equity: pd.Series,
        benchmark: Optional[pd.Series] = None,
        title: str = "Equity Curve",
        save_path: Optional[str] = None,
    ) -> None:
        """
        Plot the equity curve with optional benchmark overlay.

        Parameters
        ----------
        equity : pd.Series
            Portfolio equity indexed by date.
        benchmark : pd.Series, optional
            Benchmark equity for comparison (normalised to same starting value).
        title : str
            Chart title.
        save_path : str, optional
            If provided, save the figure to this path instead of displaying.
        """
        plt = self._import_plt()
        if plt is None:
            return

        with plt.style.context(self.style):
            fig, axes = plt.subplots(
                2, 1, figsize=self.figsize, gridspec_kw={
                    "height_ratios": [
                        3, 1]})
            ax_eq, ax_dd = axes

            # Normalise to 100
            eq_norm = equity / equity.iloc[0] * 100
            ax_eq.plot(eq_norm.index, eq_norm.values, label="Strategy", linewidth=1.5)

            if benchmark is not None:
                bm_norm = benchmark / benchmark.iloc[0] * 100
                bm_aligned = bm_norm.reindex(eq_norm.index, method="ffill")
                ax_eq.plot(bm_aligned.index, bm_aligned.values, label="Benchmark",
                           linewidth=1.0, linestyle="--", alpha=0.7)

            ax_eq.set_title(title)
            ax_eq.set_ylabel("Normalised Value (base=100)")
            ax_eq.legend()
            ax_eq.grid(True, alpha=0.3)

            # Drawdown panel
            cum = equity / equity.cummax() - 1
            ax_dd.fill_between(cum.index, cum.values, 0, color="red", alpha=0.4, label="Drawdown")
            ax_dd.set_ylabel("Drawdown")
            ax_dd.set_xlabel("Date")
            ax_dd.legend()
            ax_dd.grid(True, alpha=0.3)

            plt.tight_layout()
            self._save_or_show(plt, fig, save_path)

    def returns_distribution(
        self,
        returns: pd.Series,
        title: str = "Return Distribution",
        save_path: Optional[str] = None,
    ) -> None:
        """
        Plot a histogram of daily returns with normal-distribution overlay.

        Parameters
        ----------
        returns : pd.Series
            Daily percentage returns.
        title : str
        save_path : str, optional
        """
        plt = self._import_plt()
        if plt is None:
            return

        with plt.style.context(self.style):
            fig, ax = plt.subplots(figsize=self.figsize)
            r = returns.dropna()
            ax.hist(r, bins=50, density=True, alpha=0.6, color="steelblue", label="Actual")

            mu, sigma = r.mean(), r.std()
            x = np.linspace(r.min(), r.max(), 200)
            normal_pdf = np.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
            ax.plot(x, normal_pdf, "r--", linewidth=1.5, label="Normal fit")

            ax.axvline(0, color="black", linewidth=0.8, linestyle=":")
            ax.set_title(title)
            ax.set_xlabel("Daily Return")
            ax.set_ylabel("Density")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            self._save_or_show(plt, fig, save_path)

    def rolling_metrics(
        self,
        returns: pd.Series,
        window: int = 63,
        title: str = "Rolling Metrics",
        save_path: Optional[str] = None,
    ) -> None:
        """
        Plot rolling Sharpe ratio and volatility.

        Parameters
        ----------
        returns : pd.Series
            Daily returns.
        window : int
            Rolling window in days.
        title : str
        save_path : str, optional
        """
        plt = self._import_plt()
        if plt is None:
            return

        roll_sharpe = (returns.rolling(window).mean() /
                       returns.rolling(window).std()) * np.sqrt(252)
        roll_vol = returns.rolling(window).std() * np.sqrt(252)

        with plt.style.context(self.style):
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.figsize, sharex=True)
            ax1.plot(roll_sharpe.index, roll_sharpe.values, color="navy", linewidth=1.2)
            ax1.axhline(0, color="black", linewidth=0.8, linestyle=":")
            ax1.set_title(title)
            ax1.set_ylabel(f"Rolling Sharpe ({window}d)")
            ax1.grid(True, alpha=0.3)

            ax2.plot(roll_vol.index, roll_vol.values, color="darkorange", linewidth=1.2)
            ax2.set_ylabel(f"Rolling Volatility ({window}d)")
            ax2.set_xlabel("Date")
            ax2.grid(True, alpha=0.3)
            plt.tight_layout()
            self._save_or_show(plt, fig, save_path)

    def monthly_heatmap(
        self,
        returns: pd.Series,
        title: str = "Monthly Returns Heatmap",
        save_path: Optional[str] = None,
    ) -> None:
        """
        Plot a calendar heatmap of monthly returns.

        Parameters
        ----------
        returns : pd.Series
            Daily returns indexed by date.
        title : str
        save_path : str, optional
        """
        plt = self._import_plt()
        if plt is None:
            return

        monthly = (1 + returns).resample("ME").prod() - 1
        df = pd.DataFrame({"year": monthly.index.year,
                           "month": monthly.index.month,
                           "ret": monthly.values})
        pivot = df.pivot(index="year", columns="month", values="ret")
        pivot.columns = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ][:len(pivot.columns)]

        try:
            import seaborn as sns  # lazy optional import
            with plt.style.context(self.style):
                fig, ax = plt.subplots(figsize=self.figsize)
                sns.heatmap(pivot * 100, annot=True, fmt=".1f", center=0,
                            cmap="RdYlGn", ax=ax, linewidths=0.5)
                ax.set_title(title)
                plt.tight_layout()
                self._save_or_show(plt, fig, save_path)
        except ImportError:
            logger.warning("seaborn not available; skipping monthly heatmap.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _import_plt():
        try:
            import matplotlib
            matplotlib.use("Agg")   # non-interactive backend
            import matplotlib.pyplot as plt
            return plt
        except ImportError:
            logger.warning("matplotlib not available; skipping visualisation.")
            return None

    @staticmethod
    def _save_or_show(plt, fig, save_path: Optional[str]) -> None:
        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Figure saved to %s", save_path)
        else:
            plt.show()
        plt.close(fig)

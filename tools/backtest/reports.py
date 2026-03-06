"""Comprehensive backtest reporting module."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Full set of performance statistics for a backtest."""

    total_return: float
    annualised_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: int
    volatility: float
    downside_volatility: float
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    n_trades: int
    expectancy: float


class BacktestReporter:
    """
    Generates comprehensive backtest reports in multiple formats.

    Parameters
    ----------
    risk_free_rate : float
        Annualised risk-free rate used in Sharpe / Sortino calculations.
    """

    def __init__(self, risk_free_rate: float = 0.05) -> None:
        self.risk_free_rate = risk_free_rate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        equity_curve: pd.Series,
        trades: Optional[pd.DataFrame] = None,
    ) -> PerformanceMetrics:
        """
        Compute a full set of performance metrics from an equity curve.

        Parameters
        ----------
        equity_curve : pd.Series
            Portfolio equity indexed by date.
        trades : pd.DataFrame, optional
            Trade log with columns ``pnl`` and optionally ``entry_time``,
            ``exit_time``.

        Returns
        -------
        PerformanceMetrics
        """
        returns = equity_curve.pct_change().dropna()
        n_years = len(returns) / 252

        total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
        ann_return = float((1 + total_return) ** (1 / n_years) - 1) if n_years > 0 else 0.0
        vol = float(returns.std() * np.sqrt(252))

        # Sharpe
        excess = returns - self.risk_free_rate / 252
        sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0.0

        # Sortino
        downside = returns[returns < 0]
        down_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 1 else 0.0
        sortino = float(ann_return / down_vol) if down_vol > 0 else 0.0

        # Drawdown
        cum = equity_curve / equity_curve.cummax() - 1
        max_dd = float(cum.min())
        dd_duration = self._max_drawdown_duration(cum)

        # Calmar
        calmar = float(ann_return / abs(max_dd)) if max_dd != 0 else 0.0

        # Trade stats
        if trades is not None and "pnl" in trades.columns:
            wins = trades["pnl"][trades["pnl"] > 0]
            losses = trades["pnl"][trades["pnl"] < 0]
            n_trades = len(trades)
            win_rate = len(wins) / n_trades if n_trades else 0.0
            avg_win = float(wins.mean()) if len(wins) else 0.0
            avg_loss = float(losses.mean()) if len(losses) else 0.0
            profit_factor = float(wins.sum() / abs(losses.sum())
                                  ) if losses.sum() != 0 else float("inf")
            expectancy = float(trades["pnl"].mean())
        else:
            n_trades = 0
            win_rate = avg_win = avg_loss = profit_factor = expectancy = 0.0

        return PerformanceMetrics(
            total_return=total_return,
            annualised_return=ann_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            max_drawdown_duration_days=dd_duration,
            volatility=vol,
            downside_volatility=down_vol,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            n_trades=n_trades,
            expectancy=expectancy,
        )

    def to_dataframe(self, metrics: PerformanceMetrics) -> pd.DataFrame:
        """
        Convert a PerformanceMetrics object to a tidy DataFrame.

        Returns
        -------
        pd.DataFrame
            Single-column DataFrame with metric names as index.
        """
        data = asdict(metrics)
        return pd.DataFrame.from_dict(data, orient="index", columns=["value"])

    def to_text(self, metrics: PerformanceMetrics) -> str:
        """
        Render metrics as a formatted text report.

        Returns
        -------
        str
        """
        lines = [
            "=" * 50,
            "         BACKTEST PERFORMANCE REPORT",
            "=" * 50,
            f"  Total Return       : {metrics.total_return * 100:>8.2f} %",
            f"  Annualised Return  : {metrics.annualised_return * 100:>8.2f} %",
            f"  Sharpe Ratio       : {metrics.sharpe_ratio:>8.2f}",
            f"  Sortino Ratio      : {metrics.sortino_ratio:>8.2f}",
            f"  Calmar Ratio       : {metrics.calmar_ratio:>8.2f}",
            f"  Max Drawdown       : {metrics.max_drawdown * 100:>8.2f} %",
            f"  DD Duration (days) : {metrics.max_drawdown_duration_days:>8d}",
            f"  Volatility (ann.)  : {metrics.volatility * 100:>8.2f} %",
            f"  Win Rate           : {metrics.win_rate * 100:>8.2f} %",
            f"  Profit Factor      : {metrics.profit_factor:>8.2f}",
            f"  Avg Win            : {metrics.avg_win:>8.4f}",
            f"  Avg Loss           : {metrics.avg_loss:>8.4f}",
            f"  Expectancy         : {metrics.expectancy:>8.4f}",
            f"  # Trades           : {metrics.n_trades:>8d}",
            "=" * 50,
        ]
        return "\n".join(lines)

    def export_html(self, metrics: PerformanceMetrics, path: str) -> None:
        """
        Save metrics as a minimal HTML table.

        Parameters
        ----------
        metrics : PerformanceMetrics
        path : str
            Output file path.
        """
        df = self.to_dataframe(metrics)
        df.index.name = "Metric"
        html = df.to_html(float_format=lambda x: f"{x:.4f}")
        wrapped = f"<html><body><h2>Backtest Report</h2>{html}</body></html>"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(wrapped)
        logger.info("HTML report saved to %s", path)

    def export_json(self, metrics: PerformanceMetrics, path: str) -> None:
        """
        Save metrics as a JSON file.

        Parameters
        ----------
        metrics : PerformanceMetrics
        path : str
            Output file path.
        """
        import json

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(metrics), fh, indent=2, default=str)
        logger.info("JSON report saved to %s", path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _max_drawdown_duration(drawdown_series: pd.Series) -> int:
        """Return the length of the longest drawdown period in days."""
        in_drawdown = (drawdown_series < 0).astype(int)
        max_dur = 0
        current = 0
        for v in in_drawdown:
            current = current + 1 if v else 0
            max_dur = max(max_dur, current)
        return max_dur

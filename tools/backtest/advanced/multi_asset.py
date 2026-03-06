"""Multi-asset portfolio backtester using numpy and pandas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    """Snapshot of portfolio state at a given timestep."""

    timestamp: pd.Timestamp
    holdings: Dict[str, float]      # symbol → quantity held
    cash: float
    prices: Dict[str, float]        # symbol → current price
    equity: float = 0.0
    drawdown: float = 0.0


@dataclass
class BacktestReport:
    """Summary of a multi-asset backtest."""

    total_return: float
    annualised_return: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    n_trades: int
    equity_curve: pd.Series = field(repr=False, default_factory=pd.Series)
    daily_returns: pd.Series = field(repr=False, default_factory=pd.Series)
    positions_history: List[PortfolioState] = field(repr=False, default_factory=list)


class MultiAssetBacktester:
    """
    Event-driven multi-asset backtester operating on daily OHLCV data.

    The strategy is expressed as a callable that receives the current
    date's price DataFrame and the portfolio state, and returns target
    weights (or a dict of orders).

    Parameters
    ----------
    initial_capital : float
        Starting cash amount.
    fee_rate : float
        Round-trip transaction cost as a fraction of trade value.
    slippage_pct : float
        Additional fill slippage as a percentage.
    rebalance_frequency : str
        Pandas offset alias for rebalancing, e.g. "D", "W", "M".
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        fee_rate: float = 0.001,
        slippage_pct: float = 0.05,
        rebalance_frequency: str = "D",
    ) -> None:
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.rebalance_frequency = rebalance_frequency

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        prices: pd.DataFrame,
        strategy_fn: Callable[[pd.DataFrame, Dict], Dict[str, float]],
    ) -> BacktestReport:
        """
        Execute the backtest.

        Parameters
        ----------
        prices : pd.DataFrame
            Daily close prices, columns = symbols, index = DatetimeIndex.
        strategy_fn : callable
            Function ``(prices_up_to_today, portfolio_state_dict) → target_weights``
            where target_weights is a dict of symbol → weight in [0, 1].

        Returns
        -------
        BacktestReport
        """
        prices = prices.copy().sort_index()
        symbols = list(prices.columns)
        cash = self.initial_capital
        holdings: Dict[str, float] = {s: 0.0 for s in symbols}
        equity_series: Dict[pd.Timestamp, float] = {}
        positions_history: List[PortfolioState] = []
        n_trades = 0
        rebalance_dates = pd.date_range(
            prices.index[0], prices.index[-1], freq=self.rebalance_frequency)

        peak_equity = self.initial_capital
        max_drawdown = 0.0

        for date in prices.index:
            current_prices = prices.loc[date].to_dict()

            equity = cash + sum(
                holdings.get(s, 0) * current_prices.get(s, 0) for s in symbols
            )
            equity_series[date] = equity
            peak_equity = max(peak_equity, equity)
            drawdown = (equity - peak_equity) / peak_equity
            max_drawdown = min(max_drawdown, drawdown)

            state = PortfolioState(
                timestamp=date,
                holdings=dict(holdings),
                cash=cash,
                prices=current_prices,
                equity=equity,
                drawdown=drawdown,
            )
            positions_history.append(state)

            if date not in rebalance_dates:
                continue

            # Call strategy
            try:
                target_weights = strategy_fn(prices.loc[:date], state.__dict__)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Strategy error on %s: %s", date, exc)
                continue

            # Execute rebalance
            for symbol, weight in target_weights.items():
                if symbol not in symbols:
                    continue
                price = current_prices.get(symbol, 0)
                if price <= 0:
                    continue
                target_value = equity * max(0.0, weight)
                current_value = holdings.get(symbol, 0) * price
                delta_value = target_value - current_value
                delta_qty = delta_value / price

                fill_price = price * (1 + np.sign(delta_qty) * self.slippage_pct / 100)
                cost = abs(delta_qty) * fill_price * self.fee_rate
                cash -= delta_qty * fill_price + cost
                holdings[symbol] = holdings.get(symbol, 0) + delta_qty
                if abs(delta_qty) > 1e-10:
                    n_trades += 1

        equity_curve = pd.Series(equity_series)
        daily_returns = equity_curve.pct_change().dropna()

        total_return = (equity_curve.iloc[-1] /
                        self.initial_capital - 1) if len(equity_curve) else 0.0
        n_years = len(prices) / 252
        annualised = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
        sharpe = (
            float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
            if daily_returns.std() > 0
            else 0.0
        )
        calmar = annualised / abs(max_drawdown) if max_drawdown != 0 else 0.0

        return BacktestReport(
            total_return=total_return,
            annualised_return=annualised,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            calmar_ratio=calmar,
            n_trades=n_trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            positions_history=positions_history,
        )

    def add_benchmark(
        self, report: BacktestReport, benchmark_prices: pd.Series
    ) -> Dict[str, float]:
        """
        Compare strategy equity curve against a buy-and-hold benchmark.

        Parameters
        ----------
        report : BacktestReport
            Completed backtest report.
        benchmark_prices : pd.Series
            Daily prices for the benchmark asset.

        Returns
        -------
        dict
            Keys: "alpha", "beta", "information_ratio", "tracking_error".
        """
        strat_returns = report.daily_returns
        bench_returns = benchmark_prices.pct_change().dropna()
        aligned = pd.concat([strat_returns, bench_returns], axis=1, join="inner")
        aligned.columns = ["strategy", "benchmark"]

        cov = aligned.cov()
        beta = cov.loc["strategy", "benchmark"] / cov.loc["benchmark",
                                                          "benchmark"] if cov.loc["benchmark", "benchmark"] else 0.0
        alpha = (aligned["strategy"].mean() - beta * aligned["benchmark"].mean()) * 252
        te = (aligned["strategy"] - aligned["benchmark"]).std() * np.sqrt(252)
        ir = alpha / te if te > 0 else 0.0

        return {"alpha": alpha, "beta": beta, "information_ratio": ir, "tracking_error": te}

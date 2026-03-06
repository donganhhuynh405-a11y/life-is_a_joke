import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from typing import Dict


class Backtester:
    def __init__(self, exchange_id: str = "bybit", symbol: str = "BTCUSDT", timeframe: str = "1h"):
        self.exchange = getattr(ccxt, exchange_id)({'sandbox': True})
        self.symbol = symbol
        self.timeframe = timeframe
        self.results = {}

    def fetch_data(self, days: int = 365) -> pd.DataFrame:
        """Загружает исторические данные"""
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, since)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """RSI индикатор"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def run_rsi_strategy(self, df: pd.DataFrame) -> pd.DataFrame:
        """RSI стратегия (buy <30, sell >70)"""
        df['rsi'] = self.calculate_rsi(df)
        df['signal'] = 0
        df.loc[df['rsi'] < 30, 'signal'] = 1   # BUY
        df.loc[df['rsi'] > 70, 'signal'] = -1  # SELL
        df['position'] = df['signal'].replace(to_replace=0, method='ffill')
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['position'].shift(1) * df['returns']
        return df

    def calculate_metrics(self, df: pd.DataFrame) -> Dict[str, float]:
        """Ключевые метрики"""
        total_return = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
        strategy_return = (df['strategy_returns'] + 1).prod() - 1
        strategy_return_pct = strategy_return * 100

        returns = df['strategy_returns'].dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() != 0 else 0
        drawdown = (returns.cumsum().expanding().max() - returns.cumsum()).max() * 100

        trades = df[df['signal'] != 0]
        win_rate = (trades['strategy_returns'] > 0).mean() * 100 if len(trades) > 0 else 0

        self.results = {
            'total_return': total_return,
            'strategy_return': strategy_return_pct,
            'sharpe_ratio': sharpe,
            'max_drawdown': drawdown,
            'win_rate': win_rate,
            'total_trades': len(trades)
        }
        return self.results

    def plot_results(self, df: pd.DataFrame) -> go.Figure:
        """График результатов"""
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['close'], name='Price', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df.index, y=df['close'] * (1 + df['strategy_returns'].cumsum()),
                                 name='Strategy', line=dict(color='green')))
        fig.update_layout(
            title=f'{
                self.symbol} Backtest Results',
            xaxis_title='Date',
            yaxis_title='Price')
        return fig

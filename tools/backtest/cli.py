import fire
from tools.backtest.engine import Backtester
import json


def test(symbol: str = "BTCUSDT", days: int = 90, strategy: str = "rsi"):
    """Запуск бэктеста"""
    print(f"🚀 Testing {strategy} on {symbol} ({days} days)...")

    bt = Backtester("bybit", symbol)
    df = bt.fetch_data(days)
    df = bt.run_rsi_strategy(df)
    metrics = bt.calculate_metrics(df)

    print("\n📊 RESULTS:")
    print(json.dumps(metrics, indent=2))

    return metrics


def compare(symbol: str = "BTCUSDT", days: int = 365):
    """Сравнение стратегий"""
    strategies = {
        "rsi": lambda df: Backtester().run_rsi_strategy(df),
        # "dca": lambda df: run_dca_strategy(df),
    }

    bt = Backtester("bybit", symbol)
    df = bt.fetch_data(days)

    results = {}
    for name, strategy_func in strategies.items():
        df_test = strategy_func(df.copy())
        metrics = Backtester().calculate_metrics(df_test)
        results[name] = metrics

    print("\n🏆 STRATEGY COMPARISON:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    fire.Fire()

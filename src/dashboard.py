from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
from tools.backtest.engine import Backtester
from strategies import StrategyRegistry
from pydantic import BaseModel

app = FastAPI(title="ROFL Trading Bot Dashboard")
app.mount("/static", StaticFiles(directory="frontend"), name="static")


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    days: int = 90
    strategy: str = "rsi"


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>ROFL Bot Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    </head>
    <body>
    <h1>ROFL Trading Bot</h1>
    <div id="chart"></div>
    <button onclick="runBacktest()">Run Backtest</button>
    <script>
    async function runBacktest() {
        const res = await fetch('/backtest/BTCUSDT?days=90');
        const data = await res.json();
        Plotly.newPlot('chart', data.chart.data, data.chart.layout);
        console.log(data.results);
    }
    </script>
    </body>
    </html>
    """


@app.get("/backtest/{symbol}")
async def backtest_api(symbol: str, days: int = 90, strategy: str = "rsi"):
    bt = Backtester("bybit", symbol, "1h")
    df = bt.fetch_data(days)

    strategy_instance = StrategyRegistry.get(strategy)
    if strategy_instance is not None:
        df = strategy_instance.generate_signals(df)

    metrics = bt.calculate_metrics(df)
    fig = bt.plot_results(df)

    return {
        "results": metrics,
        "chart": fig.to_json()
    }


@app.get("/strategies")
async def list_strategies():
    return StrategyRegistry.STRATEGIES

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)

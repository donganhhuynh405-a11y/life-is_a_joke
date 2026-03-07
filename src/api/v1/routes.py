"""
src/api/v1/routes.py - REST API routes for the trading bot.

Provides endpoints for:
  - Health monitoring
  - Market data
  - Trading signals
  - Order management
  - Portfolio management
  - Performance metrics
  - Strategy management
  - Backtesting
  - Sentiment analysis
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    BacktestRequest,
    BacktestResult,
    ErrorResponse,
    HealthResponse,
    OHLCVResponse,
    OrderRequest,
    OrderResponse,
    PerformanceResponse,
    PortfolioResponse,
    PredictionResponse,
    SentimentRequest,
    SentimentResponse,
    SignalListResponse,
    StrategyListResponse,
    StrategyUpdateRequest,
    TickerResponse,
    TrainingStartRequest,
    TrainingStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="ok",
        environment=os.getenv("ENVIRONMENT", "paper"),
        services={
            "api": "ok",
            "redis": _check_service("redis"),
            "postgres": _check_service("postgres"),
        },
    )


def _check_service(name: str) -> str:
    """Attempt lightweight connectivity check."""
    try:
        if name == "redis":
            import redis  # type: ignore

            r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            r.ping()
            return "ok"
        elif name == "postgres":
            import psycopg2  # type: ignore

            url = os.getenv("DATABASE_URL")
            if url:
                conn = psycopg2.connect(url, connect_timeout=2)
                conn.close()
                return "ok"
        return "unknown"
    except Exception:
        return "unavailable"


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------


@router.get(
    "/market/{symbol}/ticker",
    response_model=TickerResponse,
    tags=["Market Data"],
    summary="Get current ticker",
)
async def get_ticker(symbol: str) -> TickerResponse:
    """Get current bid/ask/last for a symbol."""
    # In production this would call DataFetcher
    return TickerResponse(
        symbol=symbol,
        bid=None,
        ask=None,
        last=None,
        volume=None,
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/market/{symbol}/ohlcv",
    response_model=OHLCVResponse,
    tags=["Market Data"],
    summary="Get OHLCV candles",
)
async def get_ohlcv(
    symbol: str,
    timeframe: str = Query(default="1h", description="Candle timeframe (1m, 5m, 1h, 1d)"),
    limit: int = Query(default=100, ge=1, le=1000, description="Number of candles"),
) -> OHLCVResponse:
    """Get OHLCV candlestick data for a symbol."""
    return OHLCVResponse(
        symbol=symbol,
        timeframe=timeframe,
        candles=[],
        count=0,
    )


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@router.get(
    "/signals",
    response_model=SignalListResponse,
    tags=["Signals"],
    summary="Get latest trading signals",
)
async def get_signals(
    symbol: Optional[str] = Query(default=None, description="Filter by symbol"),
    strategy: Optional[str] = Query(default=None, description="Filter by strategy"),
    limit: int = Query(default=20, ge=1, le=100),
) -> SignalListResponse:
    """Get the most recent trading signals."""
    return SignalListResponse(signals=[], count=0)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Orders"],
    summary="Place a new order",
)
async def place_order(order: OrderRequest) -> OrderResponse:
    """Place a new trading order."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Order execution requires live exchange connection",
    )


@router.get(
    "/orders",
    tags=["Orders"],
    summary="List recent orders",
)
async def list_orders(
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """List recent orders."""
    return {"orders": [], "count": 0}


@router.delete(
    "/orders/{order_id}",
    tags=["Orders"],
    summary="Cancel an order",
)
async def cancel_order(order_id: str) -> Dict[str, str]:
    """Cancel an open order."""
    return {"status": "cancelled", "order_id": order_id}


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


@router.get(
    "/portfolio",
    response_model=PortfolioResponse,
    tags=["Portfolio"],
    summary="Get portfolio overview",
)
async def get_portfolio() -> PortfolioResponse:
    """Get current portfolio summary and asset allocations."""
    from .models import PortfolioSummary

    summary = PortfolioSummary(
        total_value_usdt=0.0,
        cash_usdt=0.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        total_pnl=0.0,
        positions_count=0,
    )
    return PortfolioResponse(summary=summary, allocations=[])


@router.get(
    "/portfolio/positions",
    tags=["Portfolio"],
    summary="List open positions",
)
async def list_positions(
    symbol: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """List currently open positions."""
    return {"positions": [], "count": 0, "total_unrealized_pnl": 0.0}


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


@router.get(
    "/performance",
    response_model=PerformanceResponse,
    tags=["Performance"],
    summary="Get performance metrics",
)
async def get_performance(
    period: str = Query(default="7d", description="Period: 1d, 7d, 30d, 90d, all"),
    strategy: Optional[str] = Query(default=None),
) -> PerformanceResponse:
    """Get trading performance metrics for a time period."""
    from .models import PerformanceMetrics

    now = datetime.utcnow()
    days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    days = days_map.get(period, 7)

    metrics = PerformanceMetrics(
        period_start=now - timedelta(days=days),
        period_end=now,
        total_trades=0,
        total_pnl=0.0,
        strategy=strategy,
    )
    return PerformanceResponse(metrics=metrics)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@router.get(
    "/strategies",
    response_model=StrategyListResponse,
    tags=["Strategies"],
    summary="List all strategies",
)
async def list_strategies() -> StrategyListResponse:
    """List all configured trading strategies and their status."""
    from .models import StrategyInfo, StrategyStatus

    strategies = [
        StrategyInfo(
            name="SimpleTrend",
            status=StrategyStatus.ACTIVE,
            description="Simple MA crossover trend following strategy",
            total_signals=0,
        ),
        StrategyInfo(
            name="EnhancedMultiIndicator",
            status=StrategyStatus.PAUSED,
            description="Multi-indicator strategy with RSI, MACD, Bollinger Bands",
            total_signals=0,
        ),
    ]
    return StrategyListResponse(strategies=strategies, count=len(strategies))


@router.patch(
    "/strategies/{strategy_name}",
    tags=["Strategies"],
    summary="Update strategy settings",
)
async def update_strategy(
    strategy_name: str,
    update: StrategyUpdateRequest,
) -> Dict[str, Any]:
    """Update strategy status or parameters."""
    return {
        "strategy": strategy_name,
        "updated": update.model_dump(exclude_none=True),
    }


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------


@router.post(
    "/backtest",
    response_model=BacktestResult,
    status_code=status.HTTP_200_OK,
    tags=["Backtesting"],
    summary="Run a backtest",
)
async def run_backtest(request: BacktestRequest) -> BacktestResult:
    """Run a strategy backtest over historical data."""
    return BacktestResult(
        strategy=request.strategy,
        symbol=request.symbol,
        timeframe=request.timeframe,
        period_start=request.start_date,
        period_end=request.end_date,
        initial_capital=request.initial_capital,
        final_capital=request.initial_capital,
        total_return=0.0,
        total_trades=0,
    )


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


@router.post(
    "/sentiment/analyze",
    response_model=SentimentResponse,
    tags=["Sentiment"],
    summary="Analyze text sentiment",
)
async def analyze_sentiment(request: SentimentRequest) -> SentimentResponse:
    """Analyze crypto sentiment from provided texts."""
    from src.sentiment import SentimentAnalyzer

    analyzer = SentimentAnalyzer({})
    result = analyzer.analyze_texts(request.texts)
    return SentimentResponse(
        results=result,
        text_count=len(request.texts),
    )


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------


@router.get(
    "/predict/{symbol}",
    response_model=PredictionResponse,
    tags=["ML Predictions"],
    summary="Get ML price direction prediction",
)
async def get_prediction(symbol: str) -> PredictionResponse:
    """Get ML model price direction prediction for a symbol."""
    return PredictionResponse(
        symbol=symbol,
        direction="HOLD",
        confidence=0.5,
        model="ensemble",
    )


# ---------------------------------------------------------------------------
# ML Training progress
# ---------------------------------------------------------------------------


@router.get(
    "/ml/training/status",
    response_model=TrainingStatusResponse,
    tags=["ML Training"],
    summary="Get real-time ML training progress",
)
async def get_training_status() -> TrainingStatusResponse:
    """
    Return the live status of the ML training pipeline.

    The status is read from the JSON progress file written by
    TrainingProgressTracker.  If training has never run the status is 'idle'.
    """
    from pathlib import Path
    from mi.training_progress import read_progress, DEFAULT_PROGRESS_FILE  # noqa: PLC0415

    data = read_progress(DEFAULT_PROGRESS_FILE)

    if data is None:
        return TrainingStatusResponse(status="idle")

    # Convert per-symbol results dict to the Pydantic sub-model
    from .models import TrainingSymbolResult  # noqa: PLC0415
    results = {
        sym: TrainingSymbolResult(**res)
        for sym, res in data.get("results", {}).items()
    }

    return TrainingStatusResponse(
        status=data.get("status", "idle"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        symbols_total=data.get("symbols_total", 0),
        symbols_done=data.get("symbols_done", 0),
        symbols_successful=data.get("symbols_successful", 0),
        symbols_skipped=data.get("symbols_skipped", 0),
        symbols_failed=data.get("symbols_failed", 0),
        current_symbol=data.get("current_symbol"),
        current_phase=data.get("current_phase"),
        progress_pct=data.get("progress_pct", 0.0),
        eta_seconds=data.get("eta_seconds"),
        results=results,
        log=data.get("log", [])[-50:],   # return last 50 log lines
    )


@router.post(
    "/ml/training/start",
    response_model=TrainingStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ML Training"],
    summary="Trigger ML training in the background",
)
async def start_training(request: TrainingStartRequest) -> TrainingStatusResponse:
    """
    Trigger the ML historical pre-training pipeline in a background thread.

    If training is already running, returns the current status with HTTP 202
    without starting a second run.

    Request body (all optional):
    - **force_retrain** – re-train even if a model already exists (default: false)
    - **symbols** – override the list of symbols (default: uses bot config)
    """
    from pathlib import Path  # noqa: PLC0415
    from mi.training_progress import read_progress, DEFAULT_PROGRESS_FILE  # noqa: PLC0415

    # Guard: don't start a second run while one is in progress
    current = read_progress(DEFAULT_PROGRESS_FILE)
    if current and current.get("status") == "running":
        logger.info("Training already in progress – ignoring duplicate start request")
        return await get_training_status()

    def _run_training():
        import asyncio  # noqa: PLC0415

        try:
            # Resolve symbols and exchange from environment / config
            symbols = request.symbols
            if not symbols:
                symbols_env = os.getenv("TRAINING_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")
                symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]

            logger.info(
                "🚀 Background training triggered via API for %d symbols (force=%s)",
                len(symbols), request.force_retrain
            )

            # Import pipeline inside thread to avoid circular imports at module level
            from mi.training_pipeline import MLTrainingPipeline  # noqa: PLC0415
            from core.exchange_adapter import ExchangeAdapter  # noqa: PLC0415

            exchange = ExchangeAdapter()

            pipeline = MLTrainingPipeline(
                exchange=exchange,
                symbols=symbols,
                timeframe="1h",
                force_retrain=request.force_retrain,
                progress_file=DEFAULT_PROGRESS_FILE,
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(pipeline.train_all_symbols())
            finally:
                loop.close()

        except Exception as exc:
            logger.error("Background training failed: %s", exc, exc_info=True)

    thread = threading.Thread(target=_run_training, daemon=True, name="ml-training")
    thread.start()

    # Return the (now-running) status
    return await get_training_status()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(title: str = "Trading Bot API") -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=title,
        version="1.3.0",
        description="Advanced crypto trading bot REST API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=exc.detail).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="Internal server error",
                detail=str(exc) if os.getenv("ENVIRONMENT") != "production" else None,
            ).model_dump(mode="json"),
        )

    # Include router
    app.include_router(router, prefix="/api/v1")

    return app

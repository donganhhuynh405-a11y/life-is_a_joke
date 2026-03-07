"""
src/api/v1/models.py - Pydantic models for API request/response validation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class StrategyStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class Environment(str, Enum):
    PAPER = "paper"
    TESTNET = "testnet"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str = "1.3.0"
    environment: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    services: Dict[str, str] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: List[Any]


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


class TickerResponse(BaseModel):
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[float] = None
    timestamp: datetime


class OHLCVCandle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: List[OHLCVCandle]
    count: int


# ---------------------------------------------------------------------------
# Trading signals
# ---------------------------------------------------------------------------


class TradingSignal(BaseModel):
    symbol: str
    action: SignalAction
    confidence: float = Field(ge=0.0, le=1.0)
    price: Optional[float] = None
    reason: Optional[str] = None
    strategy: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SignalListResponse(BaseModel):
    signals: List[TradingSignal]
    count: int


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    type: OrderType = OrderType.MARKET
    amount: float = Field(gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    params: Optional[Dict[str, Any]] = None

    @field_validator("price")
    @classmethod
    def price_required_for_limit(cls, v, info):
        if info.data.get("type") == OrderType.LIMIT and v is None:
            raise ValueError("price is required for limit orders")
        return v


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    type: OrderType
    amount: float
    price: Optional[float] = None
    status: str
    timestamp: datetime
    exchange: Optional[str] = None


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class PositionResponse(BaseModel):
    id: Optional[int] = None
    symbol: str
    side: str
    entry_price: float
    current_price: Optional[float] = None
    amount: float
    unrealized_pnl: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: Optional[str] = None
    opened_at: Optional[datetime] = None


class PositionListResponse(BaseModel):
    positions: List[PositionResponse]
    count: int
    total_unrealized_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class PortfolioSummary(BaseModel):
    total_value_usdt: float
    cash_usdt: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    positions_count: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AssetAllocation(BaseModel):
    symbol: str
    amount: float
    value_usdt: float
    weight: float
    unrealized_pnl: float


class PortfolioResponse(BaseModel):
    summary: PortfolioSummary
    allocations: List[AssetAllocation]


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------


class PerformanceMetrics(BaseModel):
    period_start: datetime
    period_end: datetime
    total_trades: int
    win_rate: Optional[float] = None
    total_pnl: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    profit_factor: Optional[float] = None
    strategy: Optional[str] = None


class PerformanceResponse(BaseModel):
    metrics: PerformanceMetrics
    equity_curve: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class StrategyInfo(BaseModel):
    name: str
    status: StrategyStatus
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    last_signal: Optional[datetime] = None
    total_signals: int = 0


class StrategyListResponse(BaseModel):
    strategies: List[StrategyInfo]
    count: int


class StrategyUpdateRequest(BaseModel):
    status: Optional[StrategyStatus] = None
    parameters: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    timeframe: str = "1h"
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(default=10000.0, gt=0)
    parameters: Optional[Dict[str, Any]] = None


class BacktestResult(BaseModel):
    strategy: str
    symbol: str
    timeframe: str
    period_start: datetime
    period_end: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    total_trades: int
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    trades: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# ML / Sentiment
# ---------------------------------------------------------------------------


class SentimentRequest(BaseModel):
    texts: List[str] = Field(min_length=1)


class SentimentResult(BaseModel):
    score: float
    sentiment: str
    fomo: bool
    fud: bool
    bullish_count: int
    bearish_count: int
    total_words: int


class SentimentResponse(BaseModel):
    results: SentimentResult
    text_count: int


class PredictionResponse(BaseModel):
    symbol: str
    direction: str
    confidence: float
    price_target: Optional[float] = None
    model: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# ML Training progress
# ---------------------------------------------------------------------------


class TrainingSymbolResult(BaseModel):
    """Per-symbol training outcome."""
    status: str                         # success | skipped | failed
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


class TrainingStatusResponse(BaseModel):
    """Live status of the ML training pipeline."""
    status: str                         # idle | running | done | failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    symbols_total: int = 0
    symbols_done: int = 0
    symbols_successful: int = 0
    symbols_skipped: int = 0
    symbols_failed: int = 0
    current_symbol: Optional[str] = None
    current_phase: Optional[str] = None
    progress_pct: float = 0.0
    eta_seconds: Optional[float] = None
    results: Dict[str, TrainingSymbolResult] = Field(default_factory=dict)
    log: List[str] = Field(default_factory=list)


class TrainingStartRequest(BaseModel):
    """Request body for POST /ml/training/start."""
    force_retrain: bool = Field(False, description="Force re-training of existing models")
    symbols: Optional[List[str]] = Field(
        None,
        description="Override the list of symbols to train (uses bot config if omitted)",
    )

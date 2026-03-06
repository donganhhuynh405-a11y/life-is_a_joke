"""Realistic slippage modelling for backtesting."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class SlippageType(str, Enum):
    FIXED = "fixed"             # constant basis-point slippage
    PROPORTIONAL = "proportional"  # proportional to order size / ADV
    SQUARE_ROOT = "square_root"    # market-impact model: σ * sqrt(Q/ADV)
    BID_ASK = "bid_ask"         # half-spread slippage


@dataclass
class SlippageResult:
    """Outcome of a slippage calculation."""

    symbol: str
    side: str
    requested_price: float
    fill_price: float
    slippage_bps: float         # basis points of slippage applied
    slippage_pct: float         # percentage


class SlippageModel:
    """
    Realistic slippage model for backtesting frameworks.

    Models several common sources of transaction cost:

    * **Fixed** – flat basis-point cost.
    * **Proportional** – cost grows with order size relative to ADV.
    * **Square-root** – Almgren/Chriss-style market-impact model.
    * **Bid-ask** – replicate half-spread crossing.

    Parameters
    ----------
    slippage_type : SlippageType
        Which model to use.
    fixed_bps : float
        Basis-point cost for fixed model (1 bps = 0.01 %).
    impact_coefficient : float
        Scaling factor for size-dependent models.
    volatility : float
        Annualised volatility estimate (used in square-root model).
    """

    def __init__(
        self,
        slippage_type: SlippageType = SlippageType.PROPORTIONAL,
        fixed_bps: float = 5.0,
        impact_coefficient: float = 0.1,
        volatility: float = 0.40,
    ) -> None:
        self.slippage_type = slippage_type
        self.fixed_bps = fixed_bps
        self.impact_coefficient = impact_coefficient
        self.volatility = volatility

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        adv: float = 0.0,
        spread_pct: float = 0.0,
    ) -> SlippageResult:
        """
        Calculate and apply slippage to a simulated fill.

        Parameters
        ----------
        symbol : str
            Trading symbol.
        side : str
            "buy" or "sell".
        price : float
            Mid-price at time of order.
        quantity : float
            Order size in base currency units.
        adv : float
            Average daily volume in the same units as quantity.
        spread_pct : float
            Current bid-ask spread as a percentage (for bid_ask model).

        Returns
        -------
        SlippageResult
        """
        slippage_pct = self._compute_slippage_pct(quantity, adv, spread_pct)
        direction = 1 if side == "buy" else -1
        fill_price = price * (1 + direction * slippage_pct / 100)
        slippage_bps = slippage_pct * 100

        return SlippageResult(
            symbol=symbol,
            side=side,
            requested_price=price,
            fill_price=round(fill_price, 10),
            slippage_bps=slippage_bps,
            slippage_pct=slippage_pct,
        )

    def apply_batch(
        self,
        orders: List[Dict],
    ) -> List[SlippageResult]:
        """
        Vectorised slippage application for a list of orders.

        Parameters
        ----------
        orders : list of dict
            Each dict must contain keys: ``symbol``, ``side``, ``price``,
            ``quantity``, and optionally ``adv``, ``spread_pct``.

        Returns
        -------
        list of SlippageResult
        """
        return [
            self.apply(
                symbol=o["symbol"],
                side=o["side"],
                price=o["price"],
                quantity=o["quantity"],
                adv=o.get("adv", 0.0),
                spread_pct=o.get("spread_pct", 0.0),
            )
            for o in orders
        ]

    def calibrate(
        self,
        historical_fills: List[Dict],
    ) -> None:
        """
        Update model parameters from historical fill data.

        Parameters
        ----------
        historical_fills : list of dict
            Each dict should contain ``mid_price``, ``fill_price``,
            ``quantity``, and ``adv``.
        """
        if not historical_fills:
            return
        observed_bps = []
        for fill in historical_fills:
            mid = fill.get("mid_price", 1)
            actual = fill.get("fill_price", mid)
            if mid > 0:
                observed_bps.append(abs(actual - mid) / mid * 10_000)
        if observed_bps:
            self.fixed_bps = float(np.mean(observed_bps))
            logger.info(
                "Calibrated fixed_bps to %.2f from %d fills.",
                self.fixed_bps,
                len(historical_fills))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_slippage_pct(
        self, quantity: float, adv: float, spread_pct: float
    ) -> float:
        if self.slippage_type == SlippageType.FIXED:
            return self.fixed_bps / 100

        if self.slippage_type == SlippageType.BID_ASK:
            return spread_pct / 2

        if adv <= 0:
            # Fall back to fixed when no volume data available
            return self.fixed_bps / 100

        participation = quantity / adv

        if self.slippage_type == SlippageType.PROPORTIONAL:
            return self.impact_coefficient * participation * 100

        if self.slippage_type == SlippageType.SQUARE_ROOT:
            # Simplified Almgren-Chriss: σ * √(Q/V)
            daily_vol = self.volatility / np.sqrt(252)
            return self.impact_coefficient * daily_vol * np.sqrt(participation) * 100

        return self.fixed_bps / 100

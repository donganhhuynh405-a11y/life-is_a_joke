"""
src/mi/training_progress.py — Real-time ML Training Progress Tracker

Writes a machine-readable JSON status file at every step so that:
  • the REST API can serve live progress via GET /ml/training/status
  • the CLI watcher (scripts/watch_training.py) can display a live dashboard
  • the bot's notification system can surface progress to Telegram

Progress file location (default): /var/lib/trading-bot/training_progress.json
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default path – can be overridden via the constructor.
DEFAULT_PROGRESS_FILE = Path("/var/lib/trading-bot/training_progress.json")


class TrainingProgressTracker:
    """
    Thread-safe progress tracker for the ML training pipeline.

    Usage::

        tracker = TrainingProgressTracker(symbols=["BTCUSDT", "ETHUSDT"])
        tracker.start()

        tracker.begin_symbol("BTCUSDT", phase="fetching_data")
        tracker.begin_symbol("BTCUSDT", phase="training")
        tracker.finish_symbol("BTCUSDT", status="success", metrics={...})

        tracker.begin_symbol("ETHUSDT", phase="fetching_data")
        tracker.finish_symbol("ETHUSDT", status="skipped")

        tracker.complete()
    """

    # Valid phase names surfaced to callers / the UI
    PHASE_IDLE = "idle"
    PHASE_FETCHING = "fetching_data"
    PHASE_TRAINING = "training"
    PHASE_DONE = "done"
    PHASE_FAILED = "failed"

    def __init__(
        self,
        symbols: List[str],
        progress_file: Path = DEFAULT_PROGRESS_FILE,
    ):
        self.symbols = symbols
        self.progress_file = Path(progress_file)
        self._lock = threading.Lock()

        self._state: Dict = {
            "status": self.PHASE_IDLE,
            "started_at": None,
            "completed_at": None,
            "symbols_total": len(symbols),
            "symbols_done": 0,
            "symbols_successful": 0,
            "symbols_skipped": 0,
            "symbols_failed": 0,
            "current_symbol": None,
            "current_phase": self.PHASE_IDLE,
            "progress_pct": 0.0,
            "eta_seconds": None,
            "results": {},      # symbol → {status, metrics, duration_s}
            "log": [],          # last N log lines
        }
        self._symbol_start: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Mark the overall pipeline as started."""
        with self._lock:
            self._state["status"] = "running"
            self._state["started_at"] = _now_iso()
            self._state["completed_at"] = None
            self._state["symbols_done"] = 0
            self._state["symbols_successful"] = 0
            self._state["symbols_skipped"] = 0
            self._state["symbols_failed"] = 0
            self._state["log"] = []
            self._state["results"] = {}
            snapshot = dict(self._state)
        self._flush_snapshot(snapshot)
        logger.info("📊 TrainingProgressTracker: pipeline started")

    def begin_symbol(self, symbol: str, phase: str) -> None:
        """
        Called at the start of each phase for a symbol.

        Args:
            symbol: e.g. "BTCUSDT"
            phase:  one of PHASE_FETCHING / PHASE_TRAINING
        """
        with self._lock:
            self._state["current_symbol"] = symbol
            self._state["current_phase"] = phase
            if phase == self.PHASE_FETCHING:
                self._symbol_start = _now_dt()
            self._append_log(f"▶ {symbol} — {phase}")
            snapshot = dict(self._state)
        self._flush_snapshot(snapshot)

    def finish_symbol(
        self,
        symbol: str,
        status: str,                    # "success" | "skipped" | "failed"
        metrics: Optional[Dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Called when a symbol's training (or skip) is complete.

        Args:
            symbol:  trading pair
            status:  "success", "skipped", or "failed"
            metrics: ModelMetrics.to_dict() on success
            error:   error message on failure
        """
        with self._lock:
            done = self._state["symbols_done"] + 1
            total = self._state["symbols_total"]

            # Record per-symbol result
            result: Dict = {"status": status}
            if metrics:
                result["metrics"] = metrics
            if error:
                result["error"] = error
            if self._symbol_start:
                result["duration_s"] = round(
                    (_now_dt() - self._symbol_start).total_seconds(), 1
                )

            self._state["results"][symbol] = result
            self._state["symbols_done"] = done
            self._state["progress_pct"] = round(done / total * 100, 1) if total else 0.0

            # Counters
            if status == "success":
                self._state["symbols_successful"] += 1
            elif status == "skipped":
                self._state["symbols_skipped"] += 1
            else:
                self._state["symbols_failed"] += 1

            # ETA – extrapolate from average per-symbol time
            self._state["eta_seconds"] = self._estimate_eta(done, total)

            icon = {"success": "✅", "skipped": "⏭️", "failed": "❌"}.get(status, "?")
            msg = f"{icon} {symbol} — {status}"
            if metrics:
                msg += f" (acc={metrics.get('accuracy', 0):.3f}, f1={metrics.get('f1_score', 0):.3f})"
            self._append_log(msg)
            snapshot = dict(self._state)

        self._flush_snapshot(snapshot)

    def complete(self, failed: bool = False) -> None:
        """Mark the overall pipeline as finished."""
        with self._lock:
            self._state["status"] = self.PHASE_FAILED if failed else self.PHASE_DONE
            self._state["completed_at"] = _now_iso()
            self._state["current_symbol"] = None
            self._state["current_phase"] = self.PHASE_DONE if not failed else self.PHASE_FAILED
            self._state["eta_seconds"] = 0
            self._state["progress_pct"] = 100.0 if not failed else self._state["progress_pct"]
            self._append_log("🏁 Training pipeline complete" if not failed else "💥 Pipeline failed")
            snapshot = dict(self._state)
        self._flush_snapshot(snapshot)
        logger.info("📊 TrainingProgressTracker: pipeline complete")

    def get_status(self) -> Dict:
        """Return a snapshot of the current progress state (thread-safe)."""
        with self._lock:
            return dict(self._state)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimate_eta(self, done: int, total: int) -> Optional[float]:
        """Estimate remaining seconds based on elapsed time per symbol."""
        if done == 0 or self._state["started_at"] is None:
            return None
        elapsed = (_now_dt() - datetime.fromisoformat(self._state["started_at"])).total_seconds()
        avg_per_symbol = elapsed / done
        remaining = total - done
        return round(avg_per_symbol * remaining, 1)

    def _append_log(self, message: str, max_lines: int = 200) -> None:
        """Append a timestamped log line, keeping only the last `max_lines`.
        Must be called while self._lock is held."""
        entry = f"[{_now_iso()}] {message}"
        self._state["log"].append(entry)
        if len(self._state["log"]) > max_lines:
            self._state["log"] = self._state["log"][-max_lines:]

    def _flush_snapshot(self, snapshot: dict) -> None:
        """Write a pre-captured snapshot to disk atomically.

        Always called **outside** self._lock to avoid re-entrant deadlocks.
        Callers must capture ``dict(self._state)`` while holding the lock
        and then pass it here after releasing it.
        """
        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.progress_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
            tmp.replace(self.progress_file)
        except Exception as exc:
            logger.warning("Could not write training progress file: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now_dt() -> datetime:
    return datetime.now(tz=timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def read_progress(progress_file: Path = DEFAULT_PROGRESS_FILE) -> Optional[Dict]:
    """
    Read the latest training progress from the JSON file.

    Returns None if the file does not exist yet.
    """
    try:
        if not progress_file.exists():
            return None
        return json.loads(progress_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read training progress file: %s", exc)
        return None

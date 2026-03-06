#!/usr/bin/env python3
"""
scripts/watch_training.py — Live ML Training Progress Watcher

Displays a real-time dashboard in the terminal that refreshes every
`--interval` seconds until training finishes (or Ctrl-C is pressed).

Usage
-----
    # Default: watch the standard progress file, refresh every 5 s
    python scripts/watch_training.py

    # Custom progress file path and faster refresh
    python scripts/watch_training.py --file /var/lib/trading-bot/training_progress.json --interval 2

    # Single snapshot (no loop)
    python scripts/watch_training.py --once

    # Via the REST API instead of the local file
    python scripts/watch_training.py --api http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Default path (matches TrainingProgressTracker default) ─────────────────
DEFAULT_PROGRESS_FILE = "/var/lib/trading-bot/training_progress.json"
DEFAULT_INTERVAL = 5  # seconds between refreshes


# ── Colours ────────────────────────────────────────────────────────────────

def _supports_colour() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


C = {
    "reset":  "\033[0m"  if _supports_colour() else "",
    "bold":   "\033[1m"  if _supports_colour() else "",
    "green":  "\033[92m" if _supports_colour() else "",
    "yellow": "\033[93m" if _supports_colour() else "",
    "red":    "\033[91m" if _supports_colour() else "",
    "cyan":   "\033[96m" if _supports_colour() else "",
    "dim":    "\033[2m"  if _supports_colour() else "",
}


def colour(text: str, *keys: str) -> str:
    prefix = "".join(C[k] for k in keys if k in C)
    return f"{prefix}{text}{C['reset']}" if prefix else text


# ── Progress bar ────────────────────────────────────────────────────────────

def progress_bar(pct: float, width: int = 40) -> str:
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:5.1f}%"


# ── ETA helper ──────────────────────────────────────────────────────────────

def fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return "calculating…"
    if seconds <= 0:
        return "done"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def fmt_elapsed(iso_start: Optional[str]) -> str:
    if not iso_start:
        return "—"
    try:
        start = datetime.fromisoformat(iso_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(tz=timezone.utc) - start
        m, s = divmod(int(elapsed.total_seconds()), 60)
        h, m = divmod(m, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)
    except Exception:
        return "—"


# ── Read progress ────────────────────────────────────────────────────────────

def read_from_file(path: str) -> Optional[dict]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠  Could not read progress file: {exc}", file=sys.stderr)
        return None


def read_from_api(base_url: str) -> Optional[dict]:
    try:
        import urllib.request
        url = base_url.rstrip("/") + "/api/v1/ml/training/status"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"⚠  Could not reach API: {exc}", file=sys.stderr)
        return None


# ── Render dashboard ─────────────────────────────────────────────────────────

def render(data: Optional[dict], refresh_n: int) -> None:
    # Clear screen
    if _supports_colour():
        print("\033[2J\033[H", end="")

    print(colour("═" * 72, "bold", "cyan"))
    print(colour("  🤖  ML TRAINING PROGRESS DASHBOARD", "bold", "cyan"))
    print(colour(f"  Refresh #{refresh_n}  •  {datetime.now().strftime('%H:%M:%S')}",
                 "dim"))
    print(colour("═" * 72, "bold", "cyan"))

    if data is None:
        print(colour("\n  ⏳  No training progress file found yet.", "yellow"))
        print(colour("     Start training with:", "dim"))
        print(colour("       docker exec trading-bot python scripts/run_training.py", "dim"))
        print(colour("     or via the API:", "dim"))
        print(colour("       curl -X POST http://localhost:8080/api/v1/ml/training/start", "dim"))
        return

    status = data.get("status", "idle")
    status_colour = {
        "idle": "dim",
        "running": "yellow",
        "done": "green",
        "failed": "red",
    }.get(status, "reset")

    print()
    print(f"  Status:   {colour(status.upper(), 'bold', status_colour)}")
    print(f"  Elapsed:  {fmt_elapsed(data.get('started_at'))}")

    if data.get("completed_at"):
        print(f"  Finished: {data['completed_at']}")

    print()
    pct = data.get("progress_pct", 0.0)
    print(f"  {progress_bar(pct)}")
    print()

    total = data.get("symbols_total", 0)
    done = data.get("symbols_done", 0)
    ok = data.get("symbols_successful", 0)
    skip = data.get("symbols_skipped", 0)
    fail = data.get("symbols_failed", 0)

    print(f"  Symbols:  {done}/{total}  │  "
          f"{colour(f'✅ {ok}', 'green')}  "
          f"{colour(f'⏭ {skip}', 'dim')}  "
          f"{colour(f'❌ {fail}', 'red')}")

    current = data.get("current_symbol")
    phase = data.get("current_phase", "")
    if current and status == "running":
        print(f"  Current:  {colour(current, 'bold')}  ({phase})")

    eta = data.get("eta_seconds")
    if status == "running":
        print(f"  ETA:      {fmt_eta(eta)}")

    # Per-symbol results table
    results = data.get("results", {})
    if results:
        print()
        print(colour("  Symbol Results:", "bold"))
        print("  " + "─" * 68)
        header = f"  {'Symbol':<14} {'Status':<10} {'Accuracy':>9} {'F1':>8} {'Duration':>10}"
        print(colour(header, "dim"))
        print("  " + "─" * 68)
        for sym, res in sorted(results.items()):
            sym_status = res.get("status", "?")
            icon = {"success": "✅", "skipped": "⏭️", "failed": "❌"}.get(sym_status, "?")
            metrics = res.get("metrics") or {}
            acc = f"{metrics.get('accuracy', 0):.3f}" if metrics.get("accuracy") else "—"
            f1 = f"{metrics.get('f1_score', 0):.3f}" if metrics.get("f1_score") else "—"
            dur = f"{res.get('duration_s', 0):.0f}s" if res.get("duration_s") else "—"
            line = f"  {icon} {sym:<12} {sym_status:<10} {acc:>9} {f1:>8} {dur:>10}"
            sym_c = "green" if sym_status == "success" else ("dim" if sym_status == "skipped" else "red")
            print(colour(line, sym_c))
        print("  " + "─" * 68)

    # Last log lines
    log_lines = data.get("log", [])[-10:]
    if log_lines:
        print()
        print(colour("  Recent log:", "bold"))
        for line in log_lines:
            print(colour(f"    {line}", "dim"))

    print()
    print(colour("  Press Ctrl-C to stop watching.", "dim"))
    print(colour("═" * 72, "bold", "cyan"))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch ML training progress in real-time",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file", "-f",
        default=os.getenv("TRAINING_PROGRESS_FILE", DEFAULT_PROGRESS_FILE),
        help=f"Path to training_progress.json  (default: {DEFAULT_PROGRESS_FILE})",
    )
    parser.add_argument(
        "--api", "-a",
        default=None,
        metavar="URL",
        help="Read from the REST API instead of a local file (e.g. http://localhost:8080)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Refresh interval in seconds  (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a single snapshot and exit",
    )
    args = parser.parse_args()

    def fetch() -> Optional[dict]:
        if args.api:
            return read_from_api(args.api)
        return read_from_file(args.file)

    refresh_n = 0
    try:
        while True:
            refresh_n += 1
            data = fetch()
            render(data, refresh_n)

            if args.once:
                break

            # Stop automatically when training is finished
            if data and data.get("status") in ("done", "failed"):
                print("\n✅  Training finished – watcher exiting.")
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n⏹  Watcher stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()

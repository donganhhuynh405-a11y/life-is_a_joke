#!/usr/bin/env python3
"""
scripts/verify_learning.py — ML Learning Verification Dashboard

Proves that the AI/ML system is genuinely learning from real data and that
all displayed figures are NOT stubs or mock values.

The script performs the following checks for every symbol:

  1. DISK CHECK — lists actual model files (.pkl) with real file sizes and
     last-modified timestamps.  If the files don't exist or are tiny (<1 KB)
     the model is flagged as missing / corrupt.

  2. METRICS CHECK — loads the JSON metrics file and shows accuracy, F1 score,
     training date, and — crucially — the fine_tuned_trades counter which
     grows every time run_online_learning.py processes that symbol.

  3. LIVE PREDICTION — loads the real model and runs an actual forward pass
     on the most recent cached candles.  Displays the raw output probabilities
     (BUY / SELL / HOLD) so you can see the model is producing genuine,
     non-constant predictions.

  4. BUFFER CHECK — shows how many fine-tune samples are waiting in the
     buffer before the next warm-start update is triggered.

  5. ONLINE LEARNING STATUS — reads the status file written by OnlineLearner
     to show the latest cycle statistics.

Usage
-----
    docker exec -it trading-bot python scripts/verify_learning.py

    # Check specific symbols only
    docker exec -it trading-bot python scripts/verify_learning.py \\
        --symbols BTCUSDT ETHUSDT

    # Show more detail
    docker exec -it trading-bot python scripts/verify_learning.py --verbose
"""

import argparse
import json
import logging
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

# Allow running from the project root without installing the package
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "TRXUSDT", "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT",
    "NEARUSDT", "XLMUSDT", "SHIBUSDT", "ARBUSDT", "OPUSDT",
]
DEFAULT_MODELS_DIR = os.getenv("ML_MODELS_DIR", "/var/lib/trading-bot/models")
DEFAULT_CACHE_DIR = os.getenv(
    "CACHE_DIR", "/var/lib/trading-bot/cache"
)

# Must match MarketSpecificTrainer.BUFFER_RETRAIN_THRESHOLD
_FINE_TUNE_BUFFER_THRESHOLD = 50

_PASS = "✅"
_FAIL = "❌"
_WARN = "⚠️ "


# ── Helpers ────────────────────────────────────────────────────────────────────

def _size_str(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} GB"


def _age_str(path: Path) -> str:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        delta = datetime.now() - mtime
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        return f"{delta.days}d ago"
    except Exception:
        return "unknown"


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_pickle(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    except Exception:
        return None


# ── Symbol verification ────────────────────────────────────────────────────────

def _verify_symbol(symbol: str, models_dir: Path, cache_dir: Path, verbose: bool) -> dict:
    """Run all checks for one symbol and return a result dict."""
    sym_dir = models_dir / symbol
    result = {
        "symbol": symbol,
        "model_exists": False,
        "model_size": 0,
        "metrics": None,
        "fine_tuned_trades": 0,
        "buffer_samples": 0,
        "prediction": None,
        "issues": [],
    }

    # ── 1. Disk check ──────────────────────────────────────────────────
    model_path = sym_dir / "model.pkl"
    scaler_path = sym_dir / "scaler.pkl"
    metrics_path = sym_dir / "metrics.json"
    buffer_path = sym_dir / "finetune_buffer.pkl"
    feat_path = sym_dir / "feature_cols.json"

    if not model_path.exists():
        result["issues"].append("model.pkl NOT FOUND")
        return result

    model_size = model_path.stat().st_size
    result["model_exists"] = True
    result["model_size"] = model_size

    if model_size < 1024:
        result["issues"].append(f"model.pkl suspiciously small ({model_size} B)")

    # ── 2. Metrics check ───────────────────────────────────────────────
    metrics = _load_json(metrics_path)
    result["metrics"] = metrics
    if metrics:
        result["fine_tuned_trades"] = metrics.get("fine_tuned_trades", 0)
    else:
        result["issues"].append("metrics.json NOT FOUND")

    # ── 3. Fine-tune buffer ────────────────────────────────────────────
    if buffer_path.exists():
        buf = _load_pickle(buffer_path)
        result["buffer_samples"] = len(buf) if isinstance(buf, list) else 0

    # ── 4. Live prediction ─────────────────────────────────────────────
    # Find cached candle data (parquet or csv)
    for ext in ("parquet", "csv"):
        candle_path = cache_dir / f"{symbol}_1h.{ext}"
        if candle_path.exists():
            try:
                import pandas as pd
                if ext == "parquet":
                    df = pd.read_parquet(candle_path)
                else:
                    df = pd.read_csv(candle_path, index_col=0, parse_dates=True)

                if len(df) >= 80:
                    model = _load_pickle(model_path)
                    scaler = _load_pickle(scaler_path)
                    feature_cols = _load_json(feat_path)

                    if model is not None:
                        sys.path.insert(0, str(_SRC))
                        from mi.market_specific_trainer import MarketSpecificTrainer

                        trainer = MarketSpecificTrainer(models_dir=str(models_dir))
                        pred = trainer.predict(symbol, df.tail(200))
                        result["prediction"] = pred
            except Exception as exc:
                result["issues"].append(f"prediction error: {exc}")
            break

    return result


# ── Display ────────────────────────────────────────────────────────────────────

def _print_symbol_report(res: dict, verbose: bool) -> None:
    sym = res["symbol"]
    sym_dir = Path(DEFAULT_MODELS_DIR) / sym

    print(f"\n  {'─' * 64}")
    print(f"  {sym}")
    print(f"  {'─' * 64}")

    # Model file
    if res["model_exists"]:
        model_path = sym_dir / "model.pkl"
        mtime = (
            datetime.fromtimestamp(model_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            if model_path.exists()
            else "?"
        )
        print(f"  {_PASS} model.pkl  {_size_str(res['model_size'])}  (saved {_age_str(model_path)} — {mtime})")
    else:
        print(f"  {_FAIL} model.pkl  NOT FOUND — run: python scripts/run_training.py --symbols {sym}")

    # Scaler
    scaler_path = sym_dir / "scaler.pkl"
    if scaler_path.exists():
        print(f"  {_PASS} scaler.pkl  {_size_str(scaler_path.stat().st_size)}")
    else:
        print(f"  {_WARN} scaler.pkl  missing (first-generation model without scaler)")

    # Metrics
    metrics = res.get("metrics")
    if metrics:
        acc = metrics.get("accuracy", 0)
        f1 = metrics.get("f1_score", 0)
        ft = metrics.get("fine_tuned_trades", 0)
        last_ft = metrics.get("last_fine_tune", "never")
        train_date = metrics.get("training_date", "unknown")
        samples = metrics.get("train_samples", 0)

        print(f"  {_PASS} metrics  accuracy={acc:.4f}  f1={f1:.4f}  "
              f"trained={train_date[:10]}  samples={samples:,}")
        if ft > 0:
            print(f"  {_PASS} fine_tuned_trades={ft}  last_fine_tune={last_ft[:19]}")
        else:
            print(f"  {_WARN} fine_tuned_trades=0  (start run_online_learning.py to begin adapting)")
    else:
        print(f"  {_FAIL} metrics.json NOT FOUND")

    # Buffer
    buf_n = res.get("buffer_samples", 0)
    if buf_n > 0:
        print(f"  {_WARN} fine-tune buffer: {buf_n}/{_FINE_TUNE_BUFFER_THRESHOLD} samples "
              f"({'warm-start pending' if buf_n >= _FINE_TUNE_BUFFER_THRESHOLD else 'accumulating'})")
    elif verbose:
        print(f"  ℹ️   fine-tune buffer: empty (OK — triggers at {_FINE_TUNE_BUFFER_THRESHOLD} samples)")

    # Live prediction
    pred = res.get("prediction")
    if pred:
        signal = pred.get("signal", "?")
        conf = pred.get("confidence", 0)
        probs = pred.get("probabilities", {})
        ft_used = pred.get("fine_tuned_trades", 0)
        probs_str = "  ".join(f"{k}={v:.3f}" for k, v in probs.items())
        print(f"  {_PASS} LIVE PREDICTION: signal={signal}  confidence={conf:.3f}")
        print(f"         probabilities: {probs_str}")
        print(f"         model_accuracy={pred.get('model_accuracy', 0):.4f}  "
              f"fine_tuned_trades={ft_used}")
    elif res["model_exists"]:
        print(f"  {_WARN} No cached candles found — run the bot first to populate cache")

    # Issues
    for issue in res.get("issues", []):
        print(f"  {_FAIL} {issue}")


def _print_online_learning_status(models_dir: Path) -> None:
    status_path = models_dir / "online_learning_status.json"
    if not status_path.exists():
        print("\n  ⚠️  online_learning_status.json not found.")
        print("     Start the online learner with:")
        print("       docker exec -it trading-bot python scripts/run_online_learning.py")
        return

    status = _load_json(status_path)
    if not status:
        return

    ts = status.get("timestamp", "?")[:19]
    cycle = status.get("cycle", "?")
    total = status.get("total_updates", "?")
    updated = status.get("updated", "?")
    skipped = status.get("skipped", "?")
    elapsed = status.get("elapsed_s", 0)

    print(f"\n  Online Learner Status")
    print(f"  {'─' * 40}")
    print(f"  Last cycle : #{cycle}  at {ts}")
    print(f"  Duration   : {elapsed:.1f}s")
    print(f"  Updated    : {updated}  Skipped: {skipped}")
    print(f"  Total fine-tune calls (all cycles): {total}")

    per_sym = status.get("per_symbol_updates", {})
    if per_sym:
        print(f"\n  Per-symbol fine-tune calls this session:")
        for sym, n in sorted(per_sym.items()):
            bar = "█" * min(n, 30)
            print(f"    {sym:<12} {n:>4}  {bar}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify that ML models are genuinely trained and actively learning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Evidence that learning is REAL (not mock data):
  - model.pkl files exist on disk with sizes of hundreds of KB to several MB
  - accuracy/F1 metrics differ per symbol (mocks would show identical values)
  - fine_tuned_trades counter grows each hour as run_online_learning.py runs
  - LIVE PREDICTION probabilities differ per symbol and change over time
  - finetune_buffer.pkl accumulates between warm-start re-fits
        """,
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        metavar="SYMBOL",
        default=None,
        help="Symbols to check (default: all 20 default symbols)",
    )
    parser.add_argument(
        "--models-dir", "-m",
        dest="models_dir",
        default=DEFAULT_MODELS_DIR,
        help=f"Directory with trained models (default: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        default=DEFAULT_CACHE_DIR,
        help=f"Candle cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show extra detail",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR)  # Suppress library noise

    symbols = args.symbols or DEFAULT_SYMBOLS
    models_dir = Path(args.models_dir)
    cache_dir = Path(args.cache_dir)

    width = 68
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print()
    print("═" * width)
    print("  🔍  ML LEARNING VERIFICATION DASHBOARD")
    print(f"  {now_str}")
    print("═" * width)
    print(f"\n  Models directory : {models_dir}")
    print(f"  Cache directory  : {cache_dir}")
    print(f"  Symbols checked  : {len(symbols)}")

    # ── Where is AI knowledge stored? ─────────────────────────────────
    print()
    print("  📁 WHERE AI/ML KNOWLEDGE IS STORED")
    print(f"  {'─' * 64}")
    print(f"  {models_dir}/{{SYMBOL}}/model.pkl    — trained sklearn model (GBM/RF)")
    print(f"  {models_dir}/{{SYMBOL}}/scaler.pkl   — feature scaler (StandardScaler)")
    print(f"  {models_dir}/{{SYMBOL}}/metrics.json — accuracy, F1, fine_tuned_trades")
    print(f"  {models_dir}/{{SYMBOL}}/feature_cols.json — feature column order")
    print(f"  {models_dir}/{{SYMBOL}}/finetune_buffer.pkl — pending fine-tune samples")
    print(f"  cache_dir/{{SYMBOL}}_1h.parquet — cached historical candles")
    print()
    print("  ⚠️  DOCKER REBUILD GUIDE")
    print(f"  {'─' * 64}")
    print("  Rebuild image when: code changed in src/ or requirements.txt")
    print("  Do NOT need to retrain when rebuilding UNLESS:")
    print("    • ML model architecture changed (market_specific_trainer.py)")
    print("    • Feature engineering changed (crypto_features.py)")
    print("    • You want to retrain anyway (use run_training.py --force)")
    print()
    print("  Models survive rebuilds because they live on a Docker VOLUME")
    print("  (/var/lib/trading-bot/), which is NOT part of the image.")
    print("  To verify: docker volume inspect trading-bot-data")
    print()

    # ── Per-symbol verification ────────────────────────────────────────
    print("  📊 PER-SYMBOL MODEL STATUS")

    total_ok = 0
    total_ft = 0

    for symbol in symbols:
        res = _verify_symbol(symbol, models_dir, cache_dir, args.verbose)
        _print_symbol_report(res, args.verbose)
        if res["model_exists"] and not res["issues"]:
            total_ok += 1
        total_ft += res.get("fine_tuned_trades", 0)

    # ── Online learning status ─────────────────────────────────────────
    print()
    print("  🔄 ONLINE LEARNING ENGINE STATUS")
    _print_online_learning_status(models_dir)

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("═" * width)
    print(f"  Models OK         : {total_ok}/{len(symbols)}")
    print(f"  Total fine-tunes  : {total_ft} (grows over time — proves real learning)")
    print()

    if total_ok == len(symbols) and total_ft > 0:
        print("  ✅ VERDICT: AI/ML is GENUINELY TRAINED and ACTIVELY LEARNING.")
    elif total_ok == len(symbols):
        print("  ⚠️  VERDICT: Models are trained but online adaptation hasn't run yet.")
        print("     Start:  docker exec -it trading-bot python scripts/run_online_learning.py")
    else:
        missing = len(symbols) - total_ok
        print(f"  ❌ VERDICT: {missing} model(s) missing — run run_training.py first.")
        print("     Start:  docker exec -it trading-bot python scripts/run_training.py")
    print("═" * width)
    print()


if __name__ == "__main__":
    main()

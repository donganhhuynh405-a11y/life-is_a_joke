"""
ML Training Pipeline

Автоматический пайплайн обучения ML моделей для всех торгуемых символов.
Запускается при старте бота и периодически для переобучения.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .historical_data_fetcher import HistoricalDataFetcher
from .market_specific_trainer import MarketSpecificTrainer, ModelMetrics
from .training_progress import TrainingProgressTracker, DEFAULT_PROGRESS_FILE

logger = logging.getLogger(__name__)


class MLTrainingPipeline:
    """
    Пайплайн для автоматического обучения ML моделей
    """

    def __init__(
        self,
        exchange,
        symbols: List[str],
        timeframe: str = '1h',
        force_retrain: bool = False,
        models_dir: str = '/var/lib/trading-bot/models',
        progress_file: Path = DEFAULT_PROGRESS_FILE,
    ):
        """
        Args:
            exchange: ExchangeAdapter instance
            symbols: Список торговых символов
            timeframe: Таймфрейм для обучения
            force_retrain: Принудительное переобучение существующих моделей
            models_dir: Директория для хранения обученных моделей
            progress_file: Path where live training progress JSON is written
        """
        self.exchange = exchange
        self.symbols = symbols
        self.timeframe = timeframe
        self.force_retrain = force_retrain

        self.data_fetcher = HistoricalDataFetcher(exchange)
        self.trainer = MarketSpecificTrainer(models_dir=models_dir)

        # Real-time progress tracker (written to disk at every step)
        self.progress = TrainingProgressTracker(
            symbols=symbols,
            progress_file=progress_file,
        )

        # Статистика обучения
        self.training_stats = {
            'started_at': None,
            'completed_at': None,
            'total_symbols': len(symbols),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'results': {}
        }

    async def train_all_symbols(self) -> Dict:
        """
        Обучить модели для всех символов

        Returns:
            Dict со статистикой обучения
        """
        logger.info("=" * 80)
        logger.info("🚀 STARTING ML TRAINING PIPELINE")
        logger.info("=" * 80)
        logger.info(f"📊 Symbols: {', '.join(self.symbols)}")
        logger.info(f"⏱️  Timeframe: {self.timeframe}")
        logger.info(f"🔄 Force retrain: {self.force_retrain}")
        logger.info("=" * 80)

        self.training_stats['started_at'] = datetime.now().isoformat()
        self.training_stats['completed_at'] = None
        self.training_stats['successful'] = 0
        self.training_stats['failed'] = 0
        self.training_stats['skipped'] = 0
        self.training_stats['results'] = {}
        self.progress.start()

        pipeline_failed = False
        try:
            for i, symbol in enumerate(self.symbols, 1):
                logger.info(f"\n{'=' * 80}")
                logger.info(f"📈 Processing {symbol} ({i}/{len(self.symbols)})")
                logger.info(f"{'=' * 80}")

                try:
                    result = await self.train_symbol(symbol)

                    if result:
                        self.training_stats['successful'] += 1
                        self.training_stats['results'][symbol] = {
                            'status': 'success',
                            'metrics': result.to_dict() if isinstance(result, ModelMetrics) else result
                        }
                        self.progress.finish_symbol(
                            symbol, status='success',
                            metrics=result.to_dict() if isinstance(result, ModelMetrics) else result
                        )
                    else:
                        self.training_stats['skipped'] += 1
                        self.training_stats['results'][symbol] = {
                            'status': 'skipped',
                            'reason': 'Model already exists and force_retrain=False'
                        }
                        self.progress.finish_symbol(symbol, status='skipped')

                except Exception as e:
                    logger.error(f"❌ Failed to train {symbol}: {e}", exc_info=True)
                    self.training_stats['failed'] += 1
                    self.training_stats['results'][symbol] = {
                        'status': 'failed',
                        'error': str(e)
                    }
                    self.progress.finish_symbol(symbol, status='failed', error=str(e))
        except Exception as pipeline_exc:
            logger.error("💥 Pipeline crashed: %s", pipeline_exc, exc_info=True)
            pipeline_failed = True
        finally:
            self.training_stats['completed_at'] = datetime.now().isoformat()
            self.progress.complete(failed=pipeline_failed)

        # Итоговый отчет
        self._print_summary()

        return self.training_stats

    async def train_symbol(self, symbol: str) -> Optional[ModelMetrics]:
        """
        Обучить модель для одного символа

        Args:
            symbol: Торговый символ

        Returns:
            ModelMetrics если обучение успешно, None если пропущено
        """
        # Проверить существующую модель
        existing_model = self.trainer.load_model(symbol)

        if existing_model and not self.force_retrain:
            model, scaler, metrics = existing_model
            logger.info(
                f"✅ Model already exists for {symbol} (accuracy: {metrics.get('accuracy', 'N/A')})")
            logger.info("   Skipping training (use force_retrain=True to retrain)")
            return None

        # Write a lock file so _collect_ml_status() can surface "training in progress"
        # to the hourly notification.  Always clean it up in the finally block.
        _lock_path = self.trainer.models_dir / '.training.lock'
        try:
            _lock_path.parent.mkdir(parents=True, exist_ok=True)
            _lock_path.write_text(json.dumps({'symbol': symbol}))

            # Загрузить исторические данные
            logger.info(f"📥 Fetching historical data for {symbol}...")
            self.progress.begin_symbol(symbol, phase=TrainingProgressTracker.PHASE_FETCHING)
            df = await self.data_fetcher.fetch_full_history(
                symbol=symbol,
                timeframe=self.timeframe,
                force_reload=self.force_retrain
            )

            if df is None or len(df) < self.trainer.min_training_samples:
                logger.error(
                    f"❌ Insufficient data for {symbol}: {len(df) if df is not None else 0} candles")
                raise ValueError("Not enough data for training")

            logger.info(f"✅ Loaded {len(df)} candles for {symbol}")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")

            # Обучить модель (first attempt, possibly with cached data)
            logger.info(f"🎓 Training model for {symbol}...")
            self.progress.begin_symbol(symbol, phase=TrainingProgressTracker.PHASE_TRAINING)
            try:
                metrics = self.trainer.train_model(
                    symbol=symbol,
                    df=df,
                    test_size=0.2
                )
            except Exception as train_err:  # Exception excludes KeyboardInterrupt/SystemExit
                # If the first attempt fails (e.g. cached data is stale or the
                # cleaned feature set is too small), fetch a fresh copy from the
                # exchange and try once more before giving up.
                logger.warning(
                    f"First training attempt for {symbol} failed ({train_err}); "
                    "retrying with fresh data from exchange..."
                )
                df = await self.data_fetcher.fetch_full_history(
                    symbol=symbol,
                    timeframe=self.timeframe,
                    force_reload=True,  # bypass the cache
                )
                if df is None or len(df) < self.trainer.min_training_samples:
                    raise ValueError(
                        f"Insufficient data even after cache refresh: "
                        f"{len(df) if df is not None else 0} candles"
                    ) from train_err
                logger.info(f"Reloaded {len(df)} candles for {symbol}, retrying training...")
                # This second call is allowed to raise — caller will log the real error.
                metrics = self.trainer.train_model(
                    symbol=symbol,
                    df=df,
                    test_size=0.2
                )

            if metrics:
                logger.info(f"✅ Training completed for {symbol}")
                logger.info(f"   Accuracy: {metrics.accuracy:.4f}")
                logger.info(f"   F1 Score: {metrics.f1_score:.4f}")
                return metrics
            else:
                # train_model now re-raises on failure, so this branch is a
                # safety net for any future caller that resets the old contract.
                raise RuntimeError(
                    f"train_model returned no metrics for {symbol}; check logs above"
                )
        finally:
            # Always remove the lock file regardless of success / failure
            try:
                _lock_path.unlink(missing_ok=True)
            except Exception as _e:
                logger.debug(f"Could not remove training lock file: {_e}")

    def _print_summary(self):
        """Вывести итоговый отчет"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 TRAINING PIPELINE SUMMARY")
        logger.info("=" * 80)

        started = datetime.fromisoformat(self.training_stats['started_at'])
        completed = datetime.fromisoformat(self.training_stats['completed_at'])
        duration = completed - started

        logger.info(f"⏱️  Duration: {duration}")
        logger.info(f"📈 Total symbols: {self.training_stats['total_symbols']}")
        logger.info(f"✅ Successful: {self.training_stats['successful']}")
        logger.info(f"⏭️  Skipped: {self.training_stats['skipped']}")
        logger.info(f"❌ Failed: {self.training_stats['failed']}")

        if self.training_stats['successful'] > 0:
            logger.info("\n🎯 Successfully trained models:")
            for symbol, result in self.training_stats['results'].items():
                if result['status'] == 'success':
                    metrics = result['metrics']
                    logger.info(
                        f"   • {symbol}: accuracy={metrics['accuracy']:.4f}, f1={metrics['f1_score']:.4f}")

        if self.training_stats['failed'] > 0:
            logger.info("\n❌ Failed models:")
            for symbol, result in self.training_stats['results'].items():
                if result['status'] == 'failed':
                    logger.info(f"   • {symbol}: {result['error']}")

        logger.info("=" * 80)

    async def retrain_if_needed(self, symbol: str, max_age_days: int = 7) -> bool:
        """
        Переобучить модель если она устарела

        Args:
            symbol: Торговый символ
            max_age_days: Максимальный возраст модели в днях

        Returns:
            True если модель была переобучена
        """
        model_info = self.trainer.get_model_info(symbol)

        if model_info is None:
            # Модель не существует, обучить
            logger.info(f"No model found for {symbol}, training...")
            await self.train_symbol(symbol)
            return True

        # Проверить возраст модели
        training_date = datetime.fromisoformat(model_info['training_date'])
        age = datetime.now() - training_date

        if age.days > max_age_days:
            logger.info(f"Model for {symbol} is {age.days} days old, retraining...")
            self.force_retrain = True
            await self.train_symbol(symbol)
            return True

        return False

    def get_training_report(self) -> str:
        """
        Получить текстовый отчет об обучении

        Returns:
            Форматированный отчет
        """
        if not self.training_stats.get('completed_at'):
            return "Training not completed yet"

        report = []
        report.append("=" * 80)
        report.append("ML TRAINING REPORT")
        report.append("=" * 80)

        started = datetime.fromisoformat(self.training_stats['started_at'])
        completed = datetime.fromisoformat(self.training_stats['completed_at'])
        duration = completed - started

        report.append(f"\nDuration: {duration}")
        report.append(f"Total: {self.training_stats['total_symbols']}")
        report.append(f"✅ Success: {self.training_stats['successful']}")
        report.append(f"⏭️  Skipped: {self.training_stats['skipped']}")
        report.append(f"❌ Failed: {self.training_stats['failed']}")

        if self.training_stats['successful'] > 0:
            report.append("\nTrained Models:")
            for symbol, result in sorted(self.training_stats['results'].items()):
                if result['status'] == 'success':
                    m = result['metrics']
                    report.append(f"  {symbol}: acc={m['accuracy']:.3f}, f1={m['f1_score']:.3f}")

        report.append("=" * 80)

        return "\n".join(report)

    # ------------------------------------------------------------------
    # Incremental fine-tuning from live trade outcomes
    # ------------------------------------------------------------------

    async def fine_tune_from_trades(
        self,
        trade_records: List[Dict],
    ) -> Dict:
        """
        Fine-tune pre-trained models with the outcomes of recent bot trades.

        This is the "layer-on-top" step: after the historical foundation is
        trained, every closed trade yields a verified signal (direction +
        outcome) that is used to nudge the model toward real market behaviour.

        Args:
            trade_records: List of dicts, each containing:
                'symbol'   — e.g. 'BTCUSDT'
                'side'     — 'BUY' or 'SELL'
                'pnl'      — realised profit/loss in USDT
                'entry_df' — pd.DataFrame with OHLCV up to entry (≥ lookback rows)

        Returns:
            Dict with per-symbol fine-tune results.
        """
        results: Dict[str, str] = {}

        for record in trade_records:
            symbol = record.get('symbol')
            if not symbol:
                continue

            side = record.get('side', '').upper()
            pnl = float(record.get('pnl', 0))
            entry_df = record.get('entry_df')

            if entry_df is None or not isinstance(entry_df, object):
                results[symbol] = 'skipped: no entry_df'
                continue

            # Map trade outcome to the model's target space (UP=1 / DOWN=-1 / HOLD=0).
            # The target represents the ACTUAL correct direction:
            #   profitable BUY → price went UP   → correct direction was 1
            #   profitable SELL → price went DOWN → correct direction was -1
            #   losing BUY → price went DOWN → correct direction was -1
            #   losing SELL → price went UP → correct direction was 1
            #   breakeven → no clear signal → 0
            if pnl > 0 and side == 'BUY':
                outcome = 1      # Price moved UP — long was correct
            elif pnl > 0 and side == 'SELL':
                outcome = -1     # Price moved DOWN — short was correct
            elif pnl < 0 and side == 'BUY':
                outcome = -1     # Price moved DOWN — long was wrong
            elif pnl < 0 and side == 'SELL':
                outcome = 1      # Price moved UP — short was wrong
            else:
                outcome = 0      # Breakeven / uncertain

            ok = self.trainer.fine_tune_from_trade(
                symbol=symbol,
                recent_df=entry_df,
                trade_outcome=outcome,
            )
            results[symbol] = 'updated' if ok else 'failed'

        return results


async def initialize_ml_system(
    exchange,
    symbols: List[str],
    force_retrain: bool = False,
    models_dir: str = '/var/lib/trading-bot/models',
) -> Dict:
    """
    Инициализировать ML систему: загрузить данные и обучить модели

    Args:
        exchange: ExchangeAdapter instance
        symbols: Список торговых символов
        force_retrain: Принудительное переобучение
        models_dir: Директория для хранения обученных моделей

    Returns:
        Dict со статистикой обучения
    """
    pipeline = MLTrainingPipeline(
        exchange=exchange,
        symbols=symbols,
        timeframe='1h',
        force_retrain=force_retrain,
        models_dir=models_dir,
    )

    stats = await pipeline.train_all_symbols()

    logger.info("\n" + pipeline.get_training_report())

    return stats

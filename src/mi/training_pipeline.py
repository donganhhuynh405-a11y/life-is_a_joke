"""
ML Training Pipeline

Автоматический пайплайн обучения ML моделей для всех торгуемых символов.
Запускается при старте бота и периодически для переобучения.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

from .historical_data_fetcher import HistoricalDataFetcher
from .market_specific_trainer import MarketSpecificTrainer, ModelMetrics

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
    ):
        """
        Args:
            exchange: ExchangeAdapter instance
            symbols: Список торговых символов
            timeframe: Таймфрейм для обучения
            force_retrain: Принудительное переобучение существующих моделей
            models_dir: Директория для хранения обученных моделей
        """
        self.exchange = exchange
        self.symbols = symbols
        self.timeframe = timeframe
        self.force_retrain = force_retrain

        self.data_fetcher = HistoricalDataFetcher(exchange)
        self.trainer = MarketSpecificTrainer(models_dir=models_dir)

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
                else:
                    self.training_stats['skipped'] += 1
                    self.training_stats['results'][symbol] = {
                        'status': 'skipped',
                        'reason': 'Model already exists and force_retrain=False'
                    }

            except Exception as e:
                logger.error(f"❌ Failed to train {symbol}: {e}", exc_info=True)
                self.training_stats['failed'] += 1
                self.training_stats['results'][symbol] = {
                    'status': 'failed',
                    'error': str(e)
                }

        self.training_stats['completed_at'] = datetime.now().isoformat()

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

            # Обучить модель
            logger.info(f"🎓 Training model for {symbol}...")
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
                raise ValueError("Training failed")
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

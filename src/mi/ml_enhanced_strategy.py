"""
ML-Enhanced Position Strategy

Интегрирует ML-предсказания в процесс создания позиций,
комбинируя классические индикаторы с персональными моделями для каждого рынка.
"""

import logging
import pandas as pd
from typing import Dict, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class MLEnhancedStrategy:
    """
    Улучшенная стратегия с ML-предсказаниями для каждого рынка
    """

    def __init__(self, trainer, config):
        """
        Args:
            trainer: MarketSpecificTrainer instance
            config: Bot configuration
        """
        self.trainer = trainer
        self.config = config

        self.min_ml_confidence = 0.6
        self.min_model_accuracy = 0.55
        self.classic_weight = 0.6
        self.ml_weight = 0.4

    def enhance_signal_with_ml(
        self,
        symbol: str,
        classic_signal: Dict,
        recent_data: pd.DataFrame
    ) -> Dict:
        """
        Улучшить классический сигнал с помощью ML-предсказания

        Args:
            symbol: Торговый символ
            classic_signal: Результат анализа классических индикаторов
            recent_data: Последние данные для ML-предсказания

        Returns:
            Улучшенный сигнал с комбинированной уверенностью
        """
        ml_prediction = self.trainer.predict(symbol, recent_data)

        if ml_prediction is None:
            logger.debug(f"No ML prediction for {symbol}, using classic signal only")
            return {
                **classic_signal,
                'ml_enhanced': False,
                'ml_available': False
            }

        model_accuracy = ml_prediction.get('model_accuracy', 0.0)
        if model_accuracy < self.min_model_accuracy:
            logger.debug(f"Model accuracy too low for {symbol}: {model_accuracy:.4f}")
            return {
                **classic_signal,
                'ml_enhanced': False,
                'ml_available': True,
                'ml_accuracy_too_low': True
            }

        ml_confidence = ml_prediction.get('confidence', 0.0)
        if ml_confidence < self.min_ml_confidence:
            logger.debug(f"ML confidence too low for {symbol}: {ml_confidence:.4f}")
            return {
                **classic_signal,
                'ml_enhanced': False,
                'ml_available': True,
                'ml_confidence_too_low': True
            }

        classic_action = classic_signal.get('signal', 'HOLD')
        ml_action = ml_prediction.get('signal', 'HOLD')

        signal_values = {'BUY': 1, 'HOLD': 0, 'SELL': -1, 'EXIT': 0}
        classic_value = signal_values.get(classic_action, 0)
        ml_value = signal_values.get(ml_action, 0)

        combined_value = (classic_value * self.classic_weight +
                          ml_value * self.ml_weight)

        if combined_value > 0.3:
            final_signal = 'BUY'
        elif combined_value < -0.3:
            final_signal = 'SELL'
        else:
            final_signal = 'HOLD'

        classic_conf = classic_signal.get('confidence', 0.5)
        combined_confidence = (classic_conf * self.classic_weight +
                               ml_confidence * self.ml_weight)

        if classic_action == ml_action and classic_action != 'HOLD':
            combined_confidence = min(combined_confidence * 1.2, 1.0)
            signal_agreement = True
        else:
            signal_agreement = False

        logger.info(f"🤖 ML-Enhanced signal for {symbol}:")
        logger.info(f"   Classic: {classic_action} (conf: {classic_conf:.2f})")
        logger.info(f"   ML: {ml_action} (conf: {ml_confidence:.2f}, acc: {model_accuracy:.2f})")
        logger.info(f"   Combined: {final_signal} (conf: {combined_confidence:.2f})")

        return {
            **classic_signal,
            'signal': final_signal,
            'confidence': combined_confidence,
            'ml_enhanced': True,
            'ml_available': True,
            'ml_prediction': ml_prediction,
            'classic_signal': classic_action,
            'ml_signal': ml_action,
            'signals_agree': signal_agreement,
            'model_accuracy': model_accuracy,
            'enhancement_timestamp': datetime.now().isoformat()
        }

    def calculate_optimal_position_size(
        self,
        symbol: str,
        signal: Dict,
        base_position_size: float
    ) -> float:
        """
        Рассчитать оптимальный размер позиции на основе ML-метрик

        Args:
            symbol: Торговый символ
            signal: Улучшенный сигнал
            base_position_size: Базовый размер позиции

        Returns:
            Оптимизированный размер позиции
        """
        if not signal.get('ml_enhanced', False):
            return base_position_size

        confidence = signal.get('confidence', 0.5)
        model_accuracy = signal.get('model_accuracy', 0.5)
        signals_agree = signal.get('signals_agree', False)

        confidence_multiplier = 0.5 + (confidence * 1.0)
        accuracy_multiplier = model_accuracy * 2.0
        agreement_multiplier = 1.2 if signals_agree else 1.0

        total_multiplier = min(
            confidence_multiplier * accuracy_multiplier * agreement_multiplier,
            2.0
        )
        total_multiplier = max(total_multiplier, 0.5)

        optimized_size = base_position_size * total_multiplier

        logger.info(
            f"📊 Position size for {symbol}: {base_position_size:.4f} → {optimized_size:.4f} (×{total_multiplier:.2f})")

        return optimized_size

    def should_create_position(
        self,
        symbol: str,
        signal: Dict,
        min_confidence_threshold: float = 0.6
    ) -> Tuple[bool, str]:
        """
        Определить, следует ли создавать позицию

        Args:
            symbol: Торговый символ
            signal: Улучшенный сигнал
            min_confidence_threshold: Минимальный порог уверенности

        Returns:
            (should_create, reason)
        """
        action = signal.get('signal', 'HOLD')
        confidence = signal.get('confidence', 0.0)

        if action not in ['BUY', 'SELL']:
            return False, f"Signal is {action}, not actionable"

        if confidence < min_confidence_threshold:
            return False, f"Confidence {confidence:.2f} < threshold {min_confidence_threshold:.2f}"

        if signal.get('ml_enhanced', False):
            model_accuracy = signal.get('model_accuracy', 0.0)

            if model_accuracy < 0.6:
                adjusted_threshold = min_confidence_threshold * 1.2
                if confidence < adjusted_threshold:
                    return False, f"Low model accuracy ({model_accuracy:.2f}), need higher confidence"

            if not signal.get('signals_agree', False):
                adjusted_threshold = min_confidence_threshold * 1.15
                if confidence < adjusted_threshold:
                    return False, "Classic and ML signals disagree, need higher confidence"

        return True, f"{action} signal with {confidence:.2f} confidence"

    def get_model_statistics(self, symbols: list) -> Dict:
        """
        Получить статистику по моделям всех символов

        Args:
            symbols: Список торговых символов

        Returns:
            Dict со статистикой
        """
        stats = {
            'total_symbols': len(symbols),
            'trained_models': 0,
            'models': {}
        }

        for symbol in symbols:
            model_info = self.trainer.get_model_info(symbol)
            if model_info:
                stats['trained_models'] += 1
                stats['models'][symbol] = model_info

        return stats

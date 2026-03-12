"""
Market-Specific ML Model Trainer

Обучает персональную ML модель для каждого торгуемого символа
на полной исторической глубине данных этого рынка.

Foundation pre-training approach:
  1. Download full history from coin inception date.
  2. Extract rich features via AdvancedFeatureEngineer (100+ indicators
     covering price, volume, volatility, momentum, patterns and market
     regimes).
  3. Use regime-balanced sampling so the model trains equally on bull,
     bear and sideways markets — not just the most recent trend.
  4. Persist the trained model as the permanent "historical foundation".
  5. Incrementally fine-tune from live bot trade outcomes via
     fine_tune_from_trade(), layering knowledge on top of the foundation
     without overwriting it.
"""

import json
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Метрики качества модели"""
    symbol: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    train_samples: int
    test_samples: int
    training_date: str
    model_version: str = "2.0"
    pretrained_from_history: bool = True
    fine_tuned_trades: int = 0
    # regime coverage: fraction of samples per regime in training set
    regime_coverage: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


class MarketSpecificTrainer:
    """
    Тренер ML моделей специфичных для каждого рынка.

    Uses AdvancedFeatureEngineer from crypto_features.py to build a rich
    100+ feature set covering price, volume, volatility, momentum, candle
    patterns and market-regime signals.  Training is regime-balanced so the
    model learns to trade bull, bear and sideways markets equally well.

    After the initial historical foundation is trained, live bot trades can
    be used to fine-tune the model incrementally via fine_tune_from_trade().
    """

    def __init__(self, models_dir: str = "/var/lib/trading-bot/models"):
        """
        Args:
            models_dir: Директория для сохранения обученных моделей
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # Minimum candles required before training
        self.min_training_samples = 1000

        # Sliding-window look-back for feature extraction
        self.lookback_period = 60

        # Try to load the rich feature engineer (from crypto_features.py).
        # Falls back to the lightweight internal calculator when unavailable.
        try:
            from .crypto_features import AdvancedFeatureEngineer
            self._feature_engineer = AdvancedFeatureEngineer()
            self._use_advanced_features = True
            logger.info("✅ AdvancedFeatureEngineer loaded — using rich feature set (100+ features)")
        except Exception as _e:
            self._feature_engineer = None
            self._use_advanced_features = False
            logger.warning(f"AdvancedFeatureEngineer unavailable ({_e}) — using basic features")

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_model_path(self, symbol: str) -> Path:
        """Путь к файлу модели"""
        symbol_dir = self.models_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        return symbol_dir / "model.pkl"

    def _get_metrics_path(self, symbol: str) -> Path:
        """Путь к файлу метрик"""
        symbol_dir = self.models_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        return symbol_dir / "metrics.json"

    def _get_scaler_path(self, symbol: str) -> Path:
        """Путь к файлу scaler"""
        symbol_dir = self.models_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        return symbol_dir / "scaler.pkl"

    def _get_feature_cols_path(self, symbol: str) -> Path:
        """Path to the saved list of training feature column names."""
        symbol_dir = self.models_dir / symbol
        symbol_dir.mkdir(exist_ok=True)
        return symbol_dir / "feature_cols.json"

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def _load_feature_cols(self, symbol: str) -> Optional[List[str]]:
        """Load the training feature column list for a symbol, if saved."""
        path = self._get_feature_cols_path(symbol)
        if not path.exists():
            return None
        try:
            with open(path, 'r') as fh:
                return json.load(fh)
        except Exception:
            return None

    def _align_inference_features(
        self,
        feat_df: pd.DataFrame,
        training_cols: List[str],
    ) -> np.ndarray:
        """
        Align an inference feature DataFrame to the exact columns used during
        training.  Missing columns are filled with 0; extra columns are dropped.
        """
        # Add missing columns as 0
        for col in training_cols:
            if col not in feat_df.columns:
                feat_df = feat_df.copy()
                feat_df[col] = 0.0
        # Select and order columns exactly as during training
        return feat_df[training_cols].values.astype(np.float32)

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute technical indicators (lightweight fallback).

        The primary path uses AdvancedFeatureEngineer (see
        _extract_features_rich).  This method is kept as a stable fallback
        when that import is unavailable.
        """
        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands
        sma_20 = df['close'].rolling(window=20).mean()
        std_20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma_20 + (std_20 * 2)
        df['bb_middle'] = sma_20
        df['bb_lower'] = sma_20 - (std_20 * 2)

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['atr'] = true_range.rolling(window=14).mean()

        # Volume SMA
        df['volume_sma'] = df['volume'].rolling(window=20).mean()

        # Заполнить NaN
        df.fillna(method='bfill', inplace=True)
        df.fillna(method='ffill', inplace=True)

        return df

    # ------------------------------------------------------------------
    # Rich feature extraction using AdvancedFeatureEngineer
    # ------------------------------------------------------------------

    def _extract_features_rich(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract the full 100+ feature set via AdvancedFeatureEngineer.

        Falls back to calculate_technical_indicators() when the advanced
        engineer is unavailable.  All features are numeric and NaN-filled
        before returning.
        """
        if self._use_advanced_features and self._feature_engineer is not None:
            try:
                feat_df = self._feature_engineer.extract_all_features(
                    ohlcv=df,
                    onchain=None,
                    orderbook=None,
                    cross_exchange=None,
                )
                # Fill NaN conservatively
                feat_df = feat_df.ffill().bfill()
                # Drop any column that is still entirely NaN or non-numeric
                feat_df = feat_df.select_dtypes(include=[np.number])
                feat_df.dropna(axis=1, how='all', inplace=True)
                logger.debug(f"Rich feature extraction: {len(feat_df.columns)} features")
                return feat_df
            except Exception as e:
                logger.warning(f"AdvancedFeatureEngineer failed ({e}), falling back to basic features")

        # Fallback: basic indicators attached to the OHLCV frame
        df_ind = self.calculate_technical_indicators(df)
        basic_cols = [
            'open', 'high', 'low', 'close', 'volume',
            'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_middle', 'bb_lower',
            'atr', 'volume_sma'
        ]
        available = [c for c in basic_cols if c in df_ind.columns]
        return df_ind[available].ffill().bfill()

    # ------------------------------------------------------------------
    # Regime-balanced sampling
    # ------------------------------------------------------------------

    def _assign_regime(self, df_feat: pd.DataFrame, close: pd.Series) -> pd.Series:
        """
        Assign a market regime label to each row so we can balance training.

        Regimes (stored as string labels):
          'bull_trend'   — uptrend with strong momentum
          'bear_trend'   — downtrend with strong momentum
          'sideways'     — low ADX, ranging market
          'high_vol'     — elevated volatility (crash / recovery)
        """
        regimes = pd.Series('sideways', index=df_feat.index)

        # Use pre-computed regime columns when available (from AdvancedFeatureEngineer)
        if 'adx' in df_feat.columns and 'trend_direction' in df_feat.columns:
            adx = df_feat['adx'].fillna(0)
            trend = df_feat['trend_direction'].fillna(0)
            trending = adx > 25
            regimes[trending & (trend > 0)] = 'bull_trend'
            regimes[trending & (trend < 0)] = 'bear_trend'

        if 'high_volatility' in df_feat.columns:
            regimes[df_feat['high_volatility'].fillna(0) == 1] = 'high_vol'

        # Fallback: derive from close prices when regime columns are absent
        if 'adx' not in df_feat.columns:
            sma50 = close.rolling(50).mean()
            sma200 = close.rolling(200).mean()
            vol = close.pct_change().rolling(20).std()
            vol_ma = vol.rolling(50).mean()
            bull = (close > sma200) & (sma50 > sma200)
            bear = (close < sma200) & (sma50 < sma200)
            hv = vol > (vol_ma * 1.5)
            regimes[bull] = 'bull_trend'
            regimes[bear] = 'bear_trend'
            regimes[hv] = 'high_vol'

        return regimes

    def _balance_by_regime(
        self,
        X: np.ndarray,
        y: np.ndarray,
        regimes: np.ndarray,
        min_per_regime: int = 500,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Oversample under-represented regimes so the model trains on all
        market conditions, not just the most prevalent one.
        """
        unique_regimes = np.unique(regimes)
        if len(unique_regimes) <= 1:
            return X, y

        # Count per regime
        counts = {r: int(np.sum(regimes == r)) for r in unique_regimes}
        logger.info(f"Regime distribution before balancing: {counts}")

        X_parts = [X]
        y_parts = [y]

        for regime in unique_regimes:
            idx = np.where(regimes == regime)[0]
            if len(idx) < min_per_regime and len(idx) > 0:
                # Oversample with replacement
                needed = min_per_regime - len(idx)
                repeat_idx = np.random.choice(idx, size=needed, replace=True)
                X_parts.append(X[repeat_idx])
                y_parts.append(y[repeat_idx])

        X_bal = np.concatenate(X_parts, axis=0)
        y_bal = np.concatenate(y_parts, axis=0)

        # Shuffle
        shuffle_idx = np.random.permutation(len(X_bal))
        return X_bal[shuffle_idx], y_bal[shuffle_idx]

    # ------------------------------------------------------------------
    # Feature-and-label preparation (new, regime-aware)
    # ------------------------------------------------------------------

    def prepare_features_and_labels(
        self,
        df: pd.DataFrame,
        prediction_horizon: int = 1
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Build feature vectors and direction labels from OHLCV data.

        Instead of flattening the full lookback window (which creates a very
        wide, slow-to-train feature space), we use the CURRENT point-in-time
        feature row directly.  The rich AdvancedFeatureEngineer already
        encodes temporal information through rolling statistics (momentum,
        moving-average distances, volatility regimes, etc.), so each row
        is a complete description of the market state at that moment.

        This keeps the feature dimensionality at ~88 per sample regardless
        of the lookback period, making GradientBoosting practical even on
        millions of historical candles.
        """
        feat_df = self._extract_features_rich(df)

        # Compute future return for labels
        future_return = df['close'].shift(-prediction_horizon) / df['close'] - 1

        # Assign market regime (used later for regime-balanced training)
        regimes = self._assign_regime(feat_df, df['close'])

        # Align indices
        common_idx = feat_df.index.intersection(future_return.dropna().index)
        feat_df = feat_df.loc[common_idx]
        future_return = future_return.loc[common_idx]
        regimes = regimes.loc[common_idx]

        # Replace infinity values with NaN so they are caught by the filter below
        # (some technical indicators produce inf on division-by-zero or log(0))
        feat_df = feat_df.replace([np.inf, -np.inf], np.nan)

        # Drop rows with any remaining NaN in features
        # (first ~200 rows typically have NaN from rolling windows)
        valid_mask = ~feat_df.isnull().any(axis=1)
        feat_df = feat_df[valid_mask]
        future_return = future_return[valid_mask]
        regimes = regimes[valid_mask]

        if len(feat_df) < self.min_training_samples:
            raise ValueError(
                f"Insufficient data after cleaning: {len(feat_df)} < {self.min_training_samples}")

        X = feat_df.values.astype(np.float32)
        feature_cols = list(feat_df.columns)  # saved during train_model

        y_list: List[int] = []
        for ret in future_return.values:
            if ret > 0.005:
                y_list.append(1)     # UP
            elif ret < -0.005:
                y_list.append(-1)    # DOWN
            else:
                y_list.append(0)     # HOLD

        y = np.array(y_list, dtype=np.int32)
        reg = regimes.values

        logger.info(
            f"✅ Prepared {len(X):,} samples × {X.shape[1]} features "
            f"(horizon={prediction_horizon}h)")

        return X, y, reg, feature_cols

    # ------------------------------------------------------------------
    # Model training  (foundation pre-training on full history)
    # ------------------------------------------------------------------

    def train_model(
        self,
        symbol: str,
        df: pd.DataFrame,
        test_size: float = 0.2
    ) -> Optional[ModelMetrics]:
        """
        Foundation pre-training on full historical data.

        Workflow:
          1. Extract 100+ features via AdvancedFeatureEngineer.
          2. Build sliding-window samples covering the full history.
          3. Balance samples across market regimes (bull/bear/sideways/
             high-volatility) so the model trains on all conditions.
          4. Train a GradientBoostingClassifier (preferred) or fall back
             to RandomForest if GBM is unavailable.
          5. Persist the model, scaler, and rich metrics to disk.

        Args:
            symbol: Trading symbol (e.g. 'BTCUSDT')
            df: Full OHLCV history DataFrame
            test_size: Fraction of data held out for evaluation

        Returns:
            ModelMetrics on success, None on failure.
        """
        logger.info(f"🎓 Foundation pre-training for {symbol}: {len(df):,} candles")

        try:
            # Build feature matrix + labels + regime labels
            X, y, reg, feature_cols = self.prepare_features_and_labels(df)

            # Hold out the last test_size fraction (time-ordered, no shuffle)
            split_idx = int(len(X) * (1 - test_size))
            X_train_raw, X_test = X[:split_idx], X[split_idx:]
            y_train_raw, y_test = y[:split_idx], y[split_idx:]
            reg_train = reg[:split_idx]

            # Regime-balanced oversampling on the training set
            X_train, y_train = self._balance_by_regime(X_train_raw, y_train_raw, reg_train)

            logger.info(
                f"📊 Train (balanced): {len(X_train):,}  Test: {len(X_test):,}  "
                f"Features: {X_train.shape[1]}")

            # Compute regime coverage for metadata
            regime_coverage: Dict[str, float] = {}
            for r in np.unique(reg_train):
                regime_coverage[str(r)] = float(np.mean(reg_train == r))

            # Normalise
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            # Primary model: GradientBoosting (captures non-linear patterns well)
            try:
                from sklearn.ensemble import GradientBoostingClassifier
                model = GradientBoostingClassifier(
                    n_estimators=200,
                    max_depth=5,
                    learning_rate=0.05,
                    subsample=0.8,
                    random_state=42,
                )
                logger.info("🔄 Training GradientBoostingClassifier (regime-balanced)…")
                model.fit(X_train_scaled, y_train)
            except Exception as gbm_err:
                logger.warning(f"GBM training failed ({gbm_err}), falling back to RandomForest")
                from sklearn.ensemble import RandomForestClassifier
                model = RandomForestClassifier(
                    n_estimators=200,
                    max_depth=10,
                    min_samples_split=10,
                    random_state=42,
                    n_jobs=-1,
                )
                logger.info("🔄 Training RandomForestClassifier…")
                model.fit(X_train_scaled, y_train)

            # Evaluate
            y_pred = model.predict(X_test_scaled)
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

            accuracy = accuracy_score(y_test, y_pred)
            precision = precision_score(y_test, y_pred, average='weighted', zero_division=0)
            recall = recall_score(y_test, y_pred, average='weighted', zero_division=0)
            f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)

            metrics = ModelMetrics(
                symbol=symbol,
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1,
                train_samples=len(X_train),
                test_samples=len(X_test),
                training_date=datetime.now().isoformat(),
                pretrained_from_history=True,
                fine_tuned_trades=0,
                regime_coverage=regime_coverage,
            )

            logger.info("✅ Foundation pre-training completed!")
            logger.info(f"   Accuracy: {accuracy:.4f}")
            logger.info(f"   Precision: {precision:.4f}")
            logger.info(f"   Recall:    {recall:.4f}")
            logger.info(f"   F1 Score:  {f1:.4f}")
            logger.info(f"   Regimes:   {regime_coverage}")

            # Persist
            for path, obj in [
                (self._get_model_path(symbol), model),
                (self._get_scaler_path(symbol), scaler),
            ]:
                with open(path, 'wb') as fh:
                    pickle.dump(obj, fh)

            with open(self._get_metrics_path(symbol), 'w') as fh:
                json.dump(metrics.to_dict(), fh, indent=2)

            # Save the feature column list so inference can align features
            if feature_cols is not None:
                with open(self._get_feature_cols_path(symbol), 'w') as fh:
                    json.dump(feature_cols, fh)

            logger.info(f"💾 Model saved to {self._get_model_path(symbol)}")
            return metrics

        except Exception as e:
            logger.error(f"❌ Failed to train model for {symbol}: {e}", exc_info=True)
            raise  # re-raise so training_pipeline.py reports the actual root cause

    # ------------------------------------------------------------------
    # Incremental fine-tuning from live bot trades
    # ------------------------------------------------------------------

    def fine_tune_from_trade(
        self,
        symbol: str,
        recent_df: pd.DataFrame,
        trade_outcome: int,
    ) -> bool:
        """
        Incrementally update a pre-trained model with the outcome of a
        single live bot trade.

        The update is a warm-start re-fit using the existing model as the
        starting point (for GradientBoosting this means adding extra
        estimators; for RandomForest the new sample is appended to an
        internal buffer and the model is periodically retrained).

        Args:
            symbol: Trading symbol.
            recent_df: OHLCV DataFrame ending at the trade entry
                (must have at least `lookback_period` rows).
            trade_outcome: Actual direction (1=profit long, -1=profit short,
                0=breakeven/stopped-out).

        Returns:
            True if the model was updated successfully.
        """
        model_data = self.load_model(symbol)
        if model_data is None:
            logger.warning(f"No model for {symbol} — skipping fine-tune")
            return False

        model, scaler, metrics_dict = model_data

        try:
            # Build one feature vector from the recent window
            feat_df = self._extract_features_rich(recent_df)
            feat_df = feat_df.ffill().bfill()
            if len(feat_df) < self.lookback_period:
                logger.warning(
                    f"fine_tune_from_trade: insufficient data ({len(feat_df)} rows)")
                return False

            # Align features to training column set
            training_cols = self._load_feature_cols(symbol)
            if training_cols is not None:
                X_new = self._align_inference_features(feat_df.iloc[[-1]], training_cols)
            else:
                X_new = feat_df.iloc[[-1]].values.astype(np.float32)

            if scaler is not None:
                # Scale using the training scaler
                try:
                    X_new_scaled = scaler.transform(X_new)
                except ValueError as ve:
                    # Feature count mismatch — this indicates an alignment problem.
                    # Abort rather than corrupt the scaler.
                    logger.error(
                        f"Feature mismatch in fine_tune_from_trade for {symbol}: {ve}. "
                        "Re-run training to rebuild the model with the current feature set.")
                    return False
            else:
                X_new_scaled = X_new

            y_new = np.array([trade_outcome], dtype=np.int32)

            # Accumulate trade samples in a buffer; trigger a warm-start re-fit
            # once enough samples are collected.  GradientBoostingClassifier and
            # RandomForest do not support partial_fit, so buffer accumulation is
            # the correct approach for these estimators.
            buffer_path = self._get_model_path(symbol).parent / "finetune_buffer.pkl"
            buffer: List[Tuple] = []
            if buffer_path.exists():
                with open(buffer_path, 'rb') as fh:
                    try:
                        buffer = pickle.load(fh)
                    except Exception:
                        buffer = []
            buffer.append((X_new_scaled[0], int(trade_outcome)))
            with open(buffer_path, 'wb') as fh:
                pickle.dump(buffer, fh)

            logger.debug(f"Fine-tune buffer for {symbol}: {len(buffer)} samples accumulated")

            # Trigger warm-start mini-retrain once enough samples are buffered.
            # The buffer represents verified live-trade outcomes layered on top of
            # the historical foundation — we fit only on the buffer samples using
            # warm_start so the existing tree ensemble is extended, not replaced.
            BUFFER_RETRAIN_THRESHOLD = 50
            if len(buffer) >= BUFFER_RETRAIN_THRESHOLD:
                logger.info(
                    f"🔄 Triggering warm-start fine-tune for {symbol} "
                    f"({len(buffer)} new trade samples)…")
                X_buf = np.array([b[0] for b in buffer], dtype=np.float32)
                y_buf = np.array([b[1] for b in buffer], dtype=np.int32)

                try:
                    # Use warm_start to extend the existing ensemble rather than
                    # fitting from scratch, preserving the historical foundation.
                    if hasattr(model, 'warm_start'):
                        original_n = getattr(model, 'n_estimators', 200)
                        model.warm_start = True
                        model.n_estimators = original_n + 20
                        model.fit(X_buf, y_buf)
                    else:
                        model.fit(X_buf, y_buf)

                    # Clear buffer and persist updated model
                    buffer_path.unlink(missing_ok=True)
                    with open(self._get_model_path(symbol), 'wb') as fh:
                        pickle.dump(model, fh)
                    logger.info(f"✅ Warm-start fine-tune complete for {symbol}")
                except Exception as rt_err:
                    logger.warning(f"Mini-retrain failed: {rt_err}")
                    return False

            # Update trade counter in metrics
            if metrics_dict is not None:
                metrics_dict['fine_tuned_trades'] = metrics_dict.get('fine_tuned_trades', 0) + 1
                metrics_dict['last_fine_tune'] = datetime.now().isoformat()
                with open(self._get_metrics_path(symbol), 'w') as fh:
                    json.dump(metrics_dict, fh, indent=2)

            return True

        except Exception as e:
            logger.error(f"fine_tune_from_trade failed for {symbol}: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def load_model(self, symbol: str) -> Optional[Tuple]:
        """
        Загрузить обученную модель

        Args:
            symbol: Торговый символ

        Returns:
            (model, scaler, metrics) или None
        """
        model_path = self._get_model_path(symbol)
        scaler_path = self._get_scaler_path(symbol)
        metrics_path = self._get_metrics_path(symbol)

        if not model_path.exists():
            logger.warning(f"No trained model found for {symbol}")
            return None

        try:
            with open(model_path, 'rb') as f:
                model = pickle.load(f)

            scaler = None
            if scaler_path.exists():
                with open(scaler_path, 'rb') as f:
                    scaler = pickle.load(f)

            metrics = None
            if metrics_path.exists():
                with open(metrics_path, 'r') as f:
                    metrics = json.load(f)

            acc = metrics.get('accuracy', 'N/A') if metrics else 'N/A'
            ft = metrics.get('fine_tuned_trades', 0) if metrics else 0
            logger.info(f"✅ Loaded model for {symbol} (acc={acc}, fine-tuned trades={ft})")

            return model, scaler, metrics

        except Exception as e:
            logger.error(f"Failed to load model for {symbol}: {e}")
            return None

    def predict(
        self,
        symbol: str,
        recent_data: pd.DataFrame
    ) -> Optional[Dict]:
        """
        Сделать предсказание для символа

        Args:
            symbol: Торговый символ
            recent_data: DataFrame с последними данными (минимум lookback_period свечей)

        Returns:
            Dict с предсказанием и уверенностью
        """
        model_data = self.load_model(symbol)
        if model_data is None:
            return None

        model, scaler, metrics = model_data

        try:
            # Use the same rich feature extraction as training
            feat_df = self._extract_features_rich(recent_data)
            feat_df = feat_df.ffill().bfill()

            if len(feat_df) < self.lookback_period:
                logger.warning(
                    f"Insufficient data for prediction: {len(feat_df)} < {self.lookback_period}")
                return None

            # Align features to training column set and take the last row
            training_cols = self._load_feature_cols(symbol)
            if training_cols is not None:
                window = self._align_inference_features(feat_df.iloc[[-1]], training_cols)
            else:
                window = feat_df.iloc[[-1]].values.astype(np.float32)

            if scaler is not None:
                try:
                    features = scaler.transform(window)
                except ValueError:
                    features = window  # shape mismatch — use raw
            else:
                features = window

            prediction = model.predict(features)[0]
            probabilities = model.predict_proba(features)[0]

            classes = model.classes_
            class_idx = np.where(classes == prediction)[0][0]
            confidence = probabilities[class_idx]

            signal_map = {1: 'BUY', -1: 'SELL', 0: 'HOLD'}

            result = {
                'signal': signal_map.get(int(prediction), 'HOLD'),
                'confidence': float(confidence),
                'prediction': int(prediction),
                'probabilities': {
                    signal_map.get(int(cls), f'class_{cls}'): float(prob)
                    for cls, prob in zip(classes, probabilities)
                },
                'model_accuracy': metrics.get('accuracy', 0.0) if metrics else 0.0,
                'pretrained_from_history': metrics.get('pretrained_from_history', False) if metrics else False,
                'fine_tuned_trades': metrics.get('fine_tuned_trades', 0) if metrics else 0,
                'timestamp': datetime.now().isoformat()
            }

            return result

        except Exception as e:
            logger.error(f"Prediction failed for {symbol}: {e}", exc_info=True)
            return None

    def get_model_info(self, symbol: str) -> Optional[Dict]:
        """Получить информацию о модели символа"""
        metrics_path = self._get_metrics_path(symbol)

        if not metrics_path.exists():
            return None

        try:
            with open(metrics_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read model info: {e}")
            return None

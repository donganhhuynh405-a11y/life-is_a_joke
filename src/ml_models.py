"""
Advanced ML module: LSTM + Transformer for price prediction.
Production implementation with proper training, persistence, and learning.
"""
import numpy as np
from typing import Tuple, Dict, Optional
import logging
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger('bot.ml')


class PricePredictorLSTM:
    """LSTM-based price predictor trained on OHLCV + on-chain metrics"""

    def __init__(self, lookback=50, features=10, model_dir='models'):
        self.lookback = lookback
        self.features = features
        self.model = None
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.scaler_x = None
        self.scaler_y = None
        self.history = []
        self.is_trained = False

    def build_model(self):
        """Build LSTM model using TensorFlow/Keras"""
        try:
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
            from tensorflow.keras.regularizers import l2
            from tensorflow.keras.optimizers import Adam

            self.model = Sequential([
                LSTM(128, return_sequences=True, input_shape=(self.lookback, self.features),
                     kernel_regularizer=l2(0.001)),
                Dropout(0.3),
                BatchNormalization(),
                LSTM(64, return_sequences=True, kernel_regularizer=l2(0.001)),
                Dropout(0.3),
                BatchNormalization(),
                LSTM(32, kernel_regularizer=l2(0.001)),
                Dropout(0.2),
                Dense(16, activation='relu'),
                Dropout(0.1),
                Dense(1, activation='sigmoid')
            ])

            optimizer = Adam(learning_rate=0.001)
            self.model.compile(
                optimizer=optimizer,
                loss='binary_crossentropy',
                metrics=['accuracy', 'AUC']
            )
            logger.info('LSTM model built successfully')
            return True
        except ImportError as e:
            logger.error(f'TensorFlow not available: {e}')
            return False
        except Exception as e:
            logger.error(f'Error building LSTM model: {e}')
            return False

    def _prepare_sequences(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare sequences for LSTM training"""
        try:
            if len(X.shape) == 2:
                # Reshape to (samples, timesteps, features)
                n_samples = len(X) - self.lookback + 1
                X_seq = np.zeros((n_samples, self.lookback, X.shape[1]))
                y_seq = np.zeros((n_samples,))

                for i in range(n_samples):
                    X_seq[i] = X[i:i + self.lookback]
                    y_seq[i] = y[i + self.lookback - 1] if i + self.lookback - 1 < len(y) else y[-1]

                return X_seq, y_seq
            return X, y
        except Exception as e:
            logger.error(f'Error preparing sequences: {e}')
            raise

    def _scale_data(self, X: np.ndarray, y: np.ndarray,
                    fit: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """Scale features and target using StandardScaler"""
        try:
            from sklearn.preprocessing import StandardScaler

            if fit:
                self.scaler_x = StandardScaler()
                self.scaler_y = StandardScaler()

            original_shape = X.shape
            if len(X.shape) == 3:
                # Reshape for scaling
                X_reshaped = X.reshape(-1, X.shape[-1])
                if fit:
                    X_scaled = self.scaler_x.fit_transform(X_reshaped)
                else:
                    X_scaled = self.scaler_x.transform(X_reshaped)
                X_scaled = X_scaled.reshape(original_shape)
            else:
                if fit:
                    X_scaled = self.scaler_x.fit_transform(X)
                else:
                    X_scaled = self.scaler_x.transform(X)

            y_reshaped = y.reshape(-1, 1)
            if fit:
                y_scaled = self.scaler_y.fit_transform(y_reshaped).flatten()
            else:
                y_scaled = self.scaler_y.transform(y_reshaped).flatten()

            return X_scaled, y_scaled
        except Exception as e:
            logger.error(f'Error scaling data: {e}')
            raise

    def train(self, X: np.ndarray, y: np.ndarray, epochs=50, validation_split=0.2,
              batch_size=32, early_stopping_patience=10) -> Dict:
        """
        Train LSTM on historical OHLCV data

        Args:
            X: Input features (samples, features) or (samples, timesteps, features)
            y: Target values (0 or 1 for binary classification)
            epochs: Number of training epochs
            validation_split: Fraction of data for validation
            batch_size: Training batch size
            early_stopping_patience: Epochs to wait before early stopping

        Returns:
            Dictionary with training metrics
        """
        try:
            if self.model is None:
                if not self.build_model():
                    raise RuntimeError("Failed to build model")

            # Validate inputs
            if len(X) == 0 or len(y) == 0:
                raise ValueError("Empty training data")

            if len(X) != len(y):
                logger.warning(f"X and y length mismatch: {len(X)} vs {len(y)}")

            # Prepare sequences
            X_seq, y_seq = self._prepare_sequences(X, y)
            logger.info(f'Prepared sequences: X_seq={X_seq.shape}, y_seq={y_seq.shape}')

            # Scale data
            X_scaled, y_scaled = self._scale_data(X_seq, y_seq, fit=True)

            # Setup callbacks
            from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint

            checkpoint_path = self.model_dir / 'lstm_checkpoint.h5'
            callbacks = [
                EarlyStopping(
                    monitor='val_loss',
                    patience=early_stopping_patience,
                    restore_best_weights=True,
                    verbose=1
                ),
                ReduceLROnPlateau(
                    monitor='val_loss',
                    factor=0.5,
                    patience=5,
                    min_lr=1e-7,
                    verbose=1
                ),
                ModelCheckpoint(
                    str(checkpoint_path),
                    monitor='val_loss',
                    save_best_only=True,
                    verbose=1
                )
            ]

            # Train model
            logger.info(f'Training LSTM on {len(X_scaled)} samples for {epochs} epochs')
            history = self.model.fit(
                X_scaled, y_scaled,
                epochs=epochs,
                batch_size=batch_size,
                validation_split=validation_split,
                callbacks=callbacks,
                verbose=1
            )

            self.history.append({
                'timestamp': datetime.now().isoformat(),
                'epochs_trained': len(history.history['loss']),
                'final_loss': float(history.history['loss'][-1]),
                'final_val_loss': float(history.history['val_loss'][-1]),
                'final_accuracy': float(history.history['accuracy'][-1]),
                'final_val_accuracy': float(history.history['val_accuracy'][-1])
            })

            self.is_trained = True

            # Return training metrics
            metrics = {
                'loss': float(history.history['loss'][-1]),
                'val_loss': float(history.history['val_loss'][-1]),
                'accuracy': float(history.history['accuracy'][-1]),
                'val_accuracy': float(history.history['val_accuracy'][-1]),
                'epochs_completed': len(history.history['loss']),
                'samples_trained': len(X_scaled)
            }

            logger.info(f'Training completed: {metrics}')
            return metrics

        except Exception as e:
            logger.error(f'Training failed: {e}', exc_info=True)
            raise

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict next price movement: >0.5 = UP, <0.5 = DOWN

        Args:
            X: Input features

        Returns:
            Prediction probabilities
        """
        try:
            if self.model is None:
                raise RuntimeError("Model not built. Call build_model() or train() first.")

            if not self.is_trained:
                logger.warning("Model not trained yet. Predictions may be unreliable.")

            # Prepare sequences
            if len(X.shape) == 2:
                X_seq, _ = self._prepare_sequences(X, np.zeros(len(X)))
            else:
                X_seq = X

            # Scale data
            if self.scaler_x is not None:
                original_shape = X_seq.shape
                X_reshaped = X_seq.reshape(-1, X_seq.shape[-1])
                X_scaled = self.scaler_x.transform(X_reshaped)
                X_scaled = X_scaled.reshape(original_shape)
            else:
                X_scaled = X_seq
                logger.warning("Scaler not fitted. Using unscaled data.")

            # Predict
            predictions = self.model.predict(X_scaled, verbose=0)
            return predictions

        except Exception as e:
            logger.error(f'Prediction failed: {e}', exc_info=True)
            raise

    def save_model(self, name: str = 'lstm_model') -> bool:
        """Save model, scalers, and metadata to disk"""
        try:
            if self.model is None:
                logger.error("No model to save")
                return False

            import joblib

            # Save Keras model
            model_path = self.model_dir / f'{name}.h5'
            self.model.save(str(model_path))
            logger.info(f'Model saved to {model_path}')

            # Save scalers
            if self.scaler_x is not None:
                scaler_x_path = self.model_dir / f'{name}_scaler_x.pkl'
                joblib.dump(self.scaler_x, scaler_x_path)

            if self.scaler_y is not None:
                scaler_y_path = self.model_dir / f'{name}_scaler_y.pkl'
                joblib.dump(self.scaler_y, scaler_y_path)

            # Save metadata
            metadata = {
                'lookback': self.lookback,
                'features': self.features,
                'is_trained': self.is_trained,
                'training_history': self.history,
                'saved_at': datetime.now().isoformat()
            }
            metadata_path = self.model_dir / f'{name}_metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info('Model components saved successfully')
            return True

        except Exception as e:
            logger.error(f'Failed to save model: {e}', exc_info=True)
            return False

    def load_model(self, name: str = 'lstm_model') -> bool:
        """Load model, scalers, and metadata from disk"""
        try:
            from tensorflow.keras.models import load_model
            import joblib

            # Load Keras model
            model_path = self.model_dir / f'{name}.h5'
            if not model_path.exists():
                logger.error(f'Model not found: {model_path}')
                return False

            self.model = load_model(str(model_path))
            logger.info(f'Model loaded from {model_path}')

            # Load scalers
            scaler_x_path = self.model_dir / f'{name}_scaler_x.pkl'
            if scaler_x_path.exists():
                self.scaler_x = joblib.load(scaler_x_path)

            scaler_y_path = self.model_dir / f'{name}_scaler_y.pkl'
            if scaler_y_path.exists():
                self.scaler_y = joblib.load(scaler_y_path)

            # Load metadata
            metadata_path = self.model_dir / f'{name}_metadata.json'
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    self.lookback = metadata.get('lookback', self.lookback)
                    self.features = metadata.get('features', self.features)
                    self.is_trained = metadata.get('is_trained', False)
                    self.history = metadata.get('training_history', [])

            logger.info('Model components loaded successfully')
            return True

        except Exception as e:
            logger.error(f'Failed to load model: {e}', exc_info=True)
            return False

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """Evaluate model performance on test data"""
        try:
            if self.model is None:
                raise RuntimeError("Model not built")

            # Prepare sequences
            X_seq, y_seq = self._prepare_sequences(X, y)

            # Scale data
            if self.scaler_x is not None:
                X_scaled, y_scaled = self._scale_data(X_seq, y_seq, fit=False)
            else:
                X_scaled, y_scaled = X_seq, y_seq

            # Evaluate
            results = self.model.evaluate(X_scaled, y_scaled, verbose=0)

            metrics = {
                'loss': float(results[0]),
                'accuracy': float(results[1]),
                'auc': float(results[2]) if len(results) > 2 else None
            }

            logger.info(f'Evaluation metrics: {metrics}')
            return metrics

        except Exception as e:
            logger.error(f'Evaluation failed: {e}', exc_info=True)
            raise


class TransformerPredictor:
    """Transformer model for sequence prediction with real attention mechanisms"""

    def __init__(self, max_len=100, d_model=64, heads=4, num_layers=2, model_dir='models'):
        self.max_len = max_len
        self.d_model = d_model
        self.heads = heads
        self.num_layers = num_layers
        self.model = None
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.scaler = None
        self.history = []
        self.is_trained = False

    def build_model(self):
        """Build Transformer encoder with multi-head attention"""
        try:
            from tensorflow.keras.models import Model
            from tensorflow.keras.layers import (
                Input, Dense, Dropout, LayerNormalization,
                MultiHeadAttention, GlobalAveragePooling1D
            )

            # Input layer
            inputs = Input(shape=(self.max_len, self.d_model))
            x = inputs

            # Transformer encoder layers
            for i in range(self.num_layers):
                # Multi-head attention
                attention_output = MultiHeadAttention(
                    num_heads=self.heads,
                    key_dim=self.d_model // self.heads,
                    dropout=0.1,
                    name=f'attention_{i}'
                )(x, x)

                # Skip connection and layer normalization
                x = LayerNormalization(epsilon=1e-6)(x + attention_output)

                # Feed-forward network
                ffn = Dense(self.d_model * 4, activation='relu')(x)
                ffn = Dropout(0.1)(ffn)
                ffn = Dense(self.d_model)(ffn)

                # Skip connection and layer normalization
                x = LayerNormalization(epsilon=1e-6)(x + ffn)

            # Global pooling and output
            x = GlobalAveragePooling1D()(x)
            x = Dropout(0.2)(x)
            x = Dense(32, activation='relu')(x)
            x = Dropout(0.1)(x)
            outputs = Dense(3, activation='softmax')(x)  # BUY, SELL, HOLD

            self.model = Model(inputs=inputs, outputs=outputs)

            from tensorflow.keras.optimizers import Adam
            self.model.compile(
                optimizer=Adam(learning_rate=0.001),
                loss='categorical_crossentropy',
                metrics=['accuracy']
            )

            logger.info(f'Transformer model built with {self.num_layers} layers, {self.heads} heads')
            return True

        except ImportError as e:
            logger.error(f'TensorFlow not available: {e}')
            return False
        except Exception as e:
            logger.error(f'Error building Transformer model: {e}', exc_info=True)
            return False

    def _prepare_features(self, features: np.ndarray) -> np.ndarray:
        """Prepare and pad features to max_len"""
        try:
            if len(features.shape) == 2:
                # (samples, features) -> (samples, max_len, d_model)
                features.shape[0]

                # Pad or truncate sequence length
                if features.shape[0] < self.max_len:
                    pad_len = self.max_len - features.shape[0]
                    features = np.pad(features, ((0, pad_len), (0, 0)), mode='edge')
                elif features.shape[0] > self.max_len:
                    features = features[-self.max_len:]

                # Adjust feature dimension
                if features.shape[1] < self.d_model:
                    pad_feat = self.d_model - features.shape[1]
                    features = np.pad(features, ((0, 0), (0, pad_feat)), mode='constant')
                elif features.shape[1] > self.d_model:
                    features = features[:, :self.d_model]

                # Add batch dimension
                features = features.reshape(1, self.max_len, self.d_model)

            return features

        except Exception as e:
            logger.error(f'Error preparing features: {e}')
            raise

    def train(self, X: np.ndarray, y: np.ndarray, epochs=50, validation_split=0.2,
              batch_size=32, early_stopping_patience=10) -> Dict:
        """
        Train transformer on historical data

        Args:
            X: Input sequences (samples, sequence_length, features)
            y: Target labels (samples,) or one-hot encoded (samples, 3)
            epochs: Number of training epochs
            validation_split: Fraction for validation
            batch_size: Training batch size
            early_stopping_patience: Patience for early stopping

        Returns:
            Training metrics
        """
        try:
            if self.model is None:
                if not self.build_model():
                    raise RuntimeError("Failed to build model")

            from sklearn.preprocessing import StandardScaler
            from tensorflow.keras.utils import to_categorical
            from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint

            # Prepare data
            if len(X.shape) == 2:
                # Reshape to 3D
                X = X.reshape(1, -1, X.shape[-1])

            # Ensure proper dimensions
            if X.shape[1] != self.max_len:
                # Adjust sequence length
                if X.shape[1] < self.max_len:
                    pad_len = self.max_len - X.shape[1]
                    X = np.pad(X, ((0, 0), (0, pad_len), (0, 0)), mode='edge')
                else:
                    X = X[:, -self.max_len:, :]

            if X.shape[2] != self.d_model:
                # Adjust feature dimension
                if X.shape[2] < self.d_model:
                    pad_feat = self.d_model - X.shape[2]
                    X = np.pad(X, ((0, 0), (0, 0), (0, pad_feat)), mode='constant')
                else:
                    X = X[:, :, :self.d_model]

            # Scale features
            self.scaler = StandardScaler()
            original_shape = X.shape
            X_scaled = self.scaler.fit_transform(X.reshape(-1, X.shape[-1]))
            X_scaled = X_scaled.reshape(original_shape)

            # Prepare labels
            if len(y.shape) == 1:
                # Convert to one-hot
                y = to_categorical(y, num_classes=3)

            # Setup callbacks
            checkpoint_path = self.model_dir / 'transformer_checkpoint.h5'
            callbacks = [
                EarlyStopping(
                    monitor='val_loss',
                    patience=early_stopping_patience,
                    restore_best_weights=True,
                    verbose=1
                ),
                ReduceLROnPlateau(
                    monitor='val_loss',
                    factor=0.5,
                    patience=5,
                    min_lr=1e-7,
                    verbose=1
                ),
                ModelCheckpoint(
                    str(checkpoint_path),
                    monitor='val_loss',
                    save_best_only=True,
                    verbose=1
                )
            ]

            # Train
            logger.info(f'Training Transformer on {len(X_scaled)} samples')
            history = self.model.fit(
                X_scaled, y,
                epochs=epochs,
                batch_size=batch_size,
                validation_split=validation_split,
                callbacks=callbacks,
                verbose=1
            )

            self.history.append({
                'timestamp': datetime.now().isoformat(),
                'epochs_trained': len(history.history['loss']),
                'final_loss': float(history.history['loss'][-1]),
                'final_val_loss': float(history.history['val_loss'][-1]),
                'final_accuracy': float(history.history['accuracy'][-1])
            })

            self.is_trained = True

            metrics = {
                'loss': float(history.history['loss'][-1]),
                'val_loss': float(history.history['val_loss'][-1]),
                'accuracy': float(history.history['accuracy'][-1]),
                'val_accuracy': float(history.history['val_accuracy'][-1]),
                'epochs_completed': len(history.history['loss'])
            }

            logger.info(f'Training completed: {metrics}')
            return metrics

        except Exception as e:
            logger.error(f'Training failed: {e}', exc_info=True)
            raise

    def predict(self, features: np.ndarray) -> Dict:
        """
        Predict signal with confidence using real attention mechanisms

        Args:
            features: Input features

        Returns:
            Dictionary with signal, confidence, and predictions
        """
        try:
            if self.model is None:
                raise RuntimeError("Model not built. Call build_model() or train() first.")

            if not self.is_trained:
                logger.warning("Model not trained. Predictions may be unreliable.")

            # Prepare features
            X = self._prepare_features(features)

            # Scale if scaler is available
            if self.scaler is not None:
                original_shape = X.shape
                X_scaled = self.scaler.transform(X.reshape(-1, X.shape[-1]))
                X = X_scaled.reshape(original_shape)

            # Predict
            predictions = self.model.predict(X, verbose=0)[0]

            # predictions: [prob_buy, prob_sell, prob_hold]
            signal_map = ['BUY', 'SELL', 'HOLD']
            signal_idx = np.argmax(predictions)
            signal = signal_map[signal_idx]
            confidence = float(predictions[signal_idx])

            # Calculate expected price change
            prob_up = float(predictions[0])
            prob_down = float(predictions[1])
            next_price_change = (prob_up - prob_down)  # -1 to +1

            return {
                'signal': signal,
                'confidence': confidence,
                'next_price_change': next_price_change,
                'probabilities': {
                    'buy': float(predictions[0]),
                    'sell': float(predictions[1]),
                    'hold': float(predictions[2])
                }
            }

        except Exception as e:
            logger.error(f'Prediction failed: {e}', exc_info=True)
            raise

    def save_model(self, name: str = 'transformer_model') -> bool:
        """Save model, scaler, and metadata"""
        try:
            if self.model is None:
                logger.error("No model to save")
                return False

            import joblib

            # Save model
            model_path = self.model_dir / f'{name}.h5'
            self.model.save(str(model_path))
            logger.info(f'Model saved to {model_path}')

            # Save scaler
            if self.scaler is not None:
                scaler_path = self.model_dir / f'{name}_scaler.pkl'
                joblib.dump(self.scaler, scaler_path)

            # Save metadata
            metadata = {
                'max_len': self.max_len,
                'd_model': self.d_model,
                'heads': self.heads,
                'num_layers': self.num_layers,
                'is_trained': self.is_trained,
                'training_history': self.history,
                'saved_at': datetime.now().isoformat()
            }
            metadata_path = self.model_dir / f'{name}_metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info('Model components saved successfully')
            return True

        except Exception as e:
            logger.error(f'Failed to save model: {e}', exc_info=True)
            return False

    def load_model(self, name: str = 'transformer_model') -> bool:
        """Load model, scaler, and metadata"""
        try:
            from tensorflow.keras.models import load_model
            import joblib

            # Load model
            model_path = self.model_dir / f'{name}.h5'
            if not model_path.exists():
                logger.error(f'Model not found: {model_path}')
                return False

            self.model = load_model(str(model_path))
            logger.info(f'Model loaded from {model_path}')

            # Load scaler
            scaler_path = self.model_dir / f'{name}_scaler.pkl'
            if scaler_path.exists():
                self.scaler = joblib.load(scaler_path)

            # Load metadata
            metadata_path = self.model_dir / f'{name}_metadata.json'
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    self.max_len = metadata.get('max_len', self.max_len)
                    self.d_model = metadata.get('d_model', self.d_model)
                    self.heads = metadata.get('heads', self.heads)
                    self.num_layers = metadata.get('num_layers', self.num_layers)
                    self.is_trained = metadata.get('is_trained', False)
                    self.history = metadata.get('training_history', [])

            logger.info('Model components loaded successfully')
            return True

        except Exception as e:
            logger.error(f'Failed to load model: {e}', exc_info=True)
            return False


class HybridPredictor:
    """Ensemble of LSTM and Transformer with weighted predictions"""

    def __init__(self, model_dir='models', lstm_weight=0.5, transformer_weight=0.5):
        self.lstm = PricePredictorLSTM(model_dir=model_dir)
        self.transformer = TransformerPredictor(model_dir=model_dir)
        self.lstm_weight = lstm_weight
        self.transformer_weight = transformer_weight
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # Normalize weights
        total_weight = lstm_weight + transformer_weight
        self.lstm_weight = lstm_weight / total_weight
        self.transformer_weight = transformer_weight / total_weight

    def train(self, X: np.ndarray, y: np.ndarray, epochs=50,
              validation_split=0.2, batch_size=32) -> Dict:
        """
        Train both LSTM and Transformer models

        Args:
            X: Input features
            y: Target labels
            epochs: Training epochs
            validation_split: Validation data fraction
            batch_size: Batch size

        Returns:
            Combined training metrics
        """
        try:
            logger.info('Training hybrid ensemble models...')

            # Train LSTM
            logger.info('Training LSTM component...')
            lstm_metrics = self.lstm.train(
                X, y,
                epochs=epochs,
                validation_split=validation_split,
                batch_size=batch_size
            )

            # Train Transformer
            logger.info('Training Transformer component...')
            transformer_metrics = self.transformer.train(
                X, y,
                epochs=epochs,
                validation_split=validation_split,
                batch_size=batch_size
            )

            metrics = {
                'lstm': lstm_metrics,
                'transformer': transformer_metrics,
                'ensemble': {
                    'avg_loss': (lstm_metrics['loss'] + transformer_metrics['loss']) / 2,
                    'avg_accuracy': (lstm_metrics.get('accuracy', 0) +
                                     transformer_metrics.get('accuracy', 0)) / 2
                }
            }

            logger.info('Hybrid training completed successfully')
            return metrics

        except Exception as e:
            logger.error(f'Hybrid training failed: {e}', exc_info=True)
            raise

    def predict_ensemble(self, features: np.ndarray) -> Dict:
        """
        Combine LSTM and Transformer predictions with weighted averaging

        Args:
            features: Input features

        Returns:
            Ensemble prediction with confidence and component predictions
        """
        try:
            # Get LSTM prediction
            lstm_pred = self.lstm.predict(features)
            lstm_confidence = float(lstm_pred[0, 0]) if len(lstm_pred) > 0 else 0.5

            # Get Transformer prediction
            trans_pred = self.transformer.predict(features)
            trans_confidence = trans_pred['confidence']
            trans_signal = trans_pred['signal']

            # Weighted ensemble (used implicitly through signal_scores below)

            # Determine final signal based on both models
            signal_scores = {'BUY': 0, 'SELL': 0, 'HOLD': 0}

            # LSTM contribution (binary: up or down)
            if lstm_confidence > 0.5:
                signal_scores['BUY'] += self.lstm_weight * lstm_confidence
            else:
                signal_scores['SELL'] += self.lstm_weight * (1 - lstm_confidence)

            # Transformer contribution
            if trans_signal == 'BUY':
                signal_scores['BUY'] += self.transformer_weight * trans_confidence
            elif trans_signal == 'SELL':
                signal_scores['SELL'] += self.transformer_weight * trans_confidence
            else:
                signal_scores['HOLD'] += self.transformer_weight * trans_confidence

            # Select signal with highest score
            final_signal = max(signal_scores, key=signal_scores.get)
            final_confidence = signal_scores[final_signal]

            return {
                'signal': final_signal,
                'confidence': min(0.99, final_confidence),  # Cap at 0.99
                'lstm_pred': lstm_confidence,
                'transformer_pred': trans_confidence,
                'transformer_signal': trans_signal,
                'next_price_change': trans_pred['next_price_change'],
                'component_scores': signal_scores,
                'weights': {
                    'lstm': self.lstm_weight,
                    'transformer': self.transformer_weight
                }
            }

        except Exception as e:
            logger.error(f'Ensemble prediction failed: {e}', exc_info=True)
            raise

    def save_models(self, prefix: str = 'hybrid') -> bool:
        """Save both LSTM and Transformer models"""
        try:
            lstm_saved = self.lstm.save_model(f'{prefix}_lstm')
            transformer_saved = self.transformer.save_model(f'{prefix}_transformer')

            # Save ensemble metadata
            metadata = {
                'lstm_weight': self.lstm_weight,
                'transformer_weight': self.transformer_weight,
                'saved_at': datetime.now().isoformat()
            }
            metadata_path = self.model_dir / f'{prefix}_ensemble_metadata.json'
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            success = lstm_saved and transformer_saved
            if success:
                logger.info('All ensemble models saved successfully')
            else:
                logger.warning('Some models failed to save')

            return success

        except Exception as e:
            logger.error(f'Failed to save ensemble: {e}', exc_info=True)
            return False

    def load_models(self, prefix: str = 'hybrid') -> bool:
        """Load both LSTM and Transformer models"""
        try:
            lstm_loaded = self.lstm.load_model(f'{prefix}_lstm')
            transformer_loaded = self.transformer.load_model(f'{prefix}_transformer')

            # Load ensemble metadata
            metadata_path = self.model_dir / f'{prefix}_ensemble_metadata.json'
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    self.lstm_weight = metadata.get('lstm_weight', 0.5)
                    self.transformer_weight = metadata.get('transformer_weight', 0.5)

            success = lstm_loaded and transformer_loaded
            if success:
                logger.info('All ensemble models loaded successfully')
            else:
                logger.warning('Some models failed to load')

            return success

        except Exception as e:
            logger.error(f'Failed to load ensemble: {e}', exc_info=True)
            return False

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """Evaluate both models on test data"""
        try:
            lstm_metrics = self.lstm.evaluate(X, y)

            # For transformer, we need to prepare the data differently
            # Since it expects categorical targets
            from tensorflow.keras.utils import to_categorical
            if len(y.shape) == 1:
                to_categorical(y, num_classes=3)
            else:
                pass

            # Prepare X for transformer
            if len(X.shape) == 2:
                X.reshape(1, -1, X.shape[-1])
            else:
                pass

            # Note: Direct evaluation may not work perfectly due to data shape requirements
            # This is a simplified version

            return {
                'lstm': lstm_metrics,
                'transformer': 'Requires categorical data evaluation',
                'ensemble_trained': self.lstm.is_trained and self.transformer.is_trained
            }

        except Exception as e:
            logger.error(f'Evaluation failed: {e}', exc_info=True)
            return {'error': str(e)}


def train_on_historical_data(csv_file: str, epochs=50, validation_split=0.2,
                             save_models=True, model_prefix='production') -> HybridPredictor:
    """
    Load historical OHLCV data and train ensemble

    Args:
        csv_file: Path to CSV file with OHLCV data
        epochs: Number of training epochs
        validation_split: Validation data fraction
        save_models: Whether to save trained models
        model_prefix: Prefix for saved model files

    Returns:
        Trained HybridPredictor
    """
    try:
        import pandas as pd

        logger.info(f'Loading historical data from {csv_file}')
        df = pd.read_csv(csv_file)

        if len(df) < 100:
            raise ValueError(f"Insufficient data: {len(df)} rows (minimum 100 required)")

        # Prepare features from OHLCV
        feature_cols = ['open', 'high', 'low', 'close', 'volume']

        # Check if all required columns exist
        missing_cols = [col for col in feature_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing columns: {missing_cols}")

        X = df[feature_cols].values

        # Create target: 1 if next close > current close, else 0
        df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
        y = df['target'].values[:-1]  # Remove last row (no next price)
        X = X[:-1]  # Match X length

        # Add technical indicators as features
        try:
            # Simple moving averages
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['sma_50'] = df['close'].rolling(window=50).mean()

            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-10)
            df['rsi'] = 100 - (100 / (1 + rs))

            # MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2

            # Volume ratio
            df['volume_ratio'] = df['volume'] / df['volume'].rolling(window=20).mean()

            # Add these features to X
            additional_features = ['sma_20', 'sma_50', 'rsi', 'macd', 'volume_ratio']
            df_features = df[feature_cols +
                             additional_features].fillna(method='bfill').fillna(method='ffill')
            X = df_features.values[:-1]

            logger.info(f'Added technical indicators: {additional_features}')

        except Exception as e:
            logger.warning(f'Failed to add technical indicators: {e}. Using basic OHLCV only.')

        # Remove any remaining NaN values
        valid_idx = ~(np.isnan(X).any(axis=1) | np.isnan(y))
        X = X[valid_idx]
        y = y[valid_idx]

        logger.info(f'Training data: X={X.shape}, y={y.shape}')
        logger.info(f'Target distribution: UP={np.sum(y)}, DOWN={len(y) - np.sum(y)}')

        # Create and train predictor
        predictor = HybridPredictor()

        try:
            metrics = predictor.train(
                X, y,
                epochs=epochs,
                validation_split=validation_split
            )

            logger.info(f'Model trained successfully: {metrics}')

            # Save models if requested
            if save_models:
                predictor.save_models(prefix=model_prefix)
                logger.info(f'Models saved with prefix: {model_prefix}')

            return predictor

        except Exception as train_error:
            logger.error(f'Training failed: {train_error}', exc_info=True)
            raise

    except FileNotFoundError:
        logger.error(f'CSV file not found: {csv_file}')
        raise
    except Exception as e:
        logger.error(f'Failed to train on historical data: {e}', exc_info=True)
        raise


def load_trained_models(model_prefix='production', model_dir='models') -> Optional[HybridPredictor]:
    """
    Load pre-trained models from disk

    Args:
        model_prefix: Prefix of saved model files
        model_dir: Directory containing models

    Returns:
        Loaded HybridPredictor or None if loading fails
    """
    try:
        predictor = HybridPredictor(model_dir=model_dir)

        if predictor.load_models(prefix=model_prefix):
            logger.info(f'Successfully loaded models with prefix: {model_prefix}')
            return predictor
        else:
            logger.error('Failed to load models')
            return None

    except Exception as e:
        logger.error(f'Error loading models: {e}', exc_info=True)
        return None

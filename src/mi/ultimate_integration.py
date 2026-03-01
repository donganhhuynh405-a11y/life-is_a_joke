"""
Ultimate ML Trading System Integration
Brings together all advanced ML components into a cohesive trading system
"""
import torch
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
import logging
from pathlib import Path

from .advanced_architectures import (
    create_ultimate_model
)
from .crypto_features import (
    AdvancedFeatureEngineer,
    OnChainMetrics,
    CrossExchangeData,
    engineer_target_variables
)
from .ultimate_training import (
    UltimateTrainer,
    HyperparameterOptimizer,
    ContinualLearner
)

logger = logging.getLogger(__name__)


class UltimateTradingAI:
    """
    Ultimate AI system for crypto trading
    Combines all state-of-the-art ML techniques
    """

    def __init__(
        self,
        config: Dict,
        device: Optional[torch.device] = None,
        model_dir: str = 'models/ultimate'
    ):
        self.config = config
        self.device = device or torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initializing Ultimate Trading AI on {self.device}")

        # Feature engineering
        self.feature_engineer = AdvancedFeatureEngineer(config)

        # Models (initialized when needed)
        self.main_model = None
        self.ensemble_models = []
        self.continual_learner = None

        # Trading state
        self.last_predictions = {}
        self.prediction_confidence = {}
        self.feature_importance = {}

        # Performance tracking
        self.prediction_accuracy = []
        self.sharpe_ratio_history = []

    def initialize_models(
        self,
        input_size: int,
        num_assets: int,
        use_pretrained: bool = True
    ):
        """Initialize or load models"""
        logger.info("Initializing models...")

        # Create ultimate ensemble model
        self.main_model = create_ultimate_model(
            input_size=input_size,
            num_assets=num_assets,
            device=self.device
        )

        # Load pretrained weights if available
        if use_pretrained:
            model_path = self.model_dir / 'best_model.pt'
            if model_path.exists():
                checkpoint = torch.load(model_path, map_location=self.device)
                self.main_model.load_state_dict(checkpoint['model_state_dict'])
                logger.info("Loaded pretrained model")
            else:
                logger.warning("No pretrained model found, using random initialization")

        # Initialize continual learner
        self.continual_learner = ContinualLearner(
            model=self.main_model,
            device=self.device,
            memory_size=1000
        )

        logger.info(
            f"Models initialized with {sum(p.numel() for p in self.main_model.parameters()):,} parameters")

    async def train_from_historical_data(
        self,
        data: pd.DataFrame,
        symbols: List[str],
        epochs: int = 100,
        optimize_hyperparams: bool = False
    ) -> Dict:
        """
        Train models on historical data

        Args:
            data: Historical OHLCV data for all symbols
            symbols: List of trading symbols
            epochs: Number of training epochs
            optimize_hyperparams: Whether to run hyperparameter optimization

        Returns:
            Training metrics and history
        """
        logger.info("Starting training from historical data...")

        # Extract features
        logger.info("Extracting advanced features...")
        features = self.feature_engineer.extract_all_features(
            ohlcv=data,
            onchain=None,  # Would integrate real on-chain API
            orderbook=None,  # Would integrate real orderbook data
            cross_exchange=None  # Would integrate cross-exchange data
        )

        # Create targets
        targets = engineer_target_variables(data, horizons=[1, 5, 10])

        # Prepare data
        X = features.values
        y = targets.values

        # Remove NaN rows
        valid_idx = ~(np.isnan(X).any(axis=1) | np.isnan(y).any(axis=1))
        X = X[valid_idx]
        y = y[valid_idx]

        logger.info(f"Training data shape: X={X.shape}, y={y.shape}")

        # Split into train/val
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        # Hyperparameter optimization (if requested)
        if optimize_hyperparams:
            logger.info("Running hyperparameter optimization...")

            def model_factory(**params):
                return create_ultimate_model(
                    input_size=X.shape[1],
                    num_assets=len(symbols),
                    device=self.device
                )

            optimizer = HyperparameterOptimizer(
                model_factory=model_factory,
                train_data=(X_train, y_train),
                val_data=(X_val, y_val),
                device=self.device,
                n_trials=20  # Reduced for practical runtime
            )

            best_params = optimizer.optimize()
            logger.info(f"Best hyperparameters found: {best_params}")

        # Initialize models if not already done
        if self.main_model is None:
            self.initialize_models(
                input_size=X.shape[1],
                num_assets=len(symbols),
                use_pretrained=False
            )

        # Train main model
        from torch.utils.data import DataLoader, TensorDataset

        train_dataset = TensorDataset(
            torch.FloatTensor(X_train),
            torch.FloatTensor(y_train)
        )
        val_dataset = TensorDataset(
            torch.FloatTensor(X_val),
            torch.FloatTensor(y_val)
        )

        train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=64)

        trainer = UltimateTrainer(
            model=self.main_model,
            device=self.device,
            save_dir=str(self.model_dir)
        )

        history = trainer.train(
            train_loader=train_loader,
            val_loader=val_loader,
            num_epochs=epochs,
            learning_rate=0.001,
            patience=15
        )

        # Compute Fisher Information for continual learning
        self.continual_learner.compute_fisher_information(
            val_loader,
            torch.nn.MSELoss()
        )

        logger.info("Training completed!")

        return {
            'history': history,
            'final_train_loss': history['train_loss'][-1],
            'final_val_loss': history['val_loss'][-1],
            'best_val_loss': min(history['val_loss']),
            'num_epochs': len(history['train_loss'])
        }

    async def predict(
        self,
        current_data: pd.DataFrame,
        symbol: str,
        onchain: Optional[OnChainMetrics] = None,
        orderbook: Optional[Dict] = None,
        cross_exchange: Optional[CrossExchangeData] = None
    ) -> Dict:
        """
        Make prediction for a symbol

        Returns:
            Dict with predictions, confidence, and interpretability
        """
        if self.main_model is None:
            raise RuntimeError(
                "Model not initialized. Call initialize_models() or train_from_historical_data() first")

        # Extract features
        features = self.feature_engineer.extract_all_features(
            ohlcv=current_data,
            onchain=onchain,
            orderbook=orderbook,
            cross_exchange=cross_exchange
        )

        # Get last sequence
        sequence_length = 50
        if len(features) < sequence_length:
            logger.warning(f"Insufficient data for {symbol}, padding...")
            # Pad with zeros if needed
            padding = pd.DataFrame(
                np.zeros((sequence_length - len(features), len(features.columns))),
                columns=features.columns
            )
            features = pd.concat([padding, features], ignore_index=True)

        # Take last sequence
        X = features.iloc[-sequence_length:].values
        X_tensor = torch.FloatTensor(X).unsqueeze(0).to(self.device)

        # Predict
        self.main_model.eval()
        with torch.no_grad():
            outputs = self.main_model(X_tensor)

        # Parse outputs
        result = {}

        if isinstance(outputs, dict):
            # Multi-task outputs
            if 'price_direction' in outputs:
                direction_probs = torch.softmax(outputs['price_direction'], dim=-1)
                direction_idx = direction_probs.argmax(dim=-1).item()
                direction_conf = direction_probs.max().item()

                directions = ['DOWN', 'SIDEWAYS', 'UP']
                result['direction'] = directions[direction_idx]
                result['direction_confidence'] = direction_conf
                result['direction_probs'] = {
                    d: float(p) for d, p in zip(directions, direction_probs[0].cpu().numpy())
                }

            if 'volatility' in outputs:
                result['predicted_volatility'] = float(outputs['volatility'].item())

            if 'market_regime' in outputs:
                regime_probs = torch.softmax(outputs['market_regime'], dim=-1)
                regime_idx = regime_probs.argmax(dim=-1).item()

                regimes = ['BULL', 'BEAR', 'RANGING', 'HIGH_VOL']
                result['market_regime'] = regimes[regime_idx]
                result['regime_confidence'] = float(regime_probs.max().item())

            if 'position_size' in outputs:
                result['optimal_position_size'] = float(outputs['position_size'].item())

            # Interpretability
            if 'interpretability' in outputs:
                interp = outputs['interpretability']

                if 'variable_weights' in interp:
                    # Top 10 most important features
                    var_weights = interp['variable_weights'][0, -1].cpu().numpy()
                    top_indices = var_weights.argsort()[-10:][::-1]

                    result['feature_importance'] = {
                        features.columns[i]: float(var_weights[i])
                        for i in top_indices
                    }

                if 'attention_weights' in interp:
                    # Attention over time (focus on recent bars)
                    attn = interp['attention_weights'][0, -1].cpu().numpy()
                    result['temporal_attention'] = {
                        f'bar_{i}': float(attn[i])
                        for i in range(max(0, len(attn) - 10), len(attn))
                    }

        # Store for tracking
        self.last_predictions[symbol] = result
        self.prediction_confidence[symbol] = result.get('direction_confidence', 0.5)

        return result

    async def adapt_to_new_regime(
        self,
        recent_data: pd.DataFrame,
        learning_rate: float = 0.0001
    ):
        """
        Quickly adapt to new market regime using meta-learning
        """
        logger.info("Adapting to new market regime...")

        # Extract features
        features = self.feature_engineer.extract_all_features(recent_data)
        targets = engineer_target_variables(recent_data, horizons=[1])

        # Prepare data
        X = features.values
        y = targets.values

        # Remove NaN
        valid_idx = ~(np.isnan(X).any(axis=1) | np.isnan(y).any(axis=1))
        X = X[valid_idx]
        y = y[valid_idx]

        if len(X) < 10:
            logger.warning("Insufficient data for adaptation")
            return

        # Convert to tensors
        X_tensor = torch.FloatTensor(X).to(self.device)
        y_tensor = torch.FloatTensor(y).to(self.device)

        # Continual learning update
        optimizer = torch.optim.Adam(self.main_model.parameters(), lr=learning_rate)
        loss_fn = torch.nn.MSELoss()

        num_steps = 5
        for step in range(num_steps):
            loss = self.continual_learner.continual_train_step(
                X_tensor,
                y_tensor,
                optimizer,
                loss_fn
            )

            if step % 2 == 0:
                logger.info(f"Adaptation step {step + 1}/{num_steps}, loss: {loss:.4f}")

        logger.info("Adaptation complete")

    def get_trading_signal(
        self,
        symbol: str,
        min_confidence: float = 0.6
    ) -> Optional[Dict]:
        """
        Get actionable trading signal for a symbol

        Returns:
            Dict with action, size, stop_loss, take_profit or None
        """
        if symbol not in self.last_predictions:
            logger.warning(f"No prediction available for {symbol}")
            return None

        pred = self.last_predictions[symbol]

        # Check confidence threshold
        confidence = pred.get('direction_confidence', 0)
        if confidence < min_confidence:
            logger.info(f"{symbol}: Low confidence ({confidence:.2f}), no signal")
            return None

        # Determine action
        direction = pred.get('direction', 'SIDEWAYS')

        if direction == 'SIDEWAYS':
            return None

        action = 'BUY' if direction == 'UP' else 'SELL'

        # Position size (from model or default)
        position_size = pred.get('optimal_position_size', 0.02)  # Default 2%

        # Adjust size by confidence
        adjusted_size = position_size * confidence

        # Volatility-adjusted stops
        volatility = pred.get('predicted_volatility', 0.02)

        if action == 'BUY':
            stop_loss_pct = max(0.02, volatility * 1.5)  # 1.5x ATR
            take_profit_pct = stop_loss_pct * 2  # 2:1 reward:risk
        else:
            stop_loss_pct = max(0.02, volatility * 1.5)
            take_profit_pct = stop_loss_pct * 2

        signal = {
            'symbol': symbol,
            'action': action,
            'position_size': round(adjusted_size, 4),
            'confidence': round(confidence, 3),
            'stop_loss_pct': round(stop_loss_pct, 4),
            'take_profit_pct': round(take_profit_pct, 4),
            'market_regime': pred.get('market_regime', 'UNKNOWN'),
            'predicted_volatility': round(volatility, 4),
            'reasoning': (
                f"{direction} with {confidence * 100:.1f}% confidence "
                f"in {pred.get('market_regime', 'UNKNOWN')} regime"
            ),
        }

        logger.info(f"Signal for {symbol}: {signal}")
        return signal

    def save_state(self):
        """Save complete system state"""
        state_path = self.model_dir / 'system_state.pt'

        state = {
            'model_state': self.main_model.state_dict() if self.main_model else None,
            'last_predictions': self.last_predictions,
            'prediction_confidence': self.prediction_confidence,
            'feature_importance': self.feature_importance,
            'prediction_accuracy': self.prediction_accuracy,
            'sharpe_ratio_history': self.sharpe_ratio_history
        }

        torch.save(state, state_path)
        logger.info(f"System state saved to {state_path}")

    def load_state(self):
        """Load complete system state"""
        state_path = self.model_dir / 'system_state.pt'

        if not state_path.exists():
            logger.warning("No saved state found")
            return

        state = torch.load(state_path, map_location=self.device)

        if state['model_state'] and self.main_model:
            self.main_model.load_state_dict(state['model_state'])

        self.last_predictions = state.get('last_predictions', {})
        self.prediction_confidence = state.get('prediction_confidence', {})
        self.feature_importance = state.get('feature_importance', {})
        self.prediction_accuracy = state.get('prediction_accuracy', [])
        self.sharpe_ratio_history = state.get('sharpe_ratio_history', [])

        logger.info(f"System state loaded from {state_path}")

    def get_performance_report(self) -> Dict:
        """Get comprehensive performance metrics"""
        return {
            'prediction_accuracy': np.mean(self.prediction_accuracy) if self.prediction_accuracy else 0,
            'sharpe_ratio': np.mean(self.sharpe_ratio_history) if self.sharpe_ratio_history else 0,
            'num_predictions': len(self.prediction_accuracy),
            'avg_confidence': np.mean(list(self.prediction_confidence.values())) if self.prediction_confidence else 0,
            'active_symbols': len(self.last_predictions),
            'device': str(self.device),
            'model_parameters': sum(p.numel() for p in self.main_model.parameters()) if self.main_model else 0
        }


# Integration helper functions

async def integrate_with_existing_bot(
    bot_instance,
    config: Dict,
    train_on_startup: bool = False,
    historical_data_path: Optional[str] = None
):
    """
    Integrate UltimateTradingAI with existing bot

    Args:
        bot_instance: Existing bot instance
        config: Configuration dict
        train_on_startup: Whether to train on historical data at startup
        historical_data_path: Path to historical CSV data
    """
    logger.info("Integrating Ultimate Trading AI with bot...")

    # Create AI system
    ai_system = UltimateTradingAI(
        config=config,
        device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    )

    # Try to load existing state
    ai_system.load_state()

    # Train if requested
    if train_on_startup and historical_data_path:
        data = pd.read_csv(historical_data_path, index_col=0, parse_dates=True)
        symbols = config.get('symbols', ['BTC/USDT'])

        await ai_system.train_from_historical_data(
            data=data,
            symbols=symbols,
            epochs=50,
            optimize_hyperparams=False
        )

    # Attach to bot
    bot_instance.ai_system = ai_system

    logger.info("Integration complete!")
    return ai_system

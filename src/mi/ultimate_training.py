"""
Ultimate Training Pipeline with AutoML and Hyperparameter Optimization
Makes our models truly learn and adapt to crypto markets
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import optuna
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Callable
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class CryptoTradingDataset(torch.utils.data.Dataset):
    """
    PyTorch dataset for crypto trading data
    Handles sequences and multiple targets
    """

    def __init__(
        self,
        features: np.ndarray,
        targets: np.ndarray,
        sequence_length: int = 50
    ):
        self.features = torch.FloatTensor(features)
        self.targets = torch.FloatTensor(targets)
        self.sequence_length = sequence_length

    def __len__(self):
        return len(self.features) - self.sequence_length

    def __getitem__(self, idx):
        x = self.features[idx:idx + self.sequence_length]
        y = self.targets[idx + self.sequence_length]
        return x, y


class UltimateTrainer:
    """
    Ultimate training system with:
    - Hyperparameter optimization
    - Early stopping
    - Learning rate scheduling
    - Gradient clipping
    - Model checkpointing
    - Continual learning
    """

    def __init__(
        self,
        model: nn.Module,
        device: torch.device,
        save_dir: str = 'models/checkpoints'
    ):
        self.model = model
        self.device = device
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.training_history = {
            'train_loss': [],
            'val_loss': [],
            'train_metrics': [],
            'val_metrics': [],
            'learning_rates': []
        }

        self.best_val_loss = float('inf')
        self.epochs_without_improvement = 0

    def train_epoch(
        self,
        train_loader: DataLoader,
        optimizer: optim.Optimizer,
        loss_fn: nn.Module,
        grad_clip: float = 1.0
    ) -> Tuple[float, Dict]:
        """Train for one epoch"""
        self.model.train()
        total_loss = 0.0
        num_batches = 0

        all_predictions = []
        all_targets = []

        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            # Forward pass
            optimizer.zero_grad()
            outputs = self.model(batch_x)

            # Handle multi-task outputs
            if isinstance(outputs, dict):
                # Sum losses from all tasks
                loss = sum(
                    loss_fn(outputs[task], batch_y[:, i:i + 1])
                    for i, task in enumerate(outputs.keys())
                    if task not in ['interpretability', 'learned_graph']
                ) / len([k for k in outputs.keys() if k not in ['interpretability', 'learned_graph']])

                # Use first task for metrics
                predictions = outputs[list(outputs.keys())[0]]
            else:
                loss = loss_fn(outputs, batch_y)
                predictions = outputs

            # Backward pass
            loss.backward()

            # Gradient clipping
            if grad_clip > 0:
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), grad_clip)

            optimizer.step()

            total_loss += loss.item()
            num_batches += 1

            all_predictions.append(predictions.detach().cpu())
            all_targets.append(batch_y.detach().cpu())

        avg_loss = total_loss / num_batches

        # Calculate metrics
        predictions_tensor = torch.cat(all_predictions, dim=0)
        targets_tensor = torch.cat(all_targets, dim=0)
        metrics = self.calculate_metrics(predictions_tensor, targets_tensor)

        return avg_loss, metrics

    def validate(
        self,
        val_loader: DataLoader,
        loss_fn: nn.Module
    ) -> Tuple[float, Dict]:
        """Validate model"""
        self.model.eval()
        total_loss = 0.0
        num_batches = 0

        all_predictions = []
        all_targets = []

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                outputs = self.model(batch_x)

                # Handle multi-task outputs
                if isinstance(outputs, dict):
                    loss = sum(
                        loss_fn(outputs[task], batch_y[:, i:i + 1])
                        for i, task in enumerate(outputs.keys())
                        if task not in ['interpretability', 'learned_graph']
                    ) / len([k for k in outputs.keys() if k not in ['interpretability', 'learned_graph']])
                    predictions = outputs[list(outputs.keys())[0]]
                else:
                    loss = loss_fn(outputs, batch_y)
                    predictions = outputs

                total_loss += loss.item()
                num_batches += 1

                all_predictions.append(predictions.cpu())
                all_targets.append(batch_y.cpu())

        avg_loss = total_loss / num_batches

        predictions_tensor = torch.cat(all_predictions, dim=0)
        targets_tensor = torch.cat(all_targets, dim=0)
        metrics = self.calculate_metrics(predictions_tensor, targets_tensor)

        return avg_loss, metrics

    def calculate_metrics(
        self,
        predictions: torch.Tensor,
        targets: torch.Tensor
    ) -> Dict:
        """Calculate comprehensive metrics"""
        metrics = {}

        # For classification tasks
        if predictions.shape[-1] > 1:
            pred_classes = predictions.argmax(dim=-1)
            target_classes = targets.argmax(dim=-1) if targets.shape[-1] > 1 else targets.squeeze()

            accuracy = (pred_classes == target_classes).float().mean().item()
            metrics['accuracy'] = accuracy

        # For regression tasks
        else:
            mse = nn.functional.mse_loss(predictions, targets).item()
            mae = nn.functional.l1_loss(predictions, targets).item()

            metrics['mse'] = mse
            metrics['mae'] = mae

            # Direction accuracy
            pred_direction = torch.sign(predictions)
            target_direction = torch.sign(targets)
            direction_accuracy = (pred_direction == target_direction).float().mean().item()
            metrics['direction_accuracy'] = direction_accuracy

        return metrics

    def train(
        self,
        train_loader: DataLoader,
        val_loader: DataLoader,
        num_epochs: int = 100,
        learning_rate: float = 0.001,
        patience: int = 10,
        grad_clip: float = 1.0
    ) -> Dict:
        """
        Full training loop with all bells and whistles
        """
        # Loss function
        loss_fn = nn.MSELoss()

        # Optimizer with weight decay
        optimizer = optim.AdamW(
            self.model.parameters(),
            lr=learning_rate,
            weight_decay=0.01
        )

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode='min',
            factor=0.5,
            patience=5,
            verbose=True
        )

        logger.info(f"Starting training for {num_epochs} epochs")

        for epoch in range(num_epochs):
            # Train
            train_loss, train_metrics = self.train_epoch(
                train_loader,
                optimizer,
                loss_fn,
                grad_clip
            )

            # Validate
            val_loss, val_metrics = self.validate(val_loader, loss_fn)

            # Update scheduler
            scheduler.step(val_loss)

            # Record history
            self.training_history['train_loss'].append(train_loss)
            self.training_history['val_loss'].append(val_loss)
            self.training_history['train_metrics'].append(train_metrics)
            self.training_history['val_metrics'].append(val_metrics)
            self.training_history['learning_rates'].append(
                optimizer.param_groups[0]['lr']
            )

            # Logging
            logger.info(
                f"Epoch {epoch + 1}/{num_epochs} - "
                f"Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}, "
                f"Train Acc: {train_metrics.get('direction_accuracy', 0):.3f}, "
                f"Val Acc: {val_metrics.get('direction_accuracy', 0):.3f}"
            )

            # Early stopping and checkpointing
            if val_loss < self.best_val_loss:
                self.best_val_loss = val_loss
                self.epochs_without_improvement = 0

                # Save best model
                self.save_checkpoint('best_model.pt', epoch, val_loss, val_metrics)
                logger.info(f"New best model saved with val_loss: {val_loss:.4f}")
            else:
                self.epochs_without_improvement += 1

                if self.epochs_without_improvement >= patience:
                    logger.info(f"Early stopping triggered after {epoch + 1} epochs")
                    break

            # Save periodic checkpoint
            if (epoch + 1) % 10 == 0:
                self.save_checkpoint(
                    f'checkpoint_epoch_{epoch + 1}.pt',
                    epoch,
                    val_loss,
                    val_metrics)

        logger.info("Training completed!")
        return self.training_history

    def save_checkpoint(
        self,
        filename: str,
        epoch: int,
        val_loss: float,
        metrics: Dict
    ):
        """Save model checkpoint"""
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'val_loss': val_loss,
            'metrics': metrics,
            'training_history': self.training_history,
            'timestamp': datetime.now().isoformat()
        }

        filepath = self.save_dir / filename
        torch.save(checkpoint, filepath)

    def load_checkpoint(self, filename: str):
        """Load model checkpoint"""
        filepath = self.save_dir / filename
        checkpoint = torch.load(filepath, map_location=self.device)

        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.training_history = checkpoint.get('training_history', self.training_history)

        logger.info(f"Loaded checkpoint from epoch {checkpoint['epoch']}")
        return checkpoint


class HyperparameterOptimizer:
    """
    Automated hyperparameter optimization using Optuna
    Finds the best model architecture and training parameters
    """

    def __init__(
        self,
        model_factory: Callable,
        train_data: Tuple[np.ndarray, np.ndarray],
        val_data: Tuple[np.ndarray, np.ndarray],
        device: torch.device,
        n_trials: int = 50
    ):
        self.model_factory = model_factory
        self.train_data = train_data
        self.val_data = val_data
        self.device = device
        self.n_trials = n_trials

        self.study = None
        self.best_params = None

    def objective(self, trial: optuna.Trial) -> float:
        """
        Objective function for Optuna
        Returns validation loss to minimize
        """
        # Suggest hyperparameters
        params = {
            'hidden_size': trial.suggest_int('hidden_size', 64, 256, step=32),
            'num_layers': trial.suggest_int('num_layers', 2, 4),
            'num_attention_heads': trial.suggest_int('num_attention_heads', 2, 8),
            'dropout': trial.suggest_float('dropout', 0.1, 0.5),
            'learning_rate': trial.suggest_float('learning_rate', 1e-5, 1e-2, log=True),
            'batch_size': trial.suggest_categorical('batch_size', [32, 64, 128]),
            'grad_clip': trial.suggest_float('grad_clip', 0.5, 2.0)
        }

        # Create model with these hyperparameters
        model = self.model_factory(**params).to(self.device)

        # Create data loaders
        train_dataset = CryptoTradingDataset(self.train_data[0], self.train_data[1])
        val_dataset = CryptoTradingDataset(self.val_data[0], self.val_data[1])

        train_loader = DataLoader(
            train_dataset,
            batch_size=params['batch_size'],
            shuffle=True
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=params['batch_size']
        )

        # Train with early stopping
        trainer = UltimateTrainer(model, self.device)

        try:
            history = trainer.train(
                train_loader,
                val_loader,
                num_epochs=30,  # Reduced for hyperparameter search
                learning_rate=params['learning_rate'],
                patience=5,
                grad_clip=params['grad_clip']
            )

            # Return best validation loss
            best_val_loss = min(history['val_loss'])
            return best_val_loss

        except Exception as e:
            logger.warning(f"Trial failed: {e}")
            return float('inf')

    def optimize(self) -> Dict:
        """
        Run hyperparameter optimization
        """
        logger.info(f"Starting hyperparameter optimization with {self.n_trials} trials")

        # Create study
        self.study = optuna.create_study(
            direction='minimize',
            pruner=optuna.pruners.MedianPruner()
        )

        # Optimize
        self.study.optimize(
            self.objective,
            n_trials=self.n_trials,
            timeout=None,
            show_progress_bar=True
        )

        self.best_params = self.study.best_params

        logger.info("Optimization completed!")
        logger.info(f"Best val loss: {self.study.best_value:.4f}")
        logger.info(f"Best params: {self.best_params}")

        return self.best_params

    def get_optimization_history(self) -> pd.DataFrame:
        """Get history of all trials"""
        return self.study.trials_dataframe()


class ContinualLearner:
    """
    Continual learning to adapt to market regime changes
    Prevents catastrophic forgetting while learning new patterns
    """

    def __init__(
        self,
        model: nn.Module,
        device: torch.device,
        memory_size: int = 1000,
        importance_weight: float = 0.5
    ):
        self.model = model
        self.device = device
        self.memory_size = memory_size
        self.importance_weight = importance_weight

        # Experience replay memory
        self.memory_x = []
        self.memory_y = []

        # Fisher information for EWC (Elastic Weight Consolidation)
        self.fisher_information = {}
        self.optimal_params = {}

    def compute_fisher_information(
        self,
        data_loader: DataLoader,
        loss_fn: nn.Module
    ):
        """
        Compute Fisher Information Matrix
        Measures importance of each parameter
        """
        self.model.eval()

        # Initialize Fisher info
        for name, param in self.model.named_parameters():
            self.fisher_information[name] = torch.zeros_like(param)
            self.optimal_params[name] = param.clone().detach()

        # Accumulate gradients
        for batch_x, batch_y in data_loader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            self.model.zero_grad()
            outputs = self.model(batch_x)

            if isinstance(outputs, dict):
                outputs = outputs[list(outputs.keys())[0]]

            loss = loss_fn(outputs, batch_y)
            loss.backward()

            # Accumulate squared gradients
            for name, param in self.model.named_parameters():
                if param.grad is not None:
                    self.fisher_information[name] += param.grad.pow(2)

        # Normalize
        num_samples = len(data_loader.dataset)
        for name in self.fisher_information:
            self.fisher_information[name] /= num_samples

        logger.info("Fisher Information Matrix computed")

    def ewc_loss(self) -> torch.Tensor:
        """
        Elastic Weight Consolidation loss
        Penalizes changes to important parameters
        """
        loss = 0.0

        for name, param in self.model.named_parameters():
            if name in self.fisher_information:
                fisher = self.fisher_information[name]
                optimal = self.optimal_params[name]
                loss += (fisher * (param - optimal).pow(2)).sum()

        return self.importance_weight * loss

    def add_to_memory(self, x: torch.Tensor, y: torch.Tensor):
        """Add samples to experience replay memory"""
        self.memory_x.append(x.cpu())
        self.memory_y.append(y.cpu())

        # Keep memory size limited
        if len(self.memory_x) > self.memory_size:
            self.memory_x.pop(0)
            self.memory_y.pop(0)

    def sample_memory(self, batch_size: int) -> Tuple[torch.Tensor, torch.Tensor]:
        """Sample from memory for replay"""
        if not self.memory_x:
            return None, None

        indices = np.random.choice(len(self.memory_x), min(
            batch_size, len(self.memory_x)), replace=False)

        x_batch = torch.cat([self.memory_x[i] for i in indices], dim=0).to(self.device)
        y_batch = torch.cat([self.memory_y[i] for i in indices], dim=0).to(self.device)

        return x_batch, y_batch

    def continual_train_step(
        self,
        batch_x: torch.Tensor,
        batch_y: torch.Tensor,
        optimizer: optim.Optimizer,
        loss_fn: nn.Module
    ) -> float:
        """
        Single training step with continual learning
        """
        # Forward pass on new data
        outputs = self.model(batch_x)

        if isinstance(outputs, dict):
            outputs = outputs[list(outputs.keys())[0]]

        # Standard loss
        loss = loss_fn(outputs, batch_y)

        # Add EWC penalty
        if self.fisher_information:
            loss += self.ewc_loss()

        # Experience replay
        memory_x, memory_y = self.sample_memory(batch_size=batch_x.size(0))
        if memory_x is not None:
            memory_outputs = self.model(memory_x)
            if isinstance(memory_outputs, dict):
                memory_outputs = memory_outputs[list(memory_outputs.keys())[0]]
            memory_loss = loss_fn(memory_outputs, memory_y)
            loss += 0.5 * memory_loss  # Weight for replay

        # Backward pass
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # Add to memory
        self.add_to_memory(batch_x, batch_y)

        return loss.item()


def create_ensemble_predictions(
    models: List[nn.Module],
    x: torch.Tensor,
    weights: Optional[List[float]] = None
) -> torch.Tensor:
    """
    Ensemble predictions from multiple models
    """
    if weights is None:
        weights = [1.0 / len(models)] * len(models)

    predictions = []
    for model in models:
        model.eval()
        with torch.no_grad():
            pred = model(x)
            if isinstance(pred, dict):
                pred = pred[list(pred.keys())[0]]
            predictions.append(pred)

    # Weighted average
    ensemble_pred = sum(w * p for w, p in zip(weights, predictions))

    return ensemble_pred


def optimize_ensemble_weights(
    models: List[nn.Module],
    val_loader: DataLoader,
    device: torch.device
) -> List[float]:
    """
    Find optimal ensemble weights using validation set
    """
    from scipy.optimize import minimize

    def ensemble_loss(weights):
        total_loss = 0.0
        num_batches = 0

        for batch_x, batch_y in val_loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)

            pred = create_ensemble_predictions(models, batch_x, weights.tolist())
            loss = nn.functional.mse_loss(pred, batch_y)
            total_loss += loss.item()
            num_batches += 1

        return total_loss / num_batches

    # Initial weights (equal)
    initial_weights = np.ones(len(models)) / len(models)

    # Constraints: weights sum to 1 and are positive
    constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
    bounds = [(0, 1)] * len(models)

    # Optimize
    result = minimize(
        ensemble_loss,
        initial_weights,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints
    )

    optimal_weights = result.x.tolist()
    logger.info(f"Optimal ensemble weights: {optimal_weights}")

    return optimal_weights

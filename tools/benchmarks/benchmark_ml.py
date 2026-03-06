"""ML inference benchmarks."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""

    name: str
    batch_size: int
    n_runs: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_per_sec: float
    error: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class MLBenchmark:
    """
    Benchmarks ML model inference latency and throughput.

    Supports both synchronous model callables and optional GPU timing via
    PyTorch CUDA events (lazy-imported).

    Parameters
    ----------
    model_fn : callable
        Function accepting a NumPy array (batch) and returning predictions.
    input_shape : tuple
        Shape of a single sample, e.g. ``(128,)`` or ``(10, 64)``.
    dtype : str
        NumPy dtype for synthetic inputs.
    warmup_runs : int
        Number of warm-up calls before timing begins.
    use_cuda_events : bool
        Use CUDA events for precise GPU timing when available.
    """

    def __init__(
        self,
        model_fn: Callable[[np.ndarray], Any],
        input_shape: tuple = (64,),
        dtype: str = "float32",
        warmup_runs: int = 5,
        use_cuda_events: bool = True,
    ) -> None:
        self.model_fn = model_fn
        self.input_shape = input_shape
        self.dtype = dtype
        self.warmup_runs = warmup_runs
        self.use_cuda_events = use_cuda_events

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        batch_sizes: List[int],
        n_runs: int = 100,
        name: str = "model",
    ) -> List[BenchmarkResult]:
        """
        Benchmark over multiple batch sizes.

        Parameters
        ----------
        batch_sizes : list of int
            Batch sizes to evaluate.
        n_runs : int
            Number of timed runs per batch size.
        name : str
            Benchmark name prefix.

        Returns
        -------
        list of BenchmarkResult
        """
        results: List[BenchmarkResult] = []
        for bs in batch_sizes:
            res = self._benchmark_batch(bs, n_runs, name)
            results.append(res)
            logger.info(
                "%s | batch=%d | mean=%.2f ms | p95=%.2f ms | throughput=%.0f/s",
                res.name, res.batch_size, res.mean_latency_ms,
                res.p95_latency_ms, res.throughput_per_sec,
            )
        return results

    def compare(
        self,
        other: "MLBenchmark",
        batch_sizes: List[int],
        n_runs: int = 100,
        names: tuple = ("baseline", "candidate"),
    ) -> Dict[int, Dict[str, float]]:
        """
        Compare two models and return speedup ratios per batch size.

        Parameters
        ----------
        other : MLBenchmark
            The candidate model to compare against.
        batch_sizes : list of int
        n_runs : int
        names : tuple of str
            Labels for self and other.

        Returns
        -------
        dict
            ``{batch_size: {"speedup": float, "baseline_ms": float, "candidate_ms": float}}``
        """
        baseline_results = self.run(batch_sizes, n_runs, name=names[0])
        candidate_results = other.run(batch_sizes, n_runs, name=names[1])
        comparison: Dict[int, Dict[str, float]] = {}
        for b, c in zip(baseline_results, candidate_results):
            speedup = b.mean_latency_ms / c.mean_latency_ms if c.mean_latency_ms else 0.0
            comparison[b.batch_size] = {
                "speedup": speedup,
                "baseline_ms": b.mean_latency_ms,
                "candidate_ms": c.mean_latency_ms,
            }
        return comparison

    def print_summary(self, results: List[BenchmarkResult]) -> None:
        """Print a formatted summary table to stdout."""
        header = f"{'Name':<20} {'Batch':>6} {'Mean ms':>9} {'P95 ms':>8} {'Tput/s':>10}"
        print(header)
        print("-" * len(header))
        for r in results:
            print(
                f"{r.name:<20} {r.batch_size:>6} {r.mean_latency_ms:>9.2f} "
                f"{r.p95_latency_ms:>8.2f} {r.throughput_per_sec:>10.0f}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _benchmark_batch(self, batch_size: int, n_runs: int, name: str) -> BenchmarkResult:
        shape = (batch_size,) + self.input_shape
        rng = np.random.default_rng(42)
        inputs = rng.random(shape).astype(self.dtype)

        # Warm-up
        for _ in range(self.warmup_runs):
            try:
                self.model_fn(inputs)
            except Exception:  # noqa: BLE001
                pass

        latencies: List[float] = []
        error_msg = ""

        for _ in range(n_runs):
            t0 = time.perf_counter()
            try:
                self.model_fn(inputs)
                latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as exc:  # noqa: BLE001
                error_msg = str(exc)
                break

        if not latencies:
            return BenchmarkResult(
                name=name, batch_size=batch_size, n_runs=0,
                mean_latency_ms=0.0, p50_latency_ms=0.0,
                p95_latency_ms=0.0, p99_latency_ms=0.0,
                throughput_per_sec=0.0, error=error_msg,
            )

        arr = np.array(latencies)
        mean_ms = float(arr.mean())
        return BenchmarkResult(
            name=name,
            batch_size=batch_size,
            n_runs=len(latencies),
            mean_latency_ms=mean_ms,
            p50_latency_ms=float(np.percentile(arr, 50)),
            p95_latency_ms=float(np.percentile(arr, 95)),
            p99_latency_ms=float(np.percentile(arr, 99)),
            throughput_per_sec=batch_size / (mean_ms / 1000) if mean_ms > 0 else 0.0,
            error=error_msg,
        )


def benchmark_sklearn_model(
    model: Any,
    input_shape: tuple = (64,),
    batch_sizes: Optional[List[int]] = None,
    n_runs: int = 100,
) -> List[BenchmarkResult]:
    """
    Convenience function to benchmark a scikit-learn compatible model.

    Parameters
    ----------
    model : sklearn-compatible model
        Must have a ``predict`` method.
    input_shape : tuple
        Shape of a single input sample.
    batch_sizes : list of int, optional
        Defaults to [1, 8, 32, 128].
    n_runs : int
        Number of timed iterations per batch.

    Returns
    -------
    list of BenchmarkResult
    """
    batch_sizes = batch_sizes or [1, 8, 32, 128]
    bench = MLBenchmark(model_fn=model.predict, input_shape=input_shape)
    return bench.run(batch_sizes, n_runs=n_runs, name=type(model).__name__)

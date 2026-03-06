"""Data fetching benchmarks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FetchBenchmarkResult:
    """Result of a data-fetching benchmark run."""

    name: str
    n_requests: int
    concurrency: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_rps: float           # requests per second
    error_rate: float               # fraction of failed requests
    total_seconds: float
    error: str = ""


class DataFetchBenchmark:
    """
    Benchmarks data-fetching functions under various concurrency levels.

    Supports both synchronous and async fetch functions.  Synthetic
    latency can be injected for unit-testing without a live exchange.

    Parameters
    ----------
    fetch_fn : callable
        Async or sync callable with no required arguments that simulates
        or performs a single data fetch.
    name : str
        Benchmark display name.
    simulate_latency_ms : float
        If > 0, adds artificial latency (for testing without a live source).
    """

    def __init__(
        self,
        fetch_fn: Callable[[], Any],
        name: str = "fetch",
        simulate_latency_ms: float = 0.0,
    ) -> None:
        self.fetch_fn = fetch_fn
        self.name = name
        self.simulate_latency_ms = simulate_latency_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_sync(
        self,
        n_requests: int = 100,
    ) -> FetchBenchmarkResult:
        """
        Benchmark synchronous sequential fetching.

        Parameters
        ----------
        n_requests : int
            Total number of fetch calls.

        Returns
        -------
        FetchBenchmarkResult
        """
        latencies: List[float] = []
        errors = 0
        t_start = time.perf_counter()

        for _ in range(n_requests):
            t0 = time.perf_counter()
            try:
                if self.simulate_latency_ms > 0:
                    time.sleep(self.simulate_latency_ms / 1000)
                else:
                    self.fetch_fn()
                latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.debug("Fetch error: %s", exc)

        total_seconds = time.perf_counter() - t_start
        return self._build_result(latencies, errors, n_requests, 1, total_seconds)

    async def run_async(
        self,
        n_requests: int = 100,
        concurrency: int = 10,
    ) -> FetchBenchmarkResult:
        """
        Benchmark async concurrent fetching.

        Parameters
        ----------
        n_requests : int
            Total number of fetch calls.
        concurrency : int
            Maximum concurrent in-flight requests.

        Returns
        -------
        FetchBenchmarkResult
        """
        semaphore = asyncio.Semaphore(concurrency)
        latencies: List[float] = []
        errors = 0
        t_start = time.perf_counter()

        async def _single() -> Optional[float]:
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    if self.simulate_latency_ms > 0:
                        await asyncio.sleep(self.simulate_latency_ms / 1000)
                    elif asyncio.iscoroutinefunction(self.fetch_fn):
                        await self.fetch_fn()
                    else:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, self.fetch_fn)
                    return (time.perf_counter() - t0) * 1000
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Async fetch error: %s", exc)
                    return None

        results = await asyncio.gather(*[_single() for _ in range(n_requests)])
        for r in results:
            if r is None:
                errors += 1
            else:
                latencies.append(r)

        total_seconds = time.perf_counter() - t_start
        return self._build_result(latencies, errors, n_requests, concurrency, total_seconds)

    def run_concurrency_sweep(
        self,
        concurrency_levels: Optional[List[int]] = None,
        n_requests: int = 200,
    ) -> List[FetchBenchmarkResult]:
        """
        Run async benchmarks across multiple concurrency levels.

        Parameters
        ----------
        concurrency_levels : list of int, optional
            Defaults to [1, 5, 10, 20, 50].
        n_requests : int
            Requests per concurrency level.

        Returns
        -------
        list of FetchBenchmarkResult
        """
        concurrency_levels = concurrency_levels or [1, 5, 10, 20, 50]
        results: List[FetchBenchmarkResult] = []
        for c in concurrency_levels:
            res = asyncio.run(self.run_async(n_requests=n_requests, concurrency=c))
            results.append(res)
            logger.info(
                "%s | conc=%d | mean=%.2f ms | tput=%.0f rps | err=%.1f%%",
                res.name, res.concurrency, res.mean_latency_ms,
                res.throughput_rps, res.error_rate * 100,
            )
        return results

    def print_summary(self, results: List[FetchBenchmarkResult]) -> None:
        """Print a formatted summary table."""
        header = f"{'Name':<20} {'Conc':>5} {'N':>6} {'Mean ms':>9} {'P95 ms':>8} {'RPS':>8} {'Err%':>6}"
        print(header)
        print("-" * len(header))
        for r in results:
            print(
                f"{r.name:<20} {r.concurrency:>5} {r.n_requests:>6} "
                f"{r.mean_latency_ms:>9.2f} {r.p95_latency_ms:>8.2f} "
                f"{r.throughput_rps:>8.0f} {r.error_rate * 100:>6.1f}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        latencies: List[float],
        errors: int,
        n_requests: int,
        concurrency: int,
        total_seconds: float,
    ) -> FetchBenchmarkResult:
        if not latencies:
            return FetchBenchmarkResult(
                name=self.name, n_requests=n_requests, concurrency=concurrency,
                mean_latency_ms=0.0, p50_latency_ms=0.0, p95_latency_ms=0.0,
                p99_latency_ms=0.0, throughput_rps=0.0,
                error_rate=errors / n_requests if n_requests else 0.0,
                total_seconds=total_seconds,
                error="All requests failed",
            )

        arr = np.array(latencies)
        tput = n_requests / total_seconds if total_seconds > 0 else 0.0
        return FetchBenchmarkResult(
            name=self.name,
            n_requests=n_requests,
            concurrency=concurrency,
            mean_latency_ms=float(arr.mean()),
            p50_latency_ms=float(np.percentile(arr, 50)),
            p95_latency_ms=float(np.percentile(arr, 95)),
            p99_latency_ms=float(np.percentile(arr, 99)),
            throughput_rps=tput,
            error_rate=errors / n_requests if n_requests else 0.0,
            total_seconds=total_seconds,
        )

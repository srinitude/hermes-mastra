"""R08 RED: runner saturation is observable and non-blocking."""

from __future__ import annotations

import time

from async_runner import AsyncRunner


def test_drop_oldest_counter_and_burst_log_are_observable(caplog):
    runner = AsyncRunner(workers=0, queue_size=4)
    samples: list[float] = []
    for _ in range(100):
        start = time.perf_counter()
        runner.submit(lambda: None)
        samples.append((time.perf_counter() - start) * 1_000_000)
    assert runner.dropped > 0
    assert runner.drop_bursts == 1
    assert max(samples) < 50
    assert "queue_saturation" in caplog.text
    runner.shutdown(wait=0.01)

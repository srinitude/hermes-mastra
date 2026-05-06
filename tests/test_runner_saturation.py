"""R08 RED: runner saturation is observable and non-blocking."""

from __future__ import annotations

import threading

from async_runner import AsyncRunner


def test_drop_oldest_counter_and_burst_log_are_observable(caplog):
    runner = AsyncRunner(workers=0, queue_size=4)
    done = threading.Event()

    def saturate_queue() -> None:
        for _ in range(100):
            runner.submit(lambda: None)
        done.set()

    thread = threading.Thread(target=saturate_queue, daemon=True)
    thread.start()
    assert done.wait(1.0)
    assert runner.dropped > 0
    assert runner.drop_bursts == 1
    assert "queue_saturation" in caplog.text
    runner.shutdown(wait=0.01)

import pytest

from proexr.playback.stats import RollingStats


def test_average_and_rate():
    stats = RollingStats(window=4)
    for i in range(6):
        stats.add(0.010 + 0.002 * i, now=100.0 + i * 0.5)
    assert stats.average_ms == pytest.approx(17.0)  # last 4: 14, 16, 18, 20 ms
    assert stats.rate(now=102.5) == pytest.approx(2.0)


def test_empty_stats_are_zero():
    stats = RollingStats()
    assert stats.average_ms == 0.0 and stats.rate() == 0.0

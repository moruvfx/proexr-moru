import threading
import time

import numpy as np

from proexr.media.frame import Frame, MediaSource
from proexr.playback.frame_cache import FrameCache

FRAME_BYTES = 1000


class FakeSource(MediaSource):
    def __init__(self, first: int = 0, last: int = 99, parallel: bool = True) -> None:
        super().__init__(path=None, label="fake", kind="sequence", first=first, last=last,
                         width=10, height=10, parallel_reads=parallel)
        self.reads: list[int] = []
        self._lock = threading.Lock()

    def read(self, number: int, layer: int = 0) -> Frame:
        with self._lock:
            self.reads.append(number)
        return Frame(np.zeros(FRAME_BYTES, np.uint8).reshape(10, 100, 1), "srgb", number)


def wait_until(condition, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_prefetches_ahead_of_playhead_in_play_order():
    cache = FrameCache(max_bytes=FRAME_BYTES * 10, workers=2)
    source = FakeSource()
    cache.follow(source, layer=0, playhead=50, direction=1, play_range=(0, 99))
    assert wait_until(lambda: len(cache.cached_numbers(source, 0)) >= 9)
    cached = cache.cached_numbers(source, 0)
    assert cached <= set(range(50, 60))
    assert 50 in cached and 51 in cached
    cache.shutdown()


def test_reverse_playback_prefetches_backwards():
    cache = FrameCache(max_bytes=FRAME_BYTES * 5, workers=2)
    source = FakeSource()
    cache.follow(source, layer=0, playhead=50, direction=-1, play_range=(0, 99))
    assert wait_until(lambda: len(cache.cached_numbers(source, 0)) >= 4)
    assert cache.cached_numbers(source, 0) <= {50, 49, 48, 47, 46}
    cache.shutdown()


def test_never_exceeds_budget_and_keeps_frames_needed_soonest():
    cache = FrameCache(max_bytes=FRAME_BYTES * 4, workers=1)
    source = FakeSource()
    cache.follow(source, layer=0, playhead=0, direction=1, play_range=(0, 99))
    assert wait_until(lambda: cache.cached_numbers(source, 0) == {0, 1, 2, 3})
    cache.follow(source, layer=0, playhead=2, direction=1, play_range=(0, 99))
    assert wait_until(lambda: cache.cached_numbers(source, 0) == {2, 3, 4, 5})
    assert cache.used_bytes <= FRAME_BYTES * 4
    cache.shutdown()


def test_loop_that_fits_stays_fully_cached():
    cache = FrameCache(max_bytes=FRAME_BYTES * 20, workers=2)
    source = FakeSource()
    cache.follow(source, layer=0, playhead=10, direction=1, play_range=(10, 19))
    assert wait_until(lambda: cache.cached_numbers(source, 0) == set(range(10, 20)))
    reads_before = len(source.reads)
    for playhead in list(range(10, 20)) * 3:
        cache.follow(source, layer=0, playhead=playhead, direction=1, play_range=(10, 19))
    time.sleep(0.2)
    assert len(source.reads) == reads_before
    cache.shutdown()


def test_serial_source_is_read_one_frame_at_a_time():
    class SlowSerial(FakeSource):
        active = 0
        peak = 0

        def read(self, number: int, layer: int = 0) -> Frame:
            SlowSerial.active += 1
            SlowSerial.peak = max(SlowSerial.peak, SlowSerial.active)
            time.sleep(0.005)
            SlowSerial.active -= 1
            return super().read(number, layer)

    cache = FrameCache(max_bytes=FRAME_BYTES * 8, workers=4)
    source = SlowSerial(parallel=False)
    cache.follow(source, layer=0, playhead=0, direction=1, play_range=(0, 99))
    assert wait_until(lambda: len(cache.cached_numbers(source, 0)) == 8)
    assert SlowSerial.peak == 1
    assert source.reads[:8] == list(range(8))
    cache.shutdown()


def test_read_now_returns_frame_and_records_errors():
    class Broken(FakeSource):
        def read(self, number: int, layer: int = 0) -> Frame:
            raise OSError("disk gone")

    cache = FrameCache(max_bytes=FRAME_BYTES * 4, workers=1)
    good = FakeSource()
    assert cache.read_now(good, 7, 0).number == 7
    assert cache.get(good, 7, 0) is not None
    broken = Broken()
    assert cache.read_now(broken, 3, 0) is None
    assert "disk gone" in cache.error_for(broken, 3, 0)
    cache.shutdown()


def test_ready_callback_fires_for_loaded_frames():
    seen = []
    cache = FrameCache(max_bytes=FRAME_BYTES * 3, workers=1)
    cache.on_frame_ready = seen.append
    source = FakeSource()
    cache.follow(source, layer=0, playhead=0, direction=1, play_range=(0, 99))
    assert wait_until(lambda: len(seen) >= 3)
    assert (source.uid, 0, 0) in seen
    cache.shutdown()

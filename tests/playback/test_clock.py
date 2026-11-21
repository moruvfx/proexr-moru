from proexr.playback.clock import LoopMode, PlaybackClock


def make_clock(**kwargs) -> PlaybackClock:
    clock = PlaybackClock(first=0, last=9, fps=10.0, **kwargs)
    return clock


def test_advances_by_elapsed_time_not_ticks():
    clock = make_clock()
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.05) is None
    assert clock.tick(now=0.1) == 1
    assert clock.tick(now=0.35) == 3


def test_loop_wraps_to_in_point():
    clock = make_clock()
    clock.seek(9)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.1) == 0


def test_pingpong_bounces():
    clock = make_clock(loop_mode=LoopMode.PINGPONG)
    clock.seek(8)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.1) == 9
    assert clock.tick(now=0.2) == 8
    assert clock.direction == -1


def test_once_stops_at_out_point():
    clock = make_clock(loop_mode=LoopMode.ONCE)
    clock.seek(8)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.1) == 9
    assert clock.tick(now=0.2) is None
    assert not clock.is_playing


def test_reverse_and_speed():
    clock = make_clock()
    clock.seek(5)
    clock.speed = 2.0
    clock.start(direction=-1, now=0.0)
    assert clock.tick(now=0.1) == 3


def test_in_out_range_limits_playback():
    clock = make_clock()
    clock.set_in_out(2, 4)
    clock.seek(4)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.1) == 2


def test_realtime_skips_to_newest_ready_frame():
    ready = {0, 1, 2, 4}
    clock = make_clock(is_ready=lambda f: f in ready)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.45) == 4
    assert clock.dropped == 3


def test_realtime_waits_when_nothing_is_ready():
    ready = {0}
    clock = make_clock(is_ready=lambda f: f in ready)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.1) is None
    ready.add(1)
    assert clock.tick(now=0.6) == 1


def test_every_frame_mode_never_skips():
    ready = {1, 2, 3, 4, 5}
    clock = make_clock(is_ready=lambda f: f in ready, realtime=False)
    clock.start(direction=1, now=0.0)
    assert clock.tick(now=0.45) == 1
    assert clock.tick(now=0.46) == 2

from proexr.playback.memory import available_memory_bytes, safe_cache_budget

GB = 1 << 30


def test_budget_is_configured_size_when_memory_is_plentiful():
    assert safe_cache_budget(configured=8 * GB, used=2 * GB, available=20 * GB) == 8 * GB


def test_budget_shrinks_to_leave_a_reserve_for_the_system():
    assert safe_cache_budget(configured=8 * GB, used=4 * GB, available=1 * GB, reserve=2 * GB) == 3 * GB


def test_budget_never_drops_below_minimum():
    assert safe_cache_budget(configured=8 * GB, used=0, available=0, reserve=2 * GB, minimum=GB // 2) == GB // 2


def test_available_memory_is_reported():
    assert available_memory_bytes() > 0

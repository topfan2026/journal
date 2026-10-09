from scanner_site import pick_stream_monitor

WIDE = (0, 0, 3440, 1440)
HD = (3440, 0, 1920, 1080)


def test_auto_prefers_the_16_9_monitor():
    assert pick_stream_monitor([WIDE, HD]) == HD
    assert pick_stream_monitor([HD, WIDE]) == HD


def test_single_monitor_is_used():
    assert pick_stream_monitor([WIDE]) == WIDE
    assert pick_stream_monitor([]) is None


def test_off_primary_and_numbers():
    assert pick_stream_monitor([WIDE, HD], "off") is None
    assert pick_stream_monitor([HD, WIDE], "primary") == WIDE
    assert pick_stream_monitor([WIDE, HD], "2") == HD
    assert pick_stream_monitor([WIDE, HD], "9") == HD  # not a monitor number: falls back to auto

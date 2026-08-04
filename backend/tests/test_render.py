from __future__ import annotations

from pipeline.render import (
    AUDIO_BITRATE_KBPS,
    MAX_VIDEO_BITRATE_KBPS,
    _bitrate_cap_kbps,
    _escape_filter_path,
)


class TestBitrateCap:
    def test_stays_inside_the_size_budget(self):
        for duration in (20.0, 35.0, 58.0):
            cap = _bitrate_cap_kbps(duration, 50)
            projected_mb = ((cap + AUDIO_BITRATE_KBPS) * duration) / 8 / 1000
            assert projected_mb <= 50

    def test_long_clip_gets_a_lower_cap(self):
        assert _bitrate_cap_kbps(58.0, 50) < _bitrate_cap_kbps(20.0, 50)

    def test_short_clip_is_capped_by_the_ceiling(self):
        # A 5s clip could technically use 80 Mbps within 50 MB; it should not.
        assert _bitrate_cap_kbps(5.0, 50) == MAX_VIDEO_BITRATE_KBPS

    def test_never_drops_below_a_usable_floor(self):
        assert _bitrate_cap_kbps(600.0, 1) >= 800

    def test_zero_duration_does_not_divide_by_zero(self):
        assert _bitrate_cap_kbps(0.0, 50) == MAX_VIDEO_BITRATE_KBPS


class TestFilterPathEscaping:
    def test_colon_is_escaped(self):
        # An unescaped colon would be read as the next filter argument.
        assert _escape_filter_path("/tmp/a:b.ass") == "/tmp/a\\:b.ass"

    def test_quote_is_escaped(self):
        assert _escape_filter_path("/tmp/it's.ass") == "/tmp/it\\'s.ass"

    def test_plain_path_survives(self):
        assert _escape_filter_path("/work/clip-01.ass") == "/work/clip-01.ass"

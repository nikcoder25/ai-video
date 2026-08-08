"""Server-side source URL validation.

The frontend has the same allowlist, but it runs in the browser and anyone can
post straight to the API. Whatever passes here goes to yt-dlp, which will fetch
any host the container can reach, so these are the checks that matter.
"""

from __future__ import annotations

import pytest

from source_url import InvalidSourceUrl, normalize_source_url


class TestAccepted:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=abc123",
            "https://music.youtube.com/watch?v=abc123",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abc123",
            "https://www.youtube.com/live/abc123",
            "https://www.youtube.com/embed/abc123",
        ],
    )
    def test_real_video_links(self, url):
        assert normalize_source_url(url).startswith(("http://", "https://"))

    def test_scheme_is_optional(self):
        # People paste what they copied from the address bar.
        assert normalize_source_url("youtube.com/watch?v=abc") == (
            "https://youtube.com/watch?v=abc"
        )

    def test_query_is_preserved_so_the_video_id_survives(self):
        assert "v=abc123" in normalize_source_url("https://youtube.com/watch?v=abc123&t=90")

    def test_fragment_is_dropped(self):
        assert "#" not in normalize_source_url("https://youtu.be/abc123#frag")


class TestRejected:
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:6379/",  # loopback service
            "http://backend:8000/health",  # compose-internal
            "http://10.0.0.5/admin",  # RFC1918
            "http://0/",
            "file:///etc/passwd",
            "ftp://example.com/video.mp4",
        ],
    )
    def test_non_youtube_hosts(self, url):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url(url)

    def test_userinfo_cannot_disguise_the_real_host(self):
        # `youtube.com` before the @ is a username, not the host being fetched.
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("http://www.youtube.com@169.254.169.254/")

    def test_lookalike_domain(self):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("https://youtube.com.evil.test/watch?v=abc")

    def test_subdomain_not_on_the_list(self):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("https://evil.youtube.com/watch?v=abc")

    def test_non_standard_port(self):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("http://youtube.com:6379/watch?v=abc")

    def test_watch_link_without_a_video_id(self):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("https://youtube.com/watch")

    def test_channel_and_playlist_links(self):
        for url in (
            "https://youtube.com/@somechannel",
            "https://youtube.com/playlist?list=PL123",
            "https://youtube.com/",
        ):
            with pytest.raises(InvalidSourceUrl):
                normalize_source_url(url)

    def test_empty(self):
        with pytest.raises(InvalidSourceUrl):
            normalize_source_url("   ")

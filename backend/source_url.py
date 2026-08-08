"""Server-side validation of a submitted source URL.

``frontend/lib/source.ts`` runs the same allowlist in the browser, which is a
convenience, not a control -- anyone can post to the API directly. This is the
copy that actually decides, because whatever passes here is handed to yt-dlp,
which will happily fetch ``http://169.254.169.254/`` or anything else the
container can reach and write the response to disk.

An allowlist rather than a denylist: the tool exists to clip YouTube videos, so
enumerating what is allowed is both shorter and safe by default.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)

_VIDEO_PATH = re.compile(r"^/(shorts|live|embed|v)/[^/]+")


class InvalidSourceUrl(ValueError):
    """The URL is not something we are willing to fetch."""


def normalize_source_url(raw: str) -> str:
    """Return a canonical YouTube video URL, or raise :class:`InvalidSourceUrl`.

    Accepts the shapes people actually paste, including a bare ``youtube.com/...``
    with no scheme.
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidSourceUrl("Paste a YouTube link.")

    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = f"https://{text}"

    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise InvalidSourceUrl("Only http and https links are supported.")

    # `hostname` lowercases and strips any `user:pass@` and `:port`, so
    # `http://youtube.com@169.254.169.254/` resolves to the real host rather
    # than the decoy in front of the @.
    host = parsed.hostname or ""
    if host not in YOUTUBE_HOSTS:
        raise InvalidSourceUrl(
            f"{host or 'That link'} isn't supported. Paste a YouTube link, or upload the file."
        )
    if parsed.port not in (None, 80, 443):
        raise InvalidSourceUrl("Only standard http and https ports are supported.")

    path = parsed.path or "/"
    if host.endswith("youtu.be"):
        if len(path.strip("/")) == 0:
            raise InvalidSourceUrl("That link has no video id in it.")
    elif path == "/watch":
        if "v=" not in (parsed.query or ""):
            raise InvalidSourceUrl("That watch link has no `v=` video id in it.")
    elif not _VIDEO_PATH.match(path):
        raise InvalidSourceUrl(
            "That looks like a channel or playlist. Link to a single video."
        )

    # Rebuild from the parsed parts so nothing smuggled into the fragment or
    # the netloc's userinfo survives into what yt-dlp is handed.
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))

"""yt-dlp behind one call: metadata, captions if any, and the media file.

One extract_info per reel. When media is needed it is downloaded from the
info already fetched (process_ie_result), so Instagram sees one page request
per reel, not two.
"""
import copy
import re
from dataclasses import dataclass
from functools import partial
from http.cookiejar import CookieJar, MozillaCookieJar
from urllib.parse import urlparse

from reel_inbox.extractor.captions import vtt_to_text

# Never a merge: joining separate audio and video needs ffmpeg. Audio feeds
# Whisper; video (only when OCR is on) feeds the frame reader. YouTube often
# offers no combined file at all, so the two are fetched separately.
AUDIO_FORMAT = "ba/b"
# HLS first: YouTube now refuses (403) direct https video streams without a
# proof-of-origin token, and yt-dlp's native HLS downloader needs no ffmpeg.
VIDEO_FORMAT = "bv*[height<=720][protocol^=m3u8]/bv*[height<=720]/b[height<=720]/bv*/b"

META_KEYS = ("title", "description", "uploader", "duration", "webpage_url", "extractor_key")

# Checked in order. Instagram's own message names both a rate limit and a
# login requirement, and in practice it means "send cookies", so the login
# patterns come first.
_REASONS = (
    ("login_wall", r"login required|log in|sign in to confirm|use --cookies|cookies-from-browser"),
    ("rate_limited", r"\b429\b|too many requests|rate.?limit"),
    ("unavailable", r"unavailable|private|not available|removed|does not exist|\b404\b"),
)


class FetchFailed(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass
class FetchResult:
    meta: dict
    captions: str | None
    media_path: str | None
    video_path: str | None = None


def classify_error(message: str) -> str:
    lowered = message.lower()
    for reason, pattern in _REASONS:
        if re.search(pattern, lowered):
            return reason
    return "fetch_error"


def _site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return ".".join(host.split(".")[-2:])


def choose_cookie_source(url: str, loaders: dict) -> str | None:
    """The first source, in order, that loads and holds cookies for the
    URL's site. A source that cannot be read (Chrome's locked, app-bound
    encrypted store, say) is skipped rather than fatal."""
    site = _site(url)
    for name, load in loaders.items():
        try:
            jar = load()
        except Exception:
            continue
        if any(cookie.domain.lstrip(".").endswith(site) for cookie in jar):
            return name
    return None


class _Silent:
    """yt-dlp logger that prints nothing; errors still arrive as exceptions."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _load_cookie_file(path: str) -> CookieJar:
    jar = MozillaCookieJar(path)
    jar.load(ignore_discard=True, ignore_expires=True)
    return jar


class YtDlpFetcher:
    """Cookies are tried Firefox first, Chrome second, then a cookies.txt
    file. Cookie values are never logged or written anywhere by this class."""

    def __init__(self, browsers=("firefox", "chrome"), cookies_file: str | None = None):
        self.browsers = tuple(browsers)
        self.cookies_file = cookies_file
        self.last_cookie_source: str | None = None
        self._chosen: dict[str, str | None] = {}

    def _loaders(self) -> dict:
        from yt_dlp.cookies import extract_cookies_from_browser

        loaders = {
            browser: partial(extract_cookies_from_browser, browser, logger=_Silent())
            for browser in self.browsers
        }
        if self.cookies_file:
            loaders["file"] = partial(_load_cookie_file, self.cookies_file)
        return loaders

    def _cookie_params(self, url: str) -> dict:
        site = _site(url)
        if site not in self._chosen:
            self._chosen[site] = choose_cookie_source(url, self._loaders())
        source = self.last_cookie_source = self._chosen[site]
        if source == "file":
            return {"cookiefile": self.cookies_file}
        if source:
            return {"cookiesfrombrowser": (source,)}
        return {}

    def _captions(self, ydl, info) -> str | None:
        for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
            languages = [lang for lang in tracks
                         if lang == "en" or lang.startswith("en-") or lang.endswith("-orig")]
            for lang in languages:
                for entry in tracks[lang]:
                    if entry.get("ext") != "vtt" or not entry.get("url"):
                        continue
                    try:
                        raw = ydl.urlopen(entry["url"]).read().decode("utf-8", "replace")
                    except Exception:
                        continue
                    text = vtt_to_text(raw)
                    if text:
                        return text
        return None

    def fetch(self, url: str, dest_dir: str, want_media: str) -> FetchResult:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        params = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "logger": _Silent(),
            "outtmpl": f"{dest_dir}/%(id)s.%(format_id)s.%(ext)s",
            **self._cookie_params(url),
        }
        with YoutubeDL(params) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except DownloadError as error:
                raise FetchFailed(classify_error(str(error)), str(error)) from error
            captions = self._captions(ydl, info)
            media_path = video_path = None
            if want_media == "always" or captions is None:
                media_path = self._download(ydl, info, AUDIO_FORMAT)
            if want_media == "always":
                video_path = self._download(ydl, info, VIDEO_FORMAT)
        return FetchResult(
            meta={key: info.get(key) for key in META_KEYS},
            captions=captions,
            media_path=media_path,
            video_path=video_path,
        )

    @staticmethod
    def _download(ydl, info, spec: str) -> str | None:
        """One stream from info already fetched: a CDN request, not another
        page request. None when it fails; metadata and captions may still be
        enough evidence."""
        from yt_dlp.utils import DownloadError

        ydl.format_selector = ydl.build_format_selector(spec)
        try:
            done = ydl.process_ie_result(copy.deepcopy(info), download=True)
            return done["requested_downloads"][0]["filepath"]
        except (DownloadError, KeyError, IndexError, TypeError):
            return None

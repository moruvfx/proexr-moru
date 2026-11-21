"""Checks GitHub Releases for a newer installer. Qt-free; the UI decides when to ask and what to run."""
import json
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .errors import UpdateError

RELEASES_URL = "https://api.github.com/repos/moruvfx/proexr-moru/releases/latest"
TRUSTED_DOWNLOAD_PREFIX = "https://github.com/moruvfx/proexr-moru/releases/download/"
INSTALLER_PATTERN = re.compile(r"^ProEXR-Viewer-Setup-[\w.\-]+\.exe$")
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    installer_url: str | None
    notes: str


def parse_version(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", text.split("-")[0].split("+")[0])
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def release_from_json(data: dict) -> Release:
    try:
        version = str(data["tag_name"]).lstrip("vV")
        installer = next((a["browser_download_url"] for a in data.get("assets", [])
                          if INSTALLER_PATTERN.match(a.get("name", ""))
                          and str(a.get("browser_download_url", "")).startswith(TRUSTED_DOWNLOAD_PREFIX)), None)
        return Release(version, str(data.get("html_url", "")), installer, str(data.get("body") or ""))
    except (KeyError, TypeError) as error:
        raise UpdateError(f"Unexpected release data: {error}") from error


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"ProEXR-Viewer/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as error:
        raise UpdateError(f"Cannot reach {url}: {error}") from error


def fetch_latest_release() -> Release:
    try:
        return release_from_json(json.loads(_get(RELEASES_URL)))
    except ValueError as error:
        raise UpdateError(f"Bad response from GitHub: {error}") from error


def download_installer(release: Release, folder: Path | None = None) -> Path:
    """Saves the release installer to a temp folder; only URLs from this project's GitHub releases are accepted."""
    url = release.installer_url
    if not url or not url.startswith(TRUSTED_DOWNLOAD_PREFIX):
        raise UpdateError("This release has no Windows installer")
    name = url.rsplit("/", 1)[-1]
    if not INSTALLER_PATTERN.match(name):
        raise UpdateError(f"Unexpected installer name: {name}")
    target = Path(folder or tempfile.mkdtemp(prefix="proexr-update-")) / name
    target.write_bytes(_get(url))
    return target

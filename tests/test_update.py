import pytest

from proexr import update
from proexr.errors import UpdateError

RELEASE = {
    "tag_name": "v0.3.1",
    "html_url": "https://github.com/moruvfx/proexr-moru/releases/tag/v0.3.1",
    "body": "Faster playback",
    "assets": [
        {"name": "ProEXR-Viewer-0.3.1-portable.zip",
         "browser_download_url": "https://github.com/moruvfx/proexr-moru/releases/download/v0.3.1/p.zip"},
        {"name": "ProEXR-Viewer-Setup-0.3.1.exe",
         "browser_download_url": "https://github.com/moruvfx/proexr-moru/releases/download/v0.3.1/ProEXR-Viewer-Setup-0.3.1.exe"},
    ],
}


def test_version_comparison():
    assert update.is_newer("0.10.0", "0.9.9")
    assert update.is_newer("v1.0", "0.9")
    assert not update.is_newer("0.2.0", "0.2.0")
    assert not update.is_newer("0.2.0-beta", "0.2.0")


def test_release_picks_installer_asset():
    release = update.release_from_json(RELEASE)
    assert release.version == "0.3.1"
    assert release.installer_url.endswith("ProEXR-Viewer-Setup-0.3.1.exe")


def test_installer_from_another_host_is_ignored():
    data = dict(RELEASE, assets=[{"name": "ProEXR-Viewer-Setup-0.3.1.exe",
                                  "browser_download_url": "https://example.com/ProEXR-Viewer-Setup-0.3.1.exe"}])
    release = update.release_from_json(data)
    assert release.installer_url is None
    with pytest.raises(UpdateError):
        update.download_installer(release)


def test_download_saves_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "_get", lambda url: b"MZ installer")
    path = update.download_installer(update.release_from_json(RELEASE), tmp_path)
    assert path.name == "ProEXR-Viewer-Setup-0.3.1.exe" and path.read_bytes() == b"MZ installer"


def test_network_failure_becomes_update_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")
    monkeypatch.setattr(update.urllib.request, "urlopen", fail)
    with pytest.raises(UpdateError):
        update.fetch_latest_release()

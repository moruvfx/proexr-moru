import pytest

from proexr.errors import PlaylistError
from proexr.media.playlist import load_playlist, save_playlist


def test_round_trip_keeps_order_and_relative_paths(tmp_path):
    inside = tmp_path / "shots" / "a.1001.exr"
    outside = tmp_path.parent / "elsewhere.mov"
    playlist = tmp_path / "review.proexr.json"
    save_playlist(playlist, [inside, outside])
    assert "shots/a.1001.exr" in playlist.read_text()
    assert load_playlist(playlist) == [inside.resolve(), outside.resolve()]


def test_moving_the_folder_keeps_relative_entries_working(tmp_path):
    (tmp_path / "old").mkdir()
    save_playlist(tmp_path / "old" / "p.json", [tmp_path / "old" / "clip.mov"])
    (tmp_path / "old").rename(tmp_path / "new")
    assert load_playlist(tmp_path / "new" / "p.json") == [(tmp_path / "new" / "clip.mov").resolve()]


def test_broken_file_raises_playlist_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(PlaylistError):
        load_playlist(bad)

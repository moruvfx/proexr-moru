import time

import numpy as np

from proexr.media.audio import CHANNELS, AudioTrack
from proexr.playback.audio_player import AudioPlayer


class FakeOutput:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.stopped = False

    def pull(self, frames: int) -> np.ndarray:
        out = np.ones((frames, CHANNELS), np.int16)
        self.callback(out, frames, None, None)
        return out

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        pass


def test_player_feeds_decoded_samples_to_output(audio_file):
    outputs = []
    player = AudioPlayer(lambda callback: outputs.append(FakeOutput(callback)) or outputs[-1])
    track = AudioTrack(audio_file)
    assert player.play(track, 0.5)
    time.sleep(0.2)
    pulled = np.concatenate([outputs[0].pull(1024) for _ in range(20)])
    assert np.abs(pulled[:, 0]).max() > 10000
    player.stop()
    assert outputs[0].stopped and not player.is_playing
    track.close()


def test_underrun_outputs_silence():
    player = AudioPlayer(lambda callback: None)
    out = np.ones((256, CHANNELS), np.int16)
    player._fill(out, 256, None, None)
    assert not out.any()


def test_missing_audio_device_reports_failure(audio_file):
    player = AudioPlayer(lambda callback: None)
    track = AudioTrack(audio_file)
    assert not player.play(track, 0.0)
    assert not player.is_playing
    track.close()

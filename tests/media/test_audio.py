import numpy as np
import pytest

from proexr.errors import MediaReadError
from proexr.media.audio import SAMPLE_RATE, AudioTrack, has_audio


def collect(track: AudioTrack, seconds: float) -> np.ndarray:
    return np.concatenate(list(track.samples_from(seconds)))


def test_decodes_to_stereo_int16_at_output_rate(audio_file):
    track = AudioTrack(audio_file)
    samples = collect(track, 0.0)
    track.close()
    assert samples.dtype == np.int16 and samples.shape[1] == 2
    assert abs(len(samples) - 2 * SAMPLE_RATE) < SAMPLE_RATE // 10
    assert np.abs(samples[SAMPLE_RATE // 2:, 0]).max() > 10000
    assert np.abs(samples[SAMPLE_RATE // 2:, 1]).max() < 500


def test_starting_later_skips_earlier_samples(audio_file):
    track = AudioTrack(audio_file)
    remaining = collect(track, 1.5)
    track.close()
    assert abs(len(remaining) - SAMPLE_RATE // 2) < SAMPLE_RATE // 20


def test_silent_video_has_no_audio(video_file):
    assert not has_audio(video_file)
    with pytest.raises(MediaReadError):
        AudioTrack(video_file)

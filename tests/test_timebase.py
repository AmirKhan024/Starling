"""Tests for starling_net.timebase.MediaClock (D-03 fix)."""

from __future__ import annotations

from starling_net.timebase import MediaClock


def test_media_clock_from_video_matches_stream_epoch_plus_idx_over_fps(synthetic_video):
    stream_epoch = 1_700_000_000.0
    clock = MediaClock.from_video(synthetic_video, stream_epoch=stream_epoch)

    assert clock.fps == 25
    for idx in (0, 1, 100):
        expected = stream_epoch + idx / clock.fps
        assert clock.t_media(idx) == expected


def test_two_clocks_with_same_stream_epoch_agree_for_same_frame_index(synthetic_video):
    stream_epoch = 42.0
    clock_a = MediaClock.from_video(synthetic_video, stream_epoch=stream_epoch)
    clock_b = MediaClock.from_video(synthetic_video, stream_epoch=stream_epoch)

    for idx in (0, 10, 50):
        assert clock_a.t_media(idx) == clock_b.t_media(idx)


def test_is_approximate_is_false_for_file_sources(synthetic_video):
    clock = MediaClock.from_video(synthetic_video, stream_epoch=0.0)
    assert clock.is_approximate is False


def test_rtsp_clock_is_marked_approximate():
    clock = MediaClock.from_rtsp("rtsp://example.invalid/stream", stream_epoch=0.0)
    assert clock.is_approximate is True

"""Tests for starling_perception.source.PacedSource (D-05 fix)."""

from __future__ import annotations

import time

import pytest

from starling_net.timebase import MediaClock
from starling_perception.source import PacedSource


def test_non_realtime_iterates_fully_with_exact_frame_period(synthetic_video):
    clock = MediaClock.from_video(synthetic_video, stream_epoch=0.0)
    source = PacedSource(synthetic_video, clock, realtime=False)

    frames = list(source)
    assert len(frames) > 100  # synthetic_video fixture is a 5s @ 25fps clip

    for (_, idx, t_media), (_, next_idx, next_t_media) in zip(frames, frames[1:]):
        assert next_idx == idx + 1
        assert next_t_media - t_media == pytest.approx(1.0 / clock.fps)

    assert source.frames_read == len(frames)
    assert source.dropped == 0


def test_realtime_speed_10_finishes_5s_clip_in_under_1_5s(synthetic_video):
    clock = MediaClock.from_video(synthetic_video, stream_epoch=0.0)
    source = PacedSource(synthetic_video, clock, speed=10.0, realtime=True)

    start = time.monotonic()
    frames = list(source)
    elapsed = time.monotonic() - start

    assert len(frames) > 100
    assert elapsed < 1.5


def test_dropped_increments_when_consumer_is_slow(synthetic_video):
    clock = MediaClock.from_video(synthetic_video, stream_epoch=0.0)
    source = PacedSource(synthetic_video, clock, speed=1.0, realtime=True)

    count = 0
    for _frame, _idx, _t_media in source:
        count += 1
        # Simulate a slow consumer for the first few frames only, so the
        # test doesn't have to wait out the whole 5s clip in real time.
        if count <= 3:
            time.sleep(0.2)
        if count > 10:
            break

    assert source.dropped > 0

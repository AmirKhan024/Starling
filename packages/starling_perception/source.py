"""starling_perception/source.py
----------------------------------
Concurrent, paced playback (D-05, STARLING_BUILD_STATE.md §2): V1's
`run_files` consumed camera 0 fully before starting camera 1, so no
cross-camera handoff, coverage gap, or identity conflict could ever occur
in offline replay. `PacedSource` fixes that for the new node path (it is
NOT wired into `apps/baseline.py`, which stays sequential by design — it
is the frozen control condition) by emitting frames at the wall-clock
instant that corresponds to their media time. Two independent node
processes replaying two different videos with the same `stream_epoch`
therefore process the same media instant at the same wall-clock instant,
which is what makes a cross-camera event real rather than an artifact of
processing order.
"""

from __future__ import annotations

import time

import cv2

from starling_net.timebase import MediaClock


class PacedSource:
    """Iterates `(frame, frame_idx, t_media)` from a video file or webcam
    index, either as fast as possible (`realtime=False`) or paced to real
    time (`realtime=True`).

    When paced and the consumer falls behind (each `next()` call takes
    longer than one frame period because processing between yields is
    slow), frames are DROPPED rather than burst-delivered to catch up —
    bursting would defeat the entire point of pacing. `.dropped` counts
    this; a later work package treats a high drop rate as a detector-health
    signal.
    """

    def __init__(
        self,
        path_or_index,
        media_clock: MediaClock,
        speed: float = 1.0,
        realtime: bool = True,
    ) -> None:
        self.path_or_index = path_or_index
        self.media_clock = media_clock
        self.speed = speed
        self.realtime = realtime
        self.fps = media_clock.fps

        self.frames_read = 0
        self.dropped = 0
        self.behind_s = 0.0

    def __iter__(self):
        source = (
            int(self.path_or_index)
            if str(self.path_or_index).isdigit()
            else str(self.path_or_index)
        )
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {self.path_or_index}")

        start_wall = time.monotonic()
        frame_idx = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                t_media = self.media_clock.t_media(frame_idx)

                if self.realtime:
                    target_elapsed = (
                        t_media - self.media_clock.stream_epoch
                    ) / self.speed
                    now_elapsed = time.monotonic() - start_wall
                    self.behind_s = now_elapsed - target_elapsed

                    if self.behind_s > (1.0 / self.fps):
                        # More than one frame period behind schedule: the
                        # consumer is slow. Drop this frame instead of
                        # bursting it out immediately — bursting would mean
                        # the consumer never actually sees real-time pacing.
                        self.dropped += 1
                        frame_idx += 1
                        continue

                    if self.behind_s < 0:
                        time.sleep(-self.behind_s)

                self.frames_read += 1
                yield frame, frame_idx, t_media
                frame_idx += 1
        finally:
            cap.release()

"""starling_net/timebase.py
---------------------------
Media time, not processing time (D-03, STARLING_BUILD_STATE.md §2).

Every sighting/claim in the identity path must be stamped with the time the
frame actually depicts, not the wall-clock instant a busy or backlogged
node happened to get around to processing it. In V1's `run_files`, cameras
were processed sequentially, so camera 1's "timestamps" were all later than
camera 0's regardless of what actually happened when — making transit time,
reachability windows, partition intervals, and the lost threshold all
uncomputable.

`MediaClock.t_media(frame_idx)` is the single source of the frame-index ->
time mapping. It is not always exact — a node must know when its own
timestamps are untrustworthy, hence `is_approximate`.

All nodes replaying the same recorded scenario MUST share the same
`stream_epoch` (unix seconds), or their media times sit on different
timelines and nothing cross-camera is meaningful. `NodeConfig.stream_epoch`
carries this; a scenario runner (later work package) is what actually
injects one shared value into every node's config for a given run.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2

_DEFAULT_FPS = 25.0


@dataclass
class MediaClock:
    fps: float
    stream_epoch: float
    is_approximate: bool = False

    @classmethod
    def from_video(cls, path, stream_epoch: float) -> "MediaClock":
        """Build a MediaClock from a video file's own fps metadata."""
        cap = cv2.VideoCapture(str(path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
        finally:
            cap.release()

        if fps and fps > 0:
            return cls(fps=fps, stream_epoch=stream_epoch, is_approximate=False)

        # No usable fps metadata: fall back to a default and say so.
        return cls(fps=_DEFAULT_FPS, stream_epoch=stream_epoch, is_approximate=True)

    @classmethod
    def from_rtsp(cls, url, stream_epoch: float) -> "MediaClock":
        """Build a MediaClock for a live RTSP source.

        RTP timestamps are the correct source of truth for a live stream,
        but reading them requires a lower-level RTP client than OpenCV's
        VideoCapture exposes, which is out of scope here (no live camera is
        available to develop this against). This falls back to
        arrival-time pacing with `is_approximate=True`, exactly as the
        module's own rule requires: a node must know when its own
        timestamps are untrustworthy rather than silently pretending they
        are exact.
        """
        return cls(fps=_DEFAULT_FPS, stream_epoch=stream_epoch, is_approximate=True)

    def t_media(self, frame_idx: int) -> float:
        return self.stream_epoch + frame_idx / self.fps

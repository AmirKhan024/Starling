"""starling_world/frames.py
---------------------------
The camera -> node link: one ZMQ PUB socket in the world server, one topic
per camera. A node subscribes to its OWN camera's topic only, exactly as a
physical camera is wired to one node. Each message is

    [topic, header JSON, JPEG bytes]
    header = {"node_id", "frame_idx", "t_media", "width", "height"}

This is NOT gossip and never leaves the machine the camera is attached to:
raw frames go camera -> its own node and nowhere else (CLAUDE.md rule 3).
The ground-truth topic for the dashboard's comparison overlay shares the
socket (`[topic, JSON]`, starling_sim.messages.GROUND_TRUTH_TOPIC).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import zmq

_ctx = zmq.Context.instance()


def camera_topic(node_id: int) -> bytes:
    # The trailing "|" stops ZMQ's prefix matching from delivering cam:10's
    # frames to a node subscribed to cam:1.
    return f"cam:{node_id}|".encode("ascii")


@dataclass
class Frame:
    node_id: int
    frame_idx: int
    t_media: float
    jpeg: bytes
    width: int
    height: int


class FramePublisher:
    def __init__(self, bind_endpoint: str) -> None:
        self._sock = _ctx.socket(zmq.PUB)
        self._sock.setsockopt(zmq.SNDHWM, 64)
        self._sock.bind(bind_endpoint)
        self.endpoint = self._sock.getsockopt_string(zmq.LAST_ENDPOINT)

    def publish_frame(self, frame: Frame) -> None:
        header = {
            "node_id": frame.node_id,
            "frame_idx": frame.frame_idx,
            "t_media": frame.t_media,
            "width": frame.width,
            "height": frame.height,
        }
        self._sock.send_multipart(
            [camera_topic(frame.node_id), json.dumps(header).encode("utf-8"), frame.jpeg]
        )

    def publish_json(self, topic: str, payload: dict[str, Any]) -> None:
        self._sock.send_multipart([topic.encode("utf-8"), json.dumps(payload).encode("utf-8")])

    def close(self) -> None:
        self._sock.close(linger=0)


class FrameSubscriber:
    """A node's end of its camera link."""

    def __init__(self, connect_endpoint: str, node_id: int) -> None:
        self.node_id = node_id
        self._sock = _ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.RCVHWM, 8)
        self._sock.connect(connect_endpoint)
        self._sock.setsockopt(zmq.SUBSCRIBE, camera_topic(node_id))
        self.skipped = 0  # frames discarded because a newer one was already waiting

    def recv_latest(self, timeout_ms: int = 1000) -> Optional[Frame]:
        """The newest frame available, waiting up to `timeout_ms` for one.
        Older queued frames are discarded (counted in `skipped`): a camera
        node that falls behind processes the present, not a growing backlog."""
        if self._sock.poll(timeout_ms, zmq.POLLIN) == 0:
            return None
        parts = self._sock.recv_multipart()
        while self._sock.poll(0, zmq.POLLIN):
            parts = self._sock.recv_multipart()
            self.skipped += 1
        _topic, header_raw, jpeg = parts
        h = json.loads(header_raw.decode("utf-8"))
        return Frame(
            node_id=int(h["node_id"]),
            frame_idx=int(h["frame_idx"]),
            t_media=float(h["t_media"]),
            jpeg=jpeg,
            width=int(h["width"]),
            height=int(h["height"]),
        )

    def close(self) -> None:
        self._sock.close(linger=0)

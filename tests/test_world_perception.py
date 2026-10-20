"""Torch-free parts of the world-camera perception: the appearance
signature, the employee registry, and the camera -> node frame link."""

from __future__ import annotations

import time

import cv2
import numpy as np
from starling_perception.appearance import appearance_descriptor, crop_quality, descriptor_dim
from starling_perception.registry import Employee, EmployeeRegistry
from starling_world.frames import Frame, FramePublisher, FrameSubscriber


def _person(top: tuple, bottom: tuple, bg=(130, 130, 128), h=120, w=50, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), bg, dtype=np.uint8)
    img[: h // 2, w // 4 : 3 * w // 4] = top
    img[h // 2 :, w // 4 : 3 * w // 4] = bottom
    noise = rng.integers(-12, 12, size=img.shape)
    return np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)


ORANGE, BLUE, GREEN, KHAKI = (19, 106, 255), (127, 79, 47), (74, 166, 31), (91, 139, 166)


def test_descriptor_is_unit_norm_with_the_documented_dimension():
    d = appearance_descriptor(_person(ORANGE, BLUE))
    assert d.shape == (descriptor_dim(),) == (96,)
    assert abs(np.linalg.norm(d) - 1.0) < 1e-5


def test_same_clothing_is_similar_and_different_clothing_is_not():
    a = appearance_descriptor(_person(ORANGE, BLUE, seed=1))
    b = appearance_descriptor(cv2.resize(_person(ORANGE, BLUE, seed=2), (40, 90)))
    c = appearance_descriptor(_person(GREEN, KHAKI, seed=3))
    assert float(a @ b) > 0.9
    assert float(a @ c) < 0.6


def test_crop_quality_penalises_small_and_cut_off_crops():
    assert crop_quality((100, 100, 140, 190), (720, 1280, 3), ref_height_px=72) == 1.0
    assert crop_quality((100, 100, 120, 130), (720, 1280, 3), ref_height_px=72) < 0.5
    assert crop_quality((0, 100, 40, 190), (720, 1280, 3), ref_height_px=72) < 1.0


def _registry() -> EmployeeRegistry:
    def gal(top, bottom):
        return np.stack([appearance_descriptor(_person(top, bottom, seed=s)) for s in range(4)])

    return EmployeeRegistry(
        [
            Employee("EMP-1", "Ann", "picker", gal(ORANGE, BLUE)),
            Employee("EMP-2", "Ben", "loader", gal(GREEN, KHAKI)),
        ]
    )


def test_registry_verifies_the_right_employee():
    reg = _registry()
    probe = [appearance_descriptor(_person(GREEN, KHAKI, seed=s)) for s in (10, 11, 12)]
    v = reg.verify(probe, threshold=0.8, margin=0.06)
    assert v.verified and v.employee_id == "EMP-2" and v.score > v.second_score


def test_registry_refuses_a_stranger():
    reg = _registry()
    probe = [
        appearance_descriptor(_person((200, 30, 200), (240, 240, 240), seed=s))
        for s in (20, 21, 22)
    ]
    v = reg.verify(probe, threshold=0.8, margin=0.06)
    assert not v.verified and v.employee_id is None


def test_registry_round_trips(tmp_path):
    reg = _registry()
    reg.save(tmp_path / "r.json")
    back = EmployeeRegistry.load(tmp_path / "r.json")
    assert [e.id for e in back.employees] == ["EMP-1", "EMP-2"]
    assert np.allclose(back.employees[0].gallery, reg.employees[0].gallery, atol=1e-4)


def test_a_node_receives_only_its_own_camera_and_only_the_newest_frame():
    pub = FramePublisher("tcp://127.0.0.1:*")
    sub1 = FrameSubscriber(pub.endpoint, 1)
    time.sleep(0.4)  # ZMQ slow joiner
    for idx in range(1, 4):
        pub.publish_frame(Frame(1, idx, idx * 0.25, b"jpeg-%d" % idx, 4, 3))
        pub.publish_frame(Frame(10, idx, idx * 0.25, b"not-mine", 4, 3))
    time.sleep(0.3)
    fr = sub1.recv_latest(timeout_ms=1000)
    assert fr is not None and fr.node_id == 1 and fr.frame_idx == 3 and fr.jpeg == b"jpeg-3"
    assert sub1.skipped == 2
    assert sub1.recv_latest(timeout_ms=200) is None
    sub1.close()
    pub.close()

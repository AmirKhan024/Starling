"""scripts/calibrate_world_appearance.py
----------------------------------------
Measures the live 3D world's perception on held-out renders, so every
threshold the world-camera nodes use is chosen from data rather than
guessed (the same discipline as scripts/calibrate_match_threshold.py):

  * person-detection recall per camera, inside each camera's own zone;
  * floor localisation error of the foot point through the calibrated
    homography (vs the true position);
  * cross-camera appearance separability: ROC/AUC of the resolver's score
    (cosine similarity x crop quality) for same-person vs different-person
    pairs seen by DIFFERENT cameras, and the Youden-J threshold
    -> the world nodes' `match.sim_threshold`;
  * gate verification against the enrolled registry: genuine vs impostor
    scores on fresh gate renders -> FAR / FRR at the configured threshold;
  * recognition of enrolled employees by EVERY camera (not just the gate),
    on groups of signatures from that camera -> false/correct recognition
    rates at the stricter recognition threshold.

Writes docs/results_world_perception.md and docs/results_world_perception.json.

Usage:
    python scripts/calibrate_world_appearance.py [--scenes 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "packages"))

import numpy as np  # noqa: E402
from starling_geometry.calibration import CameraCalibration  # noqa: E402
from starling_node.config import WorldNodeConfig  # noqa: E402
from starling_perception.registry import EmployeeRegistry  # noqa: E402
from starling_perception.world_pipeline import half  # noqa: E402
from starling_world.config import load_world_config  # noqa: E402
from starling_world.layout import compute_camera_zones  # noqa: E402

from apps.world.capture import WorldCapture, labelled_samples  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
from enroll_employees import enrollment_poses  # noqa: E402

ACTIONS = ["idle", "pick", "scan", "work"]


def random_scenes(cfg, zones, per_camera: int, rng) -> list[tuple[int, list[dict]]]:
    cell = cfg.navmesh_cell_m
    out = []
    for node, mask in sorted(zones.items()):
        js, iss = np.nonzero(mask)
        for _ in range(per_camera):
            used, ppl = [], []
            for e in cfg.employees:
                for _ in range(80):
                    k = int(rng.integers(len(js)))
                    x, y = (iss[k] + 0.5) * cell, (js[k] + 0.5) * cell
                    if all(np.hypot(x - a, y - b) > 2.2 for a, b in used):
                        used.append((x, y))
                        walking = bool(rng.random() < 0.5)
                        ppl.append(
                            {
                                "id": e.id,
                                "x": float(x),
                                "y": float(y),
                                "heading": float(rng.uniform(0, 2 * np.pi)),
                                "speed": 1.2 if walking else 0.0,
                                "carry": bool(rng.random() < 0.25),
                                "action": "walk"
                                if walking
                                else ACTIONS[int(rng.integers(len(ACTIONS)))],
                                "phase_steps": int(rng.integers(0, 14)),
                            }
                        )
                        break
            out.append((node, ppl))
    return out


def roc(pos: np.ndarray, neg: np.ndarray) -> dict:
    thr = np.unique(np.concatenate([pos, neg]))
    tpr = np.array([(pos >= t).mean() for t in thr])
    fpr = np.array([(neg >= t).mean() for t in thr])
    # AUC as the Mann-Whitney probability that a same-person pair outscores a different-person one
    auc = float(
        ((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())
    )
    j = int(np.argmax(tpr - fpr))
    return {
        "auc": round(auc, 4),
        "youden_threshold": round(float(thr[j]), 4),
        "tpr_at_youden": round(float(tpr[j]), 4),
        "fpr_at_youden": round(float(fpr[j]), 4),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=REPO / "configs" / "world" / "warehouse.yaml")
    ap.add_argument(
        "--registry", type=Path, default=REPO / "data" / "world" / "employee_registry.json"
    )
    ap.add_argument("--scenes", type=int, default=10, help="random scenes per camera")
    ap.add_argument("--detector", default="yolo11s.pt")
    ap.add_argument("--seed", type=int, default=99)
    args = ap.parse_args(argv)

    cfg = load_world_config(args.config)
    wcfg = WorldNodeConfig()
    zones, _free, _px = compute_camera_zones(cfg)
    calibs = {
        n: CameraCalibration.from_yaml(REPO / "configs" / "calib" / "world" / f"node-{n:02d}.yaml")
        for n in zones
    }
    reg = EmployeeRegistry.load(args.registry)
    from ultralytics import YOLO

    model = YOLO(args.detector)
    rng = np.random.default_rng(args.seed)
    scenes = random_scenes(cfg, zones, args.scenes, rng)
    samples, recall = [], {n: [0, 0] for n in zones}
    gate = cfg.entrance.gate
    genuine, impostor, decisions = [], [], []
    with WorldCapture(cfg) as cap:
        bgs = {n: half(cap.render(n, [])).astype(np.float32) for n in zones}
        for node, ppl in scenes:
            got = labelled_samples(
                cap,
                model,
                node,
                ppl,
                bgs[node],
                calibs[node],
                wcfg.fg_threshold,
                conf=0.25,
                imgsz=wcfg.imgsz,
            )
            in_zone = [
                p
                for p in ppl
                if zones[node][int(p["y"] / cfg.navmesh_cell_m), int(p["x"] / cfg.navmesh_cell_m)]
            ]
            hit_ids = {s["id"] for s in got}
            recall[node][0] += sum(1 for p in in_zone if p["id"] in hit_ids)
            recall[node][1] += len(in_zone)
            samples += [s for s in got if s["id"] in {p["id"] for p in in_zone}]
        # fresh gate renders (a different seed from enrollment), three frames per pass
        for i, e in enumerate(cfg.employees):
            poses = enrollment_poses(gate.x, gate.y, 12, args.seed * 7 + i)
            descs = []
            for pose in poses:
                got = labelled_samples(
                    cap,
                    model,
                    gate.node_id,
                    [{"id": e.id, **pose}],
                    bgs[gate.node_id],
                    calibs[gate.node_id],
                    wcfg.fg_threshold,
                    conf=0.2,
                    imgsz=wcfg.imgsz,
                )
                descs += [g["desc"] for g in got]
            for k in range(0, len(descs) - wcfg.gate_min_frames + 1, wcfg.gate_min_frames):
                group = descs[k : k + wcfg.gate_min_frames]
                ranked = dict(reg.scores(group))
                genuine.append(ranked[e.id])
                impostor.append(max(s for i2, s in ranked.items() if i2 != e.id))
                v = reg.verify(group, wcfg.verify_threshold, wcfg.verify_margin)
                decisions.append((e.id, v.employee_id))

    # cross-camera appearance pairs, scored like the resolver (similarity x quality)
    pos, neg = [], []
    for a in range(len(samples)):
        for b in range(a + 1, len(samples)):
            sa, sb = samples[a], samples[b]
            if sa["node_id"] == sb["node_id"]:
                continue
            s = float(np.dot(sa["desc"], sb["desc"])) * sb["quality"]
            (pos if sa["id"] == sb["id"] else neg).append(s)
    pos, neg = np.array(pos), np.array(neg)
    app = roc(pos, neg)
    # recognition by every camera: groups of `recognise_min_frames` signatures
    # of one employee from one camera (different poses), vs the registry
    rec_genuine, rec_impostor, rec_decisions = [], [], []
    k = wcfg.recognise_min_frames
    for node in sorted(zones):
        for e in cfg.employees:
            mine = [s_["desc"] for s_ in samples if s_["node_id"] == node and s_["id"] == e.id]
            for g in range(0, len(mine) - k + 1, k):
                group = mine[g : g + k]
                ranked = dict(reg.scores(group))
                rec_genuine.append(ranked[e.id])
                rec_impostor.append(max(v for i2, v in ranked.items() if i2 != e.id))
                v = reg.verify(group, wcfg.recognise_threshold, wcfg.recognise_margin)
                rec_decisions.append((e.id, v.employee_id))
    errs = np.array([s["err_m"] for s in samples])
    correct = sum(1 for want, got in decisions if got == want)
    wrong = sum(1 for want, got in decisions if got is not None and got != want)
    result = {
        "detector": args.detector,
        "detection_recall_in_zone": {
            str(n): round(h / t, 3) if t else None for n, (h, t) in recall.items()
        },
        "detection_recall_overall": round(
            sum(h for h, _ in recall.values()) / max(1, sum(t for _, t in recall.values())), 3
        ),
        "localisation_error_m": {
            "median": round(float(np.median(errs)), 3),
            "p90": round(float(np.percentile(errs, 90)), 3),
            "n": int(len(errs)),
        },
        "appearance_cross_camera": {
            **app,
            "n_same": int(len(pos)),
            "n_diff": int(len(neg)),
            "same_median": round(float(np.median(pos)), 3),
            "diff_median": round(float(np.median(neg)), 3),
        },
        "gate_verification": {
            "threshold": wcfg.verify_threshold,
            "margin": wcfg.verify_margin,
            "frames_per_decision": wcfg.gate_min_frames,
            "genuine_median": round(float(np.median(genuine)), 3),
            "genuine_p10": round(float(np.percentile(genuine, 10)), 3),
            "impostor_max": round(float(np.max(impostor)), 3),
            "impostor_p90": round(float(np.percentile(impostor, 90)), 3),
            "decisions": len(decisions),
            "correct_accepts": correct,
            "false_accepts": wrong,
            "rejected": len(decisions) - correct - wrong,
        },
        "recognition_all_cameras": {
            "threshold": wcfg.recognise_threshold,
            "margin": wcfg.recognise_margin,
            "frames_per_decision": k,
            "genuine_median": round(float(np.median(rec_genuine)), 3) if rec_genuine else None,
            "genuine_p10": round(float(np.percentile(rec_genuine, 10)), 3) if rec_genuine else None,
            "impostor_max": round(float(np.max(rec_impostor)), 3) if rec_impostor else None,
            "decisions": len(rec_decisions),
            "correct": sum(1 for want, got in rec_decisions if got == want),
            "false": sum(1 for want, got in rec_decisions if got is not None and got != want),
            "abstained": sum(1 for _, got in rec_decisions if got is None),
        },
    }
    rec = result["recognition_all_cameras"]
    (REPO / "docs" / "results_world_perception.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8"
    )
    md = f"""# Live 3D world — measured perception

Generated by `scripts/calibrate_world_appearance.py` on held-out renders of the
live world (random poses in every camera's zone, and fresh passes through the
entrance gate — never the enrollment views). Detector: `{args.detector}`.

| Measure | Value |
|---|---|
| Person detection recall, inside each camera's own zone (single frame, conf ≥ 0.25) | {result["detection_recall_overall"]:.0%} overall; per camera {", ".join(f"{k}: {v:.0%}" for k, v in result["detection_recall_in_zone"].items() if v is not None)} |
| Floor localisation error (foot point → calibrated homography) | median {result["localisation_error_m"]["median"]} m, 90th pct {result["localisation_error_m"]["p90"]} m (n = {result["localisation_error_m"]["n"]}) |
| Cross-camera appearance, same vs different person (score = similarity × quality) | AUC {app["auc"]}; medians {result["appearance_cross_camera"]["same_median"]} vs {result["appearance_cross_camera"]["diff_median"]} |
| → resolver match threshold (Youden J) | **{app["youden_threshold"]}** (TPR {app["tpr_at_youden"]:.0%}, FPR {app["fpr_at_youden"]:.0%}) |
| Gate verification (registry, {wcfg.gate_min_frames} frames per decision, threshold {wcfg.verify_threshold}, margin {wcfg.verify_margin}) | {correct}/{len(decisions)} correct accepts, **{wrong} false accepts**, {len(decisions) - correct - wrong} rejected (the person simply keeps being checked) |
| Recognition by every camera ({k} frames, threshold {wcfg.recognise_threshold}, margin {wcfg.recognise_margin}) | {rec["correct"]}/{rec["decisions"]} correct, **{rec["false"]} false**, {rec["abstained"]} abstained; genuine median {rec["genuine_median"]}, best impostor {rec["impostor_max"]} |
| Gate scores | genuine median {result["gate_verification"]["genuine_median"]} (10th pct {result["gate_verification"]["genuine_p10"]}); best impostor {result["gate_verification"]["impostor_max"]} |

Single-frame recall understates what a node achieves: ByteTrack carries a
person across frames where the detector's confidence dips, and a claim is
made every frame the track is alive.

The appearance signature is a hand-crafted clothing-colour descriptor
(`starling_perception.appearance`), chosen because the four employees'
uniforms differ by colour; it is not a general re-identification model.
"""  # noqa: E501 (generated Markdown)
    (REPO / "docs" / "results_world_perception.md").write_text(md, encoding="utf-8")
    print(json.dumps(result, indent=1))  # CLI banner
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

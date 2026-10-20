"""scripts/enroll_employees.py
------------------------------
Employee onboarding for the live 3D world: the "badge photo" step.

Each employee in configs/world/warehouse.yaml is rendered standing at the
entrance gate, seen through the entrance camera, in several orientations
and poses. Each image goes through the nodes' own perception (YOLO person
detector, the stripe-colour appearance signature on the foreground
pixels) and the signatures become that employee's gallery in the registry
file every node is deployed with (data/world/employee_registry.json).

Nodes never see these images — only the resulting signatures, exactly as
an access-control system distributes enrolled templates.

Usage:
    python scripts/enroll_employees.py [--views 12] [--out data/world/employee_registry.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "packages"))

import numpy as np  # noqa: E402
from starling_geometry.calibration import CameraCalibration  # noqa: E402
from starling_node.config import WorldNodeConfig  # noqa: E402
from starling_perception.appearance import descriptor_dim  # noqa: E402
from starling_perception.registry import Employee, EmployeeRegistry  # noqa: E402
from starling_perception.world_pipeline import half  # noqa: E402
from starling_world.config import load_world_config  # noqa: E402

from apps.world.capture import WorldCapture, labelled_samples  # noqa: E402

DEFAULT_OUT = REPO / "data" / "world" / "employee_registry.json"


def enrollment_poses(gate_x: float, gate_y: float, n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    poses = []
    for k in range(n):
        heading = 2 * math.pi * k / n + float(rng.uniform(-0.2, 0.2))
        walking = k % 3 == 1
        poses.append(
            {
                "x": gate_x + float(rng.uniform(-0.5, 0.5)),
                "y": gate_y + float(rng.uniform(-0.5, 0.5)),
                "heading": heading,
                "speed": 1.2 if walking else 0.0,
                "action": "walk" if walking else "idle",
                "phase_steps": int(rng.integers(0, 12)),
            }
        )
    return poses


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=REPO / "configs" / "world" / "warehouse.yaml")
    ap.add_argument("--views", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--software-gl", action="store_true")
    ap.add_argument(
        "--detector", default="yolo11s.pt", help="must match the nodes' perception.yolo_model"
    )
    args = ap.parse_args(argv)

    cfg = load_world_config(args.config)
    gate = cfg.entrance.gate
    node = gate.node_id
    calib = CameraCalibration.from_yaml(
        REPO / "configs" / "calib" / "world" / f"node-{node:02d}.yaml"
    )
    wcfg = WorldNodeConfig()
    from ultralytics import YOLO

    model = YOLO(args.detector)
    employees = []
    with WorldCapture(cfg, gpu=not args.software_gl) as cap:
        bg = half(cap.render(node, [])).astype(np.float32)
        for i, e in enumerate(cfg.employees):
            gallery = []
            for pose in enrollment_poses(gate.x, gate.y, args.views, args.seed + i):
                got = labelled_samples(
                    cap,
                    model,
                    node,
                    [{"id": e.id, **pose}],
                    bg,
                    calib,
                    wcfg.fg_threshold,
                    conf=0.2,
                    imgsz=wcfg.imgsz,
                )
                if got:
                    gallery.append(got[0]["desc"])
            if len(gallery) < max(3, args.views // 2):
                print(
                    f"ENROLLMENT FAILED for {e.id}: only {len(gallery)} usable views",
                    file=sys.stderr,
                )  # CLI banner
                return 1
            employees.append(Employee(id=e.id, name=e.name, role=e.role, gallery=np.stack(gallery)))
            print(f"enrolled {e.id} {e.name}: {len(gallery)} views")  # CLI banner

    reg = EmployeeRegistry(
        employees,
        {
            "company": cfg.company.name,
            "site": cfg.company.site,
            "descriptor": {"kind": "stripe-colour", "dim": descriptor_dim()},
            "enrolled_at_camera": node,
            "enrolled_on": dt.date.today().isoformat(),
            "generator": "scripts/enroll_employees.py",
        },
    )
    reg.save(args.out)
    print(
        f"wrote {args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out}"
    )  # CLI banner

    # Sanity: every employee must be closest to their own gallery.
    for e in employees:
        held_out = [e.gallery[k] for k in range(0, len(e.gallery), 2)]
        ranked = reg.scores(held_out)
        print(
            f"  {e.id}: self {dict(ranked)[e.id]:.3f}, best other "
            f"{max(s for i2, s in ranked if i2 != e.id):.3f}"
        )  # CLI banner
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

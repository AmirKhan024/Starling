"""scripts/render_reachability.py
-----------------------------------
Renders reachable-set visualisations from the demo navmesh at 5s/15s/60s
horizons, for the report and the dashboard.

Usage
-----
    python scripts/render_reachability.py
"""

from __future__ import annotations

from pathlib import Path

from starling_geometry.navmesh import NavMesh
from starling_geometry.reachability import ReachabilityModel

DEMO_SITE = Path("data/floorplan/demo_site.geojson")
OUT_DIR = Path("docs")
# A point inside zone A, just past boundary 1 (the gap's west exit) — the
# scenario every later demo lives in: a person about to enter the dead zone.
FIXED_ORIGIN = (7.5, 2.0)
DURATIONS_S = [5, 15, 60]


def main() -> None:
    mesh = NavMesh.from_geojson(DEMO_SITE, cell_size_m=0.25)
    model = ReachabilityModel(mesh, v_max_m_s=1.6)
    model.precompute([FIXED_ORIGIN])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for dt in DURATIONS_S:
        mask = model.reachable_set(FIXED_ORIGIN, dt_s=float(dt))
        img = mesh.render(mask=mask)
        out_path = OUT_DIR / f"reachability_{dt}s.png"
        img.save(out_path)
        print(f"Wrote {out_path}  (reachable area: {mesh.area_m2(mask):.1f} sq m)")


if __name__ == "__main__":
    main()

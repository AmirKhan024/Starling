"""scripts/capture_explainer.py
--------------------------------
Drive the live demo and screenshot each panel of the TECHNICAL view at the
moment that panel is actually doing something, then record the real numbers on
screen alongside each shot.

This exists to be studied, not to judge: `scripts/review_demo.py` decides
whether the eleven review moments PASS, while this one produces the raw
material for `review/explainer.html` — a walkthrough of what every part of the
dashboard means. It writes:

    review/explainer_shots/*.png     one image per panel per scene
    review/explainer_shots.json      manifest: slug, caption, and the live
                                     /api/state values at the instant of capture

Run it, then build the document:

    python scripts/capture_explainer.py
    python scripts/build_explainer.py

The demo runs in presenter mode (no automatic episodes) so each scene is
triggered deliberately and the screenshots are reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from run_demo import DemoLauncher  # noqa: E402

OUT_DIR = REPO / "review" / "explainer_shots"
MANIFEST = REPO / "review" / "explainer_shots.json"

# Panels of the technical view. `:has()` keeps these readable rather than
# depending on nth-child positions that move whenever a section is added.
SEL = {
    "header": "header",
    "map": "section:has(> svg#map)",
    "region_summary": "#region-summary",
    "region_cards": "#region-cards",
    "central": '[data-testid="central-panel"]',
    "identities": 'section:has([data-testid="identity-table"])',
    "forks": 'section:has([data-testid="forks-panel"])',
    "demo_script": '[data-testid="demo-script"]',
    "controls": 'section:has([data-testid="btn-partition"])',
    "nodes": 'section:has(#node-cards)',
    "query": 'section:has([data-testid="query-result"])',
    "events": 'section:has([data-testid="event-log"])',
}


class Capture:
    def __init__(self, port: int) -> None:
        self.launcher = DemoLauncher(port=port, auto=False)  # presenter mode
        self.page: Any = None
        self.shots: list[dict[str, Any]] = []
        self.t0 = 0.0

    # -- live state ----------------------------------------------------

    def state(self) -> dict[str, Any]:
        with urllib.request.urlopen(self.launcher.url + "/api/state", timeout=10) as r:
            return json.loads(r.read().decode())

    def wait(self, cond: Callable[[dict], Any], timeout: float, what: str, every: float = 0.5) -> Any:
        """Poll /api/state rather than scraping the DOM: the same numbers, but
        without depending on how they happen to be rendered."""
        t = time.monotonic()
        while time.monotonic() - t < timeout:
            try:
                v = cond(self.state())
            except Exception:
                v = None
            if v:
                print(f"    ok: {what} ({time.monotonic()-t:.1f}s)", flush=True)
                return v
            self.page.wait_for_timeout(int(every * 1000))
        print(f"    TIMEOUT waiting for {what} after {timeout:.0f}s", flush=True)
        return None

    # -- capture -------------------------------------------------------

    def shot(self, slug: str, panel: str, caption: str, note: str = "") -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{slug}.png"
        sel = SEL[panel] if panel in SEL else panel
        try:
            if panel == "full":
                self.page.screenshot(path=str(path), full_page=True)
            else:
                self.page.locator(sel).first.screenshot(path=str(path))
        except Exception as exc:
            print(f"    !! could not shoot {slug}: {exc}", flush=True)
            return
        st = self.state()
        self.shots.append({
            "slug": slug,
            "panel": panel,
            "file": f"explainer_shots/{slug}.png",
            "caption": caption,
            "note": note,
            "t_s": round(time.monotonic() - self.t0, 1),
            "bytes": path.stat().st_size,
            "live": self._digest(st),
        })
        print(f"  [{self.shots[-1]['t_s']:6.1f}s] {slug}  ({path.stat().st_size//1024} KB)", flush=True)

    @staticmethod
    def _digest(s: dict[str, Any]) -> dict[str, Any]:
        """The numbers on screen at the instant of capture, so the write-up can
        quote what is actually in the image instead of a remembered figure."""
        return {
            "sim_t": round(s.get("now_t_media", 0), 1),
            "claims_total": s.get("claims_total"),
            "nodes_live": s.get("nodes_live"),
            "mean_error_m": s.get("mean_error_m"),
            "convergence": s.get("convergence"),
            "forks_open": s.get("forks_open"),
            "forks": [{"status": f["status"], "identity": f.get("identity"),
                       "face_identity": f.get("face_identity"),
                       "explanation": f.get("explanation", "")[:400],
                       "branches": [{"i": b["index"], "x": b["x"], "y": b["y"], "n": b["n_claims"]}
                                    for b in f.get("branches", [])[:4]]}
                      for f in s.get("forks", [])],
            "nodes": [{"id": n["id"], "live": n["live"], "claims": n.get("claims"),
                       "holes": n.get("holes"), "partitioned": n.get("partitioned"),
                       "lying": n.get("lying"), "attack": n.get("attack"),
                       "rejected": n.get("rejected"), "evaluated": n.get("evaluated"),
                       "reputation": n.get("reputation"),
                       "coverage_healthy": n.get("coverage_healthy")}
                      for n in s.get("nodes", [])],
            "identities": [{"short": i["short"], "name": i.get("name"), "status": i["status"],
                            "x": i["x"], "y": i["y"], "claims": i["n_claims"],
                            "error_m": i.get("error_m"), "age_s": i.get("age_s")}
                           for i in s.get("identities", [])],
            "regions": [{"id": r["id"], "area_m2": r["area_m2"],
                         "reachable_area_m2": r["reachable_area_m2"], "ratio": r.get("ratio"),
                         "unseen_for_s": r["unseen_for_s"],
                         "blind_block_area_m2": r.get("blind_block_area_m2"),
                         "healthy_zone_overlap_m2": r.get("healthy_zone_overlap_m2"),
                         "zone_overlap_m2": r.get("zone_overlap_m2"),
                         "healthy_nodes": r.get("healthy_nodes"),
                         "silent_nodes": r.get("silent_nodes"),
                         "occluded_nodes": r.get("occluded_nodes"),
                         "explanation": r.get("explanation", "")}
                        for r in s.get("regions", [])],
            "central": s.get("central"),
        }

    def _await_server(self, timeout: float = 180.0) -> None:
        """The dashboard binds its port a few seconds after the launcher returns;
        navigating before that just gets a connection refused."""
        t = time.monotonic()
        while time.monotonic() - t < timeout:
            try:
                urllib.request.urlopen(self.launcher.url + "/api/state", timeout=5).read()
                print(f"  dashboard answering after {time.monotonic()-t:.1f}s", flush=True)
                return
            except Exception:
                time.sleep(2)
        raise RuntimeError(f"dashboard never came up at {self.launcher.url}")

    def click(self, testid: str) -> None:
        self.page.click(f'[data-testid="{testid}"]')
        self.page.wait_for_timeout(700)

    def ask(self, text: str, purpose: str = "safety") -> None:
        self.page.fill('[data-testid="query-input"]', text)
        self.page.select_option('[data-testid="query-purpose"]', purpose)
        self.page.click('[data-testid="query-submit"]')
        self.page.wait_for_timeout(1800)

    def at_door(self, timeout: float = 130.0) -> None:
        """The scripted actor walks a closed circuit and pauses at the door.
        Starting the next episode only when it is there keeps each dead-zone
        scene showing the same person doing the same walk."""
        def ready(s: dict) -> Any:
            for i in s["identities"]:
                if i.get("name") == "worker-2" and i["status"] == "seen":
                    return abs(i["x"] - 1.0) < 1.6 and abs(i["y"] - 14.5) < 1.6
            return None
        self.wait(ready, timeout, "worker-2 back at the door")

    # -- scenes --------------------------------------------------------

    def scene_orientation(self) -> None:
        print("\n== scene 1: orientation (steady state) ==", flush=True)
        self.wait(lambda s: s.get("ready") and len(s.get("identities", [])) >= 3, 120, "4 nodes tracking")
        self.page.wait_for_timeout(6000)
        self.shot("01_fullpage", "full", "The whole technical view at rest.")
        self.shot("02_header", "header", "The always-on health strip.")
        self.shot("03_map", "map", "Believed positions vs simulator ground truth.")
        self.shot("04_identities", "identities", "One row per identity the resolver produced.")
        self.shot("05_nodes", "nodes", "The four node processes and their replicas.")
        self.shot("06_controls", "controls", "Every fault this demo can inject, by hand.")
        self.shot("07_demo_script", "demo_script", "The scripted tour built into the page.")
        self.shot("08_events", "events", "What the system did, in order.")

    def scene_dead_zone_healthy(self) -> None:
        print("\n== scene 2: C4 dead zone, all cameras healthy ==", flush=True)
        self.at_door()
        self.click("btn-dz-healthy")
        self.wait(lambda s: len(s.get("regions", [])) > 0, 90, "a candidate region to open")
        self.page.wait_for_timeout(14000)
        self.shot("10_map_region_healthy", "map",
                  "Worker-2 is inside the uncovered block; the region stays inside it.")
        self.shot("11_region_card_healthy", "region_cards",
                  "The negative-evidence numbers behind that shaded area.")

    def scene_dead_zone_occluded(self) -> None:
        print("\n== scene 3: C4 dead zone, camera 1 occluded ==", flush=True)
        self.wait(lambda s: not s.get("regions"), 90, "the previous region to close")
        self.at_door()
        self.click("btn-dz-occluded")
        self.wait(lambda s: len(s.get("regions", [])) > 0, 90, "a candidate region to open")
        self.page.wait_for_timeout(16000)
        self.shot("12_map_region_occluded", "map",
                  "Same walk, camera 1 occluded: the region leaks into its zone only.")
        self.shot("13_region_card_occluded", "region_cards",
                  "Silence is listed, and explicitly not counted as evidence.")
        self.wait(lambda s: not s.get("regions"), 120, "the region to close")

    def scene_partition(self) -> None:
        print("\n== scene 4: partition and heal ==", flush=True)
        self.page.wait_for_timeout(3000)
        self.shot("20_nodes_before", "nodes", "Before the cut: four replicas in step.")
        self.click("btn-partition")
        self.page.wait_for_timeout(14000)
        self.shot("21_nodes_partitioned", "nodes", "Cut {2,3} from {0,1}: the replicas drift apart.")
        self.shot("22_central_partitioned", "central",
                  "The centralized comparison loses the cut-off cameras' workers.")
        self.click("btn-heal")
        self.wait(lambda s: s["convergence"]["converged"] and not s["convergence"]["any_partitioned"],
                  90, "re-convergence")
        self.page.wait_for_timeout(2500)
        self.shot("23_nodes_healed", "nodes", "After healing: converged again, no gaps.")

    def scene_lying(self) -> None:
        print("\n== scene 5: a node lies ==", flush=True)
        self.shot("30_nodes_honest", "nodes", "All four nodes honest; reputation at 1.00.")
        self.page.select_option('[data-testid="select-lie-node"]', "2")
        self.click("btn-lie")
        self.wait(lambda s: any(n["id"] == 2 and (n.get("reputation") or 1) < 0.7 for n in s["nodes"]),
                  120, "node 2's reputation to fall below 0.70")
        self.shot("31_nodes_lying", "nodes", "Node 2 fabricates sightings: reputation falls, rejections climb.")
        self.click("btn-stop-lie")
        self.wait(lambda s: any(n["id"] == 2 and (n.get("reputation") or 0) > 0.85 for n in s["nodes"]),
                  120, "node 2's reputation to recover above 0.85")
        self.shot("32_nodes_recovered", "nodes", "It stops lying and its reputation recovers.")

    # Each conflict variant stages its own pair of look-alikes under a known face
    # identity. Waiting for "a fork" is wrong: the previous variant's fork is still
    # inside the resolver's memory window, so the wait returns instantly on the OLD
    # one and the screenshot gets captioned with the wrong verdict.
    CONFLICT_FACE = {"resolvable": "P-100", "ambiguous": "P-101"}

    def scene_conflict(self, variant: str, tag: str) -> None:
        print(f"\n== scene 6: identity conflict ({variant}) ==", flush=True)
        face = self.CONFLICT_FACE[variant]

        def own(s: dict) -> list:
            return [f for f in s.get("forks", []) if f.get("face_identity") == face]

        self.click(f"btn-conflict-{variant}")
        self.wait(lambda s: own(s) and not s["convergence"]["any_partitioned"],
                  180, f"the {variant} fork (face {face}) to appear after healing")
        self.page.wait_for_timeout(6000)
        mine = own(self.state())
        if not mine:
            print(f"    !! no fork for face {face} — SKIPPING {variant} shots rather than "
                  f"captioning another variant's fork", flush=True)
            return
        print(f"    fork for face {face}: {[f['status'] for f in mine]}", flush=True)
        self.shot(f"{tag}_forks_{variant}", "forks", f"The {variant} conflict, as the resolver reports it.")
        self.shot(f"{tag}_map_{variant}", "map", f"The {variant} conflict's branches drawn on the floor.")

    def scene_query(self) -> None:
        print("\n== scene 7: capability-scoped query ==", flush=True)
        self.ask("where is worker 2", "safety")
        self.shot("50_query_answered", "query", "A valid query: confirmed and inferred kept apart.")
        self.ask("where is worker 9", "safety")
        self.shot("51_query_refused_unknown", "query", "Nobody by that name: refused, with the reason.")
        self.ask("where is worker 2", "productivity")
        self.shot("52_query_refused_purpose", "query", "Same question, wrong purpose: refused.")

    def scene_central(self) -> None:
        print("\n== scene 8: the centralized comparison dies ==", flush=True)
        self.shot("60_central_healthy", "central", "The centralized baseline, working normally.")
        self.click("btn-central-kill")
        self.page.wait_for_timeout(9000)
        self.shot("61_central_down", "central", "Server killed: it tracks nobody. Starling is unaffected.")
        self.shot("62_nodes_while_central_down", "nodes", "The same instant on Starling's side.")
        self.click("btn-central-restart")
        self.page.wait_for_timeout(5000)

    # -- run -----------------------------------------------------------

    def run(self, scenes: list[str]) -> int:
        from playwright.sync_api import sync_playwright

        self.launcher.prepare()
        self.launcher.start()
        self.t0 = time.monotonic()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                # deviceScaleFactor=2 keeps the small type in the node cards and
                # fork tables legible when the reader zooms into a panel.
                ctx = browser.new_context(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
                self.page = ctx.new_page()
                errors: list[str] = []
                self.page.on("pageerror", lambda e: errors.append(str(e)))
                self._await_server()
                self.page.goto(self.launcher.url + "/engineer")
                self.page.wait_for_timeout(4000)

                todo = {
                    "orientation": self.scene_orientation,
                    "deadzone_healthy": self.scene_dead_zone_healthy,
                    "deadzone_occluded": self.scene_dead_zone_occluded,
                    "partition": self.scene_partition,
                    "lying": self.scene_lying,
                    "conflict_ambiguous": lambda: self.scene_conflict("ambiguous", "40"),
                    "conflict_resolvable": lambda: self.scene_conflict("resolvable", "41"),
                    "query": self.scene_query,
                    "central": self.scene_central,
                }
                for name in scenes:
                    try:
                        todo[name]()
                    except Exception as exc:
                        print(f"  !! scene {name} failed: {exc!r}", flush=True)

                MANIFEST.write_text(json.dumps(
                    {"shots": self.shots, "page_errors": errors,
                     "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    indent=2), encoding="utf-8")
                print(f"\nwrote {MANIFEST} ({len(self.shots)} shots, page errors: {len(errors)})")
                browser.close()
        finally:
            self.launcher.stop()
        return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Screenshot every panel of the technical view, with live values")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--scenes", default="orientation,deadzone_healthy,deadzone_occluded,partition,"
                                        "lying,conflict_ambiguous,conflict_resolvable,query,central")
    args = ap.parse_args(argv)
    return Capture(args.port).run([s.strip() for s in args.scenes.split(",") if s.strip()])


if __name__ == "__main__":
    raise SystemExit(main())

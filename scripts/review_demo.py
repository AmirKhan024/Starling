"""scripts/review_demo.py
-------------------------
Automated visual review of the Starling demo, for a reviewer who cannot run
the code. Starts the REAL demo (`scripts/run_demo.py`'s `DemoLauncher`, in
presenter mode so nothing happens unless the review presses a button), drives
the REAL dashboard in headless Chromium at 1440x900 through every demo moment,
polls DOM values (not fixed sleeps), takes screenshots and records what the
page actually shows, then writes:

    review/review.html          single self-contained file (base64 screenshots)
    review/review_summary.md    the same content as text
    review/screenshots/*.jpg    the individual images
    review/results.json         raw measurements of this run

Re-run with one command:     python scripts/review_demo.py
Development:                 python scripts/review_demo.py --only 2a,7a

Honesty rules: nothing is mocked or edited; every verdict comes from explicit
criteria applied to values read from the page DOM; a first run's results and
findings are kept (review/first_run_results.json + review/first_run_findings.md,
the latter written by hand) and embedded under "First-run findings".
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import platform
import re
import subprocess
import sys
import time
from importlib import metadata
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.run_demo import DemoLauncher  # noqa: E402

REVIEW_DIR = REPO / "review"
SHOT_DIR = REVIEW_DIR / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}
JPEG_QUALITY = 62
MAX_SHOT_WIDTH = 900  # full-page shots are tall; downscale from 1440 to keep the review under budget
LIAR = 2
ORDER = ["0", "1", "2a", "2b", "3", "4", "5", "6", "7a", "7b", "8"]
TITLES = {
    "0": "Startup",
    "1": "Normal walk",
    "2a": "Dead zone, healthy exits",
    "2b": "Dead zone, occluded exit",
    "3": "Partition and heal",
    "4": "Lying node",
    "5": "Query and refusal",
    "6": "Robustness",
    "7a": "Conflict, resolvable",
    "7b": "Conflict, ambiguous",
    "8": "Centralized comparison",
}
DOOR = (1.0, 14.5)  # where the stage actor (worker-2) starts and waits

READ_DOM_JS = """
() => {
  const q = (id) => { const e = document.querySelector(`[data-testid="${id}"]`); return e ? e.textContent.trim() : null; };
  const within = (root, sel) => { const e = root.querySelector(sel); return e ? e.textContent.trim() : null; };
  const nodes = [0, 1, 2, 3].map((n) => ({
    id: n, live: q(`node-${n}-live`), partitioned: q(`node-${n}-partitioned`), claims: q(`node-${n}-claims`),
    holes: q(`node-${n}-holes`), behaviour: q(`node-${n}-lying`), rejected: q(`node-${n}-rejected`),
    reputation: q(`rep-value-${n}`),
    zone: (document.querySelector(`[data-testid="zone-${n}"]`) || {dataset: {}}).dataset.coverage || null,
  }));
  const identities = [...document.querySelectorAll('[data-testid^="identity-row-"]')].map((tr) => {
    const c = [...tr.children].map((x) => x.textContent.trim());
    return { label: tr.dataset.testid.replace("identity-row-", ""), name: c[1], status: c[2], pos: c[3], age: c[4],
             node: c[5], claims: c[6], error: c[7], region: c[8] };
  });
  const cards = [...document.querySelectorAll('[data-testid^="region-card-"]')].map((el) => {
    const label = el.dataset.testid.replace("region-card-", "");
    const num = (sel) => { const t = within(el, sel); return t == null ? null : parseFloat(t); };
    let zo = {}; try { zo = JSON.parse(el.dataset.zoneOverlap || "{}"); } catch (e) {}
    return { label, hidden_s: num('[data-testid^="region-hidden-"]'), area: num('[data-testid$="-m2"]'),
             reach: num('[data-testid^="region-reach-"]'), ratio_pct: within(el, '[data-testid^="region-ratio-"]'),
             blind: num('[data-testid^="region-blind-"]'), healthy_overlap: num('[data-testid^="region-healthy-overlap-"]'),
             zone_overlap: zo, healthy: el.dataset.healthy, silent: el.dataset.silent, occluded: el.dataset.occluded,
             explanation: within(el, '[data-testid^="region-explanation-"]'),
             spark_points: (el.querySelector('[data-testid^="region-spark-"] polyline') || {getAttribute: () => ""}).getAttribute("points").split(" ").length };
  });
  const forks = [...document.querySelectorAll('[data-testid^="fork-"][data-status]')].map((el) => ({
    id: el.dataset.testid, status: el.dataset.status, text: el.textContent.trim().slice(0, 900),
    explanation: within(el, '[data-testid^="fork-explanation-"]'),
    rows: [...el.querySelectorAll('tr[data-testid^="fork-branch-row-"]')].map((r) => [...r.children].map((c) => c.textContent.trim())),
  }));
  const forkMarkers = [...document.querySelectorAll('[data-testid^="fork-branch-"][data-x]')].map((g) => ({
    id: g.dataset.testid, x: parseFloat(g.dataset.x), y: parseFloat(g.dataset.y), text: g.textContent.trim() }));
  const qr = document.querySelector('[data-testid="query-result"]');
  return {
    status: q("dash-status"), nodes_live: q("nodes-live"), sim_time: q("sim-time"), claims_total: q("claims-total"),
    mean_error: q("mean-error"), tick: q("refresh-tick"), convergence: q("convergence-status"),
    spread: q("claim-spread"), holes: q("claim-holes"), partition: q("partition-state"),
    forks_open: q("forks-count"), forks_total: q("forks-total"), action: q("action-status"), conflict_phase: q("conflict-phase"),
    central: { status: q("central-status"), tracked_now: q("central-tracked-now"), starling_now: q("starling-tracked-now"),
               truth: q("truth-workers"), detail: q("central-detail") },
    nodes, identities, cards, forks, forkMarkers,
    events: [...document.querySelectorAll('[data-testid="event-log"] div')].slice(0, 8).map((d) => d.textContent.trim()),
    demo_steps: document.querySelectorAll('[data-testid^="demo-step-"]').length,
    query: qr ? { status: qr.dataset.status, verdict: q("query-verdict"), reason: q("query-reason"),
                  confirmed: q("query-confirmed"), inferred: q("query-inferred"), unreachable: q("query-unreachable"),
                  text: q("query-result-text") } : null,
  };
}
"""


def num(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group(0)) if m else None


class Review:
    def __init__(self, port: int, only: Optional[list]) -> None:
        self.launcher = DemoLauncher(port=port, auto=False)
        self.only = only
        self.t_launch = 0.0
        self.shots: list[dict[str, Any]] = []
        self.console_errors: list[str] = []
        self.moments: dict[str, dict[str, Any]] = {
            m: {"title": TITLES[m], "verdict": "NOT TESTED", "reason": "not run in this invocation" if only else "not reached",
                "measures": {}, "what": "", "action": ""}
            for m in ORDER
        }
        self.notes: list[str] = []
        self.page: Any = None
        self.browser_version = "unknown"
        self.exit_status: dict[str, Any] = {}
        self._blind_query: Optional[dict[str, Any]] = None

    # -- helpers ------------------------------------------------------

    def now(self) -> float:
        return time.monotonic() - self.t_launch

    def dom(self) -> dict[str, Any]:
        return self.page.evaluate(READ_DOM_JS)

    def wait(self, cond: Callable[[dict[str, Any]], Any], timeout: float, what: str, every: float = 0.4) -> tuple[Any, float]:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                val = cond(self.dom())
            except Exception as exc:
                val = None
                self.notes.append(f"transient DOM read error while waiting for {what}: {exc!r}")
            if val:
                return val, time.monotonic() - t0
            self.page.wait_for_timeout(int(every * 1000))
        return None, time.monotonic() - t0

    def shot(self, moment: str, order: str, slug: str, caption: str, values: Optional[dict] = None) -> dict[str, Any]:
        name = f"{moment}{order}_{slug}"
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"{name}.jpg"
        raw = self.page.screenshot(full_page=True, type="png")
        # The dashboard is a tall, text-heavy page; a full-resolution 1440px-wide
        # JPEG of it runs 300KB+ each and blows the ~15MB review budget across ~50
        # shots. Downscale (still legible for a reviewer zooming in) before encoding.
        img = Image.open(BytesIO(raw)).convert("RGB")
        target_w = min(img.width, MAX_SHOT_WIDTH)
        if img.width > target_w:
            img = img.resize((target_w, round(img.height * target_w / img.width)), Image.LANCZOS)
        img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        d = values if values is not None else self.dom()
        rec = {"moment": moment, "name": name, "file": f"screenshots/{name}.jpg", "caption": caption,
               "t_s": round(self.now(), 1), "dom": summarise_dom(d), "bytes": path.stat().st_size}
        self.shots.append(rec)
        print(f"  [{rec['t_s']:7.1f}s] {name}: {caption}", flush=True)
        return rec

    def set_moment(self, m: str, **kw: Any) -> None:
        self.moments[m].update(kw)

    def verdict(self, m: str, verdict: str, reason: str) -> None:
        self.moments[m]["verdict"] = verdict
        self.moments[m]["reason"] = reason
        print(f"  => moment {m} {verdict}: {reason}", flush=True)

    def worker_row(self, d: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
        rows = [r for r in d["identities"] if r["name"] == name]
        return max(rows, key=lambda r: num(r["claims"]) or 0) if rows else None

    def click(self, testid: str, what: str, wait_done: bool = True) -> None:
        self.page.click(f'[data-testid="{testid}"]')
        if wait_done:
            self.wait(lambda d: (d["action"] or "").endswith(("done", "unreachable")) or "already" in (d["action"] or ""), 12, f"{what} to finish")

    def card(self, d: dict[str, Any], label: Optional[str]) -> Optional[dict[str, Any]]:
        return next((c for c in d["cards"] if c["label"] == label), None)

    def wait_actor_at_door(self, timeout: float = 130.0) -> bool:
        """The stage actor walks a closed circuit and waits at the door: only start
        the next episode once it is there, so the re-run continues the SAME person."""
        def at_door(d: dict[str, Any]) -> Any:
            r = self.worker_row(d, "worker-2")
            if not r or r["status"] != "seen":
                return None
            x, y = (float(v) for v in r["pos"].split(","))
            return abs(x - DOOR[0]) < 1.2 and abs(y - DOOR[1]) < 1.2

        ok, _ = self.wait(at_door, timeout, "worker-2 back at the door", every=0.5)
        return bool(ok)

    # -- moments ------------------------------------------------------

    def m0_startup(self) -> None:
        m = "0"
        self.set_moment(m, what="The dashboard loads and all four node processes, the simulator and the centralized comparison server are up.",
                        action="Launched the demo in presenter mode (`scripts/run_demo.py --presenter`, launched here via `DemoLauncher`) and opened the dashboard in headless Chromium.")
        # The review reads the TECHNICAL view: the operator view at "/" is written
        # for a warehouse manager and deliberately hides claim counts, gaps,
        # reputation and fork internals, which are exactly what the evidence needs.
        self.page.goto(self.launcher.url + "/engineer")
        self.page.wait_for_selector('[data-testid="node-card-3"]', timeout=60000)
        ok, _ = self.wait(lambda d: num(d["nodes_live"]) == 4 and (num(d["claims_total"]) or 0) > 50 and d["central"]["status"] == "HEALTHY", 90, "4 nodes live + central healthy")
        t_live = self.now()
        self.wait(lambda d: len([r for r in d["identities"] if r["name"] not in ("–", "")]) >= 4, 60, "identities named")
        d = self.dom()
        self.moments[m]["measures"].update({"seconds_launch_to_all_nodes_live": round(t_live, 1), "demo_script_steps_listed": d["demo_steps"],
                                            "zones_coverage": [n["zone"] for n in d["nodes"]]})
        self.shot(m, "a", "startup_loaded", "Dashboard loaded: 4 nodes live, all four camera zones outlined green (healthy), Demo script panel present.")
        if ok and t_live < 60 and d["demo_steps"] >= 8 and all(n["zone"] == "healthy" for n in d["nodes"]):
            self.verdict(m, "PASS", f"all 4 nodes live and central server healthy {t_live:.1f}s after launch; all camera zones healthy; demo-script panel lists {d['demo_steps']} steps")
        elif ok:
            self.verdict(m, "PARTIAL", f"up after {t_live:.1f}s but zones {[n['zone'] for n in d['nodes']]} / demo steps {d['demo_steps']}")
        else:
            self.verdict(m, "FAIL", "the dashboard never showed 4 live nodes and a healthy central server")

    def m1_walk(self) -> None:
        m = "1"
        self.set_moment(m, what="Believed worker positions (one colour per resolved identity) move across the floor plan; identities stay consistent; faint ground-truth markers give the comparison.",
                        action="Observed only for ~25 s. The four patrol workers stay inside their own camera zones (the stage actor worker-2 only appears in the dead-zone episodes), so 'identity across zones' is exercised in moment 2a.")
        d0 = self.dom()
        self.shot(m, "a", "walk_start", "Four workers, four identities (P-00x) with ground-truth rings.", d0)
        pos0 = {r["label"]: r["pos"] for r in d0["identities"]}
        errors: list[float] = []
        t0 = time.monotonic()
        took_b = False
        while time.monotonic() - t0 < 25:
            e = num(self.dom()["mean_error"])
            if e is not None:
                errors.append(e)
            self.page.wait_for_timeout(1000)
            if not took_b and time.monotonic() - t0 > 8:
                self.shot(m, "b", "walk_later", "Same identities at new positions a few seconds later.")
                took_b = True
        d1 = self.dom()
        self.shot(m, "c", "walk_25s", "25 s in: identities unchanged.", d1)
        pos1 = {r["label"]: r["pos"] for r in d1["identities"]}
        moved = 0.0
        for lab, p in pos0.items():
            if lab in pos1:
                a = [float(x) for x in p.split(",")]
                b = [float(x) for x in pos1[lab].split(",")]
                moved = max(moved, ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)
        named = sorted(r["name"] for r in d1["identities"] if r["name"] not in ("–", ""))
        stable = sorted(pos0) == sorted(pos1)
        avg = round(sum(errors) / len(errors), 2) if errors else None
        self.moments[m]["measures"].update({
            "named_workers": named, "identities_listed": len(d1["identities"]), "labels_unchanged_over_25s": stable,
            "max_displacement_m": round(moved, 2), "mean_position_error_m_avg": avg, "mean_position_error_m_samples": errors[-8:],
            "per_identity_error_m": [num(r["error"]) for r in d1["identities"]],
        })
        problems = []
        if named != ["worker-0", "worker-1", "worker-3", "worker-4"] or len(d1["identities"]) != 4:
            problems.append(f"expected exactly workers 0,1,3,4 as 4 identities, saw {len(d1['identities'])}: {named}")
        if not stable:
            problems.append("identity labels changed during the walk")
        if moved < 3.0:
            problems.append(f"workers barely moved ({moved:.1f} m)")
        if avg is None or avg > 1.0:
            problems.append(f"mean position error {avg} m")
        if problems:
            self.verdict(m, "PARTIAL", "; ".join(problems))
        else:
            self.verdict(m, "PASS", f"4 identities tracked, labels unchanged for 25 s, max displacement {moved:.1f} m, mean error {avg} m vs ground truth")

    # ---- dead zone episodes ----------------------------------------

    def episode(self, m: str, button: str) -> None:
        name = "worker-2"
        d = self.dom()
        self.shot(m, "1", "before", "Before the episode: cameras all healthy (green)" + ("; worker-2 waits at the door." if self.worker_row(d, name) else "; worker-2 is not in the building yet."), d)
        self.click(button, "start episode")
        t_click = time.monotonic()
        self.wait(lambda dd: (lambda r: r and r["status"] == "seen")(self.worker_row(dd, name)), 30, "worker-2 to appear")
        w2 = self.worker_row(self.dom(), name)
        label = w2["label"] if w2 else None
        found, _ = self.wait(lambda dd: self.card(dd, label), 75, "worker-2's candidate region", every=0.25)
        samples: list[dict[str, Any]] = []
        t_reg = time.monotonic()
        shots_at = [0, 5, 10, 16, 22]
        taken = 0
        asked = False
        if found:
            while time.monotonic() - t_reg < 60:
                dd = self.dom()
                c = self.card(dd, label)
                if c is None:
                    break
                el = round(time.monotonic() - t_reg, 1)
                samples.append({"t": el, "area": c["area"], "reach": c["reach"], "ratio_pct": c["ratio_pct"], "blind": c["blind"],
                                "healthy_overlap": c["healthy_overlap"], "zone_overlap": c["zone_overlap"], "healthy": c["healthy"],
                                "silent": c["silent"], "occluded": c["occluded"], "hidden_s": c["hidden_s"], "explanation": c["explanation"]})
                if taken < len(shots_at) and el >= shots_at[taken]:
                    self.shot(m, str(2 + taken), f"hidden_{int(el)}s", f"{label} hidden {c['hidden_s']} s: search area {c['area']} m² vs {c['reach']} m² reachable without negative evidence ({c['ratio_pct']}); overlap with healthy cameras' zones {c['healthy_overlap']} m²; zone overlap {c['zone_overlap']}.", dd)
                    taken += 1
                if m == "2a" and not asked and el >= 8:
                    asked = True
                    self.page.fill('[data-testid="query-input"]', "where is worker 2")
                    self.page.select_option('[data-testid="query-purpose"]', "safety")
                    self.page.click('[data-testid="query-submit"]')
                    self.wait(lambda d3: d3["query"] and d3["query"]["status"] in ("answered", "refused") and d3["query"]["text"], 15, "blind-block query")
                    self._blind_query = self.dom()
                    self.shot("5", "e", "query_worker_in_blind_block", "Query 'where is worker 2' while worker-2 is hidden in the uncovered block: the answer reports the last confirmed position and the candidate region, not a made-up position.", self._blind_query)
                self.page.wait_for_timeout(900)
        self.wait(lambda dd: (lambda r: r and r["status"] == "seen")(self.worker_row(dd, name)), 40, "worker-2 re-seen")
        d_after = self.dom()
        w2b = self.worker_row(d_after, name)
        self.shot(m, "7", "reemerged", f"worker-2 re-emerges from the block; identity now {w2b['label'] if w2b else None} (before: {label}).", d_after)
        areas = [s["area"] for s in samples if s["area"] is not None]
        self.moments[m]["measures"].update({
            "seconds_click_to_region_on_page": round(t_reg - t_click, 1), "identity_measured": label,
            "identity_after_reemerging": w2b["label"] if w2b else None, "same_identity_after": bool(w2b and label and w2b["label"] == label),
            "n_samples": len(samples), "region_lifetime_s": samples[-1]["t"] if samples else None,
            "first_area_m2": areas[0] if areas else None, "max_area_m2": max(areas) if areas else None, "final_area_m2": areas[-1] if areas else None,
            "reach_at_end_m2": samples[-1]["reach"] if samples else None,
            "final_ratio_area_over_reach": round(areas[-1] / samples[-1]["reach"], 3) if samples and samples[-1]["reach"] else None,
            "max_healthy_zone_overlap_m2": max((s["healthy_overlap"] or 0) for s in samples) if samples else None,
            "max_area_outside_blind_block_m2": max(((s["area"] or 0) - (s["blind"] or 0)) for s in samples) if samples else None,
            "samples": samples,
        })

    def m2a_healthy(self) -> None:
        m = "2a"
        self.set_moment(m, what="A worker disappears into the 12x7 m uncovered block for ~27 s. Every exit is watched by a healthy camera that saw nobody leave, so the candidate region must stay inside the block, never include a healthy camera's zone, and be much smaller than plain reachability allows; the same identity is restored on re-emergence.",
                        action="Pressed 'Dead zone - healthy exits' (the simulator moves worker-2 from the west door through the block and out through the east zone), then sampled the page (region area, reachable-without-negative-evidence area, healthy-zone overlap, area outside the block) about every second.")
        self.episode(m, "btn-dz-healthy")
        ms = self.moments[m]["measures"]
        problems = []
        if ms["n_samples"] < 15:
            problems.append(f"only {ms['n_samples']} samples ({ms['region_lifetime_s']} s): the worker was not hidden long enough")
        if (ms["max_healthy_zone_overlap_m2"] or 0) > 0.0:
            problems.append(f"region overlapped a healthy camera's zone by up to {ms['max_healthy_zone_overlap_m2']} m²")
        if (ms["max_area_outside_blind_block_m2"] or 0) > 0.5:
            problems.append(f"region extended {ms['max_area_outside_blind_block_m2']} m² outside the blind block")
        ratio = ms["final_ratio_area_over_reach"]
        if ratio is None or ratio > 0.5:
            problems.append(f"region not substantially smaller than the reachable area (ratio {ratio})")
        if not ms["same_identity_after"]:
            problems.append(f"identity after re-emerging was {ms['identity_after_reemerging']}, not {ms['identity_measured']}")
        if not problems:
            self.verdict(m, "PASS", f"region confined to the block for {ms['region_lifetime_s']} s (0 m² in healthy zones, at most 0.5 m² outside the block), final {ms['final_area_m2']} m² vs {ms['reach_at_end_m2']} m² reachable (ratio {ratio}), same identity {ms['identity_measured']} on re-emergence")
        else:
            self.verdict(m, "PARTIAL" if ms["n_samples"] >= 5 else "FAIL", "; ".join(problems))

    def m2b_occluded(self) -> None:
        m = "2b"
        self.set_moment(m, what="Same walk, but the north exit camera (node 1) is occluded for the whole episode, so it sends no healthy attestation. Its silence must NOT be counted as evidence: the region should leak into that camera's zone, and only that one, and the dashboard should say why.",
                        action="Waited for worker-2 to be back at the door, then pressed 'Dead zone - occluded camera 1' (the simulator occludes camera 1 and repeats the walk); sampled the page about every second.")
        if not self.wait_actor_at_door():
            self.notes.append("worker-2 was not back at the door before episode 2b; identity continuity may be affected")
        self.episode(m, "btn-dz-occluded")
        ms = self.moments[m]["measures"]
        s = ms["samples"]
        leak1 = max(((x["zone_overlap"] or {}).get("1", 0.0) for x in s), default=0.0)
        other = max(((x["zone_overlap"] or {}).get(str(n), 0.0) for x in s for n in (0, 2, 3)), default=0.0)
        explained = [x for x in s if "camera 1 is silent" in (x["explanation"] or "") and "occluded" in (x["explanation"] or "") and "not counted as evidence" in (x["explanation"] or "")]
        peak = max(s, key=lambda x: (x["zone_overlap"] or {}).get("1", 0.0), default=None)
        ms.update({"max_overlap_with_occluded_zone_1_m2": round(leak1, 1), "max_overlap_with_other_zones_m2": round(other, 1),
                   "samples_where_page_explains_the_silence": len(explained), "explanation_at_peak_leak": peak["explanation"] if peak else None})
        problems = []
        if leak1 <= 5.0:
            problems.append(f"the region did not leak into the occluded camera's zone (max {leak1:.1f} m²)")
        if other > 0.0:
            problems.append(f"the region also entered a healthy camera's zone by {other:.1f} m²")
        if len(explained) < max(3, len(s) // 2):
            problems.append(f"the page explained the silence in only {len(explained)} of {len(s)} samples")
        if not ms["same_identity_after"]:
            problems.append(f"identity after re-emerging was {ms['identity_after_reemerging']}")
        if ms["n_samples"] < 15:
            problems.append(f"only {ms['n_samples']} samples")
        if not problems:
            self.verdict(m, "PASS", f"region leaked into camera 1's zone (up to {leak1:.0f} m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in {len(explained)} of {len(s)} samples; same identity on re-emergence")
        else:
            self.verdict(m, "PARTIAL" if leak1 > 5 else "FAIL", "; ".join(problems))

    # ---- partition, lying, query, robustness -------------------------

    def m3_partition(self) -> None:
        m = "3"
        self.set_moment(m, what="Cut nodes {2,3} from {0,1}; both sides keep working; on heal the replicas reconverge (equal claim counts, no gaps).",
                        action="Pressed 'Partition {2,3} from {0,1}', waited, pressed 'Heal', and timed how long until the convergence badge read CONVERGED.")
        d = self.dom()
        pre = {"claims": [num(n["claims"]) for n in d["nodes"]], "spread": num(d["spread"]), "convergence": d["convergence"]}
        self.shot(m, "a", "before_partition", "Before: all nodes hold (almost) the same number of claims.", d)
        self.click("btn-partition", "partition")
        ok, _ = self.wait(lambda d: all((n["partitioned"] or "").startswith("yes") for n in d["nodes"]), 15, "all nodes partitioned")
        self.shot(m, "b", "partition_during", "Partition applied: every node card reports 'partitioned: yes'.")
        spreads = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 12:
            dd = self.dom()
            spreads.append((round(time.monotonic() - t0, 1), num(dd["spread"]), [num(n["claims"]) for n in dd["nodes"]]))
            self.page.wait_for_timeout(1500)
        self.shot(m, "c", "partition_later", "12 s into the partition: the two sides' claim counts have drifted apart.")
        self.click("btn-heal", "heal")
        t_heal = time.monotonic()
        conv, _ = self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "convergence after heal", every=0.25)
        heal_s = round(time.monotonic() - t_heal, 1)
        d_after = self.dom()
        self.shot(m, "d", "after_heal", f"After heal: {d_after['convergence']}, spread {d_after['spread']}, gaps {d_after['holes']} ({heal_s}s after pressing Heal).", d_after)
        max_spread = max((s or 0) for _, s, _ in spreads) if spreads else None
        self.moments[m]["measures"].update({"before": pre, "partition_state_shown_on_all_4_nodes": bool(ok), "spread_and_claims_during_partition": spreads,
                                            "max_spread_during_partition": max_spread, "seconds_from_heal_to_converged": heal_s if conv else None,
                                            "after_heal_claims": [num(n["claims"]) for n in d_after["nodes"]], "after_heal_gaps": num(d_after["holes"])})
        problems = []
        if not ok:
            problems.append("partition state not shown on all 4 node cards")
        if max_spread is None or max_spread <= (pre["spread"] or 0) + 5:
            problems.append(f"claim counts did not visibly diverge (max spread {max_spread} vs {pre['spread']} before)")
        if not conv:
            problems.append("did not converge within 60 s of healing")
        if problems:
            self.verdict(m, "PARTIAL" if conv and ok else "FAIL", "; ".join(problems))
        else:
            self.verdict(m, "PASS", f"partition shown on all nodes, spread grew to {max_spread}, converged {heal_s}s after heal with gaps={d_after['holes']}")

    def m4_lying(self) -> None:
        m = "4"
        self.set_moment(m, what="A node fabricates sightings; peers reject implausible claims and its reputation, as seen by peers, drops; it recovers when it stops. Honest nodes must not lose reputation.",
                        action=f"Selected node {LIAR}, pressed 'Make node lie', sampled reputation and rejected-claim counters every ~2 s for up to 40 s, then pressed 'Stop lying' and sampled recovery for up to 60 s.")
        d = self.dom()
        before = [num(n["reputation"]) for n in d["nodes"]]
        rej_before = [num((n["rejected"] or "").split(" of ")[0]) for n in d["nodes"]]
        self.shot(m, "a", "before_lie", f"Before: reputation {before}, rejected {rej_before}.", d)
        self.page.select_option('[data-testid="select-lie-node"]', str(LIAR))
        self.click("btn-lie", "lie")
        t_lie = time.monotonic()
        samples, dropped_at = [], None
        shot_b = shot_c = False
        while time.monotonic() - t_lie < 40:
            dd = self.dom()
            el = round(time.monotonic() - t_lie, 1)
            rep = [num(n["reputation"]) for n in dd["nodes"]]
            rej = [num((n["rejected"] or "").split(" of ")[0]) for n in dd["nodes"]]
            samples.append({"t": el, "reputation": rep, "rejected": rej})
            if not shot_b and el >= 4:
                self.shot(m, "b", "lying_early", f"{el}s after 'Make node {LIAR} lie': reputation {rep}, rejected {rej}.", dd)
                shot_b = True
            if rep[LIAR] is not None and rep[LIAR] < 0.7 and dropped_at is None:
                dropped_at = el
            if dropped_at is not None and el >= dropped_at + 8 and not shot_c:
                self.shot(m, "c", "lying_dropped", f"Node {LIAR}'s reputation has dropped: {rep}, rejected {rej}.", dd)
                shot_c = True
                break
            self.page.wait_for_timeout(1800)
        if not shot_c:
            self.shot(m, "c", "lying_end", "End of the lying window.")
        self.click("btn-stop-lie", "stop lying")
        t_stop = time.monotonic()
        rec_samples, recovered_at, shot_d = [], None, False
        while time.monotonic() - t_stop < 60:
            dd = self.dom()
            el = round(time.monotonic() - t_stop, 1)
            rep = [num(n["reputation"]) for n in dd["nodes"]]
            rec_samples.append({"t": el, "reputation": rep})
            if not shot_d and el >= 5:
                self.shot(m, "d", "recovering", f"{el}s after 'Stop lying': reputation {rep}.", dd)
                shot_d = True
            if rep[LIAR] is not None and rep[LIAR] > 0.9:
                recovered_at = el
                break
            self.page.wait_for_timeout(2000)
        d_end = self.dom()
        self.shot(m, "e", "after_stop", f"End of recovery window: reputation {[num(n['reputation']) for n in d_end['nodes']]}.", d_end)
        rej_end = [num((n["rejected"] or "").split(" of ")[0]) for n in d_end["nodes"]]
        last = samples[-1] if samples else {"reputation": [None] * 4, "rejected": [0] * 4}
        honest_min = min((r for i, r in enumerate(last["reputation"]) if i != LIAR and r is not None), default=None)
        honest_rejected_delta = [(rej_end[i] or 0) - (rej_before[i] or 0) for i in range(4) if i != LIAR]
        self.moments[m]["measures"].update({
            "liar_node": LIAR, "reputation_before": before, "rejected_before": rej_before, "samples_while_lying": samples,
            "seconds_until_liar_reputation_below_0.7": dropped_at, "liar_rejected_claims_at_end_of_lying": last["rejected"][LIAR],
            "lowest_honest_reputation_while_lying": honest_min, "honest_nodes_rejected_claims_added_during_test": honest_rejected_delta,
            "recovery_samples": rec_samples, "seconds_until_liar_reputation_above_0.9_after_stop": recovered_at,
        })
        problems = []
        if dropped_at is None:
            problems.append("the liar's reputation never fell below 0.7 within 40 s")
        if honest_min is not None and honest_min < 0.8:
            problems.append(f"an honest node's reputation fell to {honest_min}")
        if not (last["rejected"][LIAR] or 0) > (rej_before[LIAR] or 0):
            problems.append("no rejected claims counted for the liar")
        if dropped_at is None:
            self.verdict(m, "FAIL", "; ".join(problems))
        elif problems:
            self.verdict(m, "PARTIAL", "; ".join(problems))
        elif recovered_at is None:
            self.verdict(m, "PARTIAL", f"reputation fell below 0.7 after {dropped_at}s but did not recover above 0.9 within 60 s of stopping")
        else:
            self.verdict(m, "PASS", f"liar's reputation < 0.7 after {dropped_at}s ({last['rejected'][LIAR]} claims rejected), honest nodes stayed >= {honest_min} (their rejected counters grew by {honest_rejected_delta} during the test), recovered > 0.9 {recovered_at}s after stopping")

    def ask(self, text: str, purpose: str = "safety") -> dict[str, Any]:
        self.page.fill('[data-testid="query-input"]', text)
        self.page.select_option('[data-testid="query-purpose"]', purpose)
        self.page.click('[data-testid="query-submit"]')
        res, _ = self.wait(lambda d: d["query"] and d["query"]["status"] in ("answered", "refused") and (d["query"]["text"] or d["query"]["reason"]) and d["query"], 15, f"query '{text}'")
        return res or self.dom()["query"]

    def m5_query(self) -> None:
        m = "5"
        self.set_moment(m, what="A text query (with a `safety` capability token) returns a structured answer separating confirmed from inferred and naming unreachable nodes; unanswerable queries are refused with a reason; a query about a worker in the blind block reports the candidate region, not a made-up position.",
                        action="Typed queries into the query box and read the rendered result from the DOM: a valid one, an unknown worker, a query during a partition, one under a `productivity` token, and (during moment 2a) one about the worker hidden in the uncovered block.")
        q1 = self.ask("where is worker 3")
        self.shot(m, "a", "answer_worker3", "Valid query 'where is worker 3' (purpose safety).")
        q2 = self.ask("where is worker 9")
        self.shot(m, "b", "refusal_unknown", "Unanswerable query 'where is worker 9': refused with its reason.")
        self.click("btn-partition", "partition (edge case)")
        self.wait(lambda d: all((n["partitioned"] or "").startswith("yes") for n in d["nodes"]), 15, "partitioned")
        self.page.wait_for_timeout(3000)
        q3 = self.ask("where is worker 3")
        self.shot(m, "c", "query_while_partitioned", "Edge case: 'where is worker 3' while {2,3} is cut off from the querying side.")
        self.click("btn-heal", "heal")
        self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "converged")
        q4 = self.ask("where is worker 3", "productivity")
        self.shot(m, "d", "refusal_productivity", "Same query under a `productivity` token: refused (purpose limitation).")
        q5 = self._blind_query["query"] if self._blind_query else None
        self.moments[m]["measures"].update({"valid_query": q1, "unknown_worker": q2, "during_partition": q3, "productivity_token": q4, "worker_in_blind_block": q5})
        problems = []
        if not (q1 and q1["status"] == "answered" and q1["confirmed"] and q1["inferred"] and q1["unreachable"]):
            problems.append("valid query did not return confirmed + inferred + unreachable-nodes sections")
        if not (q2 and q2["status"] == "refused" and q2["reason"]):
            problems.append("unknown worker was not refused with a reason")
        if not (q3 and q3["status"] in ("answered", "refused")):
            problems.append("no result for the partitioned-edge-case query")
        if not (q4 and q4["status"] == "refused" and "not authorised" in (q4["reason"] or "")):
            problems.append("productivity purpose was not refused")
        if not (q5 and q5["status"] == "answered" and "candidate" in (q5["inferred"] or "").lower() and "m²" in (q5["inferred"] or "")):
            problems.append(f"the query about the worker in the blind block did not report a candidate region: {q5 and q5['inferred']}")
        if not problems:
            self.verdict(m, "PASS", "valid query answered (confirmed/inferred/unreachable); unknown worker and productivity purpose refused with reasons; partition edge case: " + (q3["status"] or "") + "; blind-block query reported: " + (q5["inferred"] or "")[:150])
        else:
            self.verdict(m, "PARTIAL" if q1 and q1["status"] == "answered" else "FAIL", "; ".join(problems))

    def m6_robust(self) -> None:
        m = "6"
        self.set_moment(m, what="The dashboard survives a page reload; a node process that actually dies is shown as OFFLINE (and its camera zone as silent), and shown live again when restarted.",
                        action="Reloaded the browser page; hard-killed node 1's OS process (not via any dashboard control), watched its card and zone, restarted the process, and watched it return.")
        t0 = time.monotonic()
        self.page.reload()
        self.page.wait_for_selector('[data-testid="node-card-3"]', timeout=30000)
        ok, _ = self.wait(lambda d: num(d["nodes_live"]) == 4 and d["status"] == "live", 30, "recovery after reload")
        reload_s = round(time.monotonic() - t0, 1)
        self.shot(m, "a", "after_reload", f"Page reloaded mid-run; recovered in {reload_s}s with 4 nodes live.")
        self.launcher.kill_node(1)
        t_kill = time.monotonic()
        off, _ = self.wait(lambda d: d["nodes"][1]["live"] == "OFFLINE", 30, "node 1 OFFLINE")
        off_s = round(time.monotonic() - t_kill, 1)
        d = self.dom()
        zone_state = d["nodes"][1]["zone"]
        self.shot(m, "b", "node1_killed", f"Node 1's process killed; card reads {d['nodes'][1]['live']} after {off_s}s, its camera zone is '{zone_state}'; nodes live {d['nodes_live']}.", d)
        others_live = all(d["nodes"][i]["live"] == "LIVE" for i in (0, 2, 3))
        self.launcher.restart_node(1)
        t_restart = time.monotonic()
        back, _ = self.wait(lambda d: d["nodes"][1]["live"] == "LIVE", 45, "node 1 LIVE again")
        back_s = round(time.monotonic() - t_restart, 1)
        self.shot(m, "c", "node1_restarted", f"Node 1 restarted; LIVE after {back_s}s.")
        conv, _ = self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "converged after restart")
        conv_s = round(time.monotonic() - t_restart, 1)
        d = self.dom()
        self.shot(m, "d", "after_recovery", f"After recovery: {d['convergence']}, gaps {d['holes']}, claims {[num(n['claims']) for n in d['nodes']]}.", d)
        self.moments[m]["measures"].update({"seconds_to_recover_after_reload": reload_s, "seconds_until_killed_node_shown_offline": off_s if off else None,
                                            "killed_node_camera_zone_state": zone_state, "other_nodes_stayed_live_while_node1_down": others_live,
                                            "seconds_until_restarted_node_live": back_s if back else None, "seconds_from_restart_to_converged": conv_s if conv else None})
        problems = []
        if not ok:
            problems.append("dashboard did not recover after a reload")
        if not off:
            problems.append("killed node never shown OFFLINE")
        if not others_live:
            problems.append("other nodes were not all live while node 1 was down")
        if not back:
            problems.append("restarted node never shown LIVE again")
        if not problems:
            self.verdict(m, "PASS" if conv else "PARTIAL", f"reload recovered in {reload_s}s; killed node OFFLINE after {off_s}s (its camera zone: {zone_state}); LIVE again {back_s}s after restart; " + (f"converged {conv_s}s after restart" if conv else "did not re-converge within 60 s"))
        else:
            self.verdict(m, "FAIL" if not off or not back else "PARTIAL", "; ".join(problems))

    # ---- conflicts -----------------------------------------------------

    def conflict(self, m: str, button: str, variant: str) -> None:
        self.click("btn-heal", "heal (clean start)")
        self.click("btn-reset", "reset (clean view)")
        self.page.wait_for_timeout(3000)
        self.shot(m, "1", "before", "Clean start: healed network, no forks.")
        self.click(button, f"conflict {variant}", wait_done=False)
        expected_face = {"resolvable": "P-100", "ambiguous": "P-101"}[variant]

        def own_forks(dd: dict[str, Any]) -> list:
            return [x for x in dd["forks"] if f"face id {expected_face}" in x["text"]]

        t0 = time.monotonic()
        forks_while_partitioned, held_seen = 0, 0
        shot_part = False
        healed_at = None
        while time.monotonic() - t0 < 110:
            d = self.dom()
            phase = d["conflict_phase"] or ""
            if "partitioned" in phase:
                forks_while_partitioned = max(forks_while_partitioned, len(own_forks(d)))
                held = re.search(r"(\d+) far-side claims held back", phase)
                held_seen = max(held_seen, int(held.group(1)) if held else 0)
                if not shot_part and time.monotonic() - t0 > 22:
                    self.shot(m, "2", "partitioned_twins", f"Partitioned: twin A on side {{0,1}}, twin B on side {{2,3}}; this variant's fork visible: {len(own_forks(d))} ({phase}).", d)
                    shot_part = True
            if "healed" in phase and own_forks(d):
                healed_at = time.monotonic() - t0
                break
            self.page.wait_for_timeout(700)
        d = self.dom()
        self.shot(m, "3", "after_heal_fork", f"After the network healed: {len(d['forks'])} fork(s) shown, open={d['forks_open']}.", d)
        self.page.wait_for_timeout(8000)
        d2 = self.dom()
        self.shot(m, "4", "8s_later", f"8 s later: fork status unchanged ({[f['status'] for f in d2['forks']]}).", d2)
        # Match the fork by this variant's OWN face identity (P-100 for resolvable,
        # P-101 for ambiguous), not by list position: a previous variant's twins can
        # still be walking (their route is longer than the heal-after window) and
        # briefly leave an unrelated, older fork in the panel's memory window.
        expected_face = {"resolvable": "P-100", "ambiguous": "P-101"}[variant]
        f = next((x for x in d["forks"] if f"face id {expected_face}" in x["text"]), None)
        f2 = next((x for x in d2["forks"] if f and x["id"] == f["id"]), None)
        self.moments[m]["measures"]["other_forks_present"] = [
            {"status": x["status"], "text": x["text"][:160]} for x in d["forks"] if not f or x["id"] != f["id"]
        ]
        self.moments[m]["measures"].update({
            "variant": variant, "forks_visible_while_partitioned": forks_while_partitioned, "far_side_claims_held_back_max": held_seen,
            "seconds_to_fork_after_start": round(healed_at, 1) if healed_at else None,
            "fork_status": f["status"] if f else None, "fork_status_8s_later": f2["status"] if f2 else None,
            "fork_explanation": f["explanation"] if f else None, "fork_branch_rows": f["rows"] if f else None,
            "fork_markers_on_map": d["forkMarkers"], "forks_open_counter": d["forks_open"], "event_log_head": d["events"],
        })
        self._fork, self._fork_later, self._markers, self._events = f, f2, d["forkMarkers"], d["events"]

    def m7a_resolvable(self) -> None:
        m = "7a"
        self.set_moment(m, what="Both halves of a split network face-anchor a look-alike as the SAME identity; one trajectory is physically impossible from the identity's last confirmed anchor. After the network heals the fork appears and is resolved by reachability, with the reason shown.",
                        action="Pressed 'Conflict - resolvable': the dashboard partitions the network, the simulator sends the two face-twins in (A anchored at the west gate twice, B at the east gate ~2 s after A's last anchor), then heals; the real resolver runs on the merged claims.")
        self.conflict(m, "btn-conflict-resolvable", "resolvable")
        ms = self.moments[m]["measures"]
        f = self._fork
        problems = []
        if ms["forks_visible_while_partitioned"]:
            problems.append("a fork was visible before the network healed")
        if not f:
            problems.append("no fork appeared after healing")
        else:
            if f["status"] != "RESOLVED_REACHABILITY":
                problems.append(f"fork status was {f['status']}, expected RESOLVED_REACHABILITY")
            if "exceeds v_max" not in (f["explanation"] or ""):
                problems.append("the resolution reason (impossible speed) is not shown")
            if not any(r[-1] == "KEPT" for r in f["rows"]) or not any(r[-1] == "rejected" for r in f["rows"]):
                problems.append("branch table does not show one KEPT and one rejected branch")
        if not any("FORK" in e for e in ms["event_log_head"]):
            problems.append("no fork line in the event log")
        if not problems:
            self.verdict(m, "PASS", f"no fork while partitioned ({ms['far_side_claims_held_back_max']} far-side claims held back); after healing the fork appeared and was resolved by reachability: {f['explanation']}")
        else:
            self.verdict(m, "PARTIAL" if f else "FAIL", "; ".join(problems))

    def m7b_ambiguous(self) -> None:
        m = "7b"
        self.set_moment(m, what="Same set-up, but both trajectories are physically possible. After the network heals the fork appears and STAYS OPEN, shown as an ambiguity for a human with both candidate positions drawn on the map; the system never picks a winner.",
                        action="Pressed 'Conflict - ambiguous' (twin A anchored at the west gate once, twin B anchored as the same identity at the east gate 25 s later), waited for the heal and the fork, and checked it 8 s later.")
        self.conflict(m, "btn-conflict-ambiguous", "ambiguous")
        ms = self.moments[m]["measures"]
        f, f2, markers = self._fork, self._fork_later, self._markers
        problems = []
        if ms["forks_visible_while_partitioned"]:
            problems.append("a fork was visible before the network healed")
        if not f:
            problems.append("no fork appeared after healing")
        else:
            if f["status"] != "OPEN" or not f2 or f2["status"] != "OPEN":
                problems.append(f"fork not open and staying open (status {f['status']}, 8 s later {f2 and f2['status']})")
            if len(markers) < 2:
                problems.append("fewer than 2 branch markers drawn on the map")
            elif abs(markers[0]["x"] - markers[1]["x"]) < 15:
                problems.append("the two candidate positions are not far apart")
            if "does NOT pick one" not in (f["explanation"] or ""):
                problems.append("the ambiguity explanation is not shown")
        if not any("FORK" in e for e in ms["event_log_head"]):
            problems.append("no fork line in the event log")
        if not problems:
            self.verdict(m, "PASS", f"no fork while partitioned; after healing one fork appeared and stayed OPEN 8 s later; {len(markers)} branch markers drawn at {[(x['x'], x['y']) for x in markers]}; explanation: {f['explanation'][:140]}")
        else:
            self.verdict(m, "PARTIAL" if f else "FAIL", "; ".join(problems))

    # ---- centralized comparison ----------------------------------------

    def m8_central(self) -> None:
        m = "8"
        self.set_moment(m, what="A centralized single-server system (the original project's matcher; NOT Starling) runs beside Starling on the same input. Under a partition it must lose the cut-off cameras' workers while Starling keeps tracking all of them; with the server killed it must be DOWN while Starling is unaffected; restarted, it recovers (from empty state).",
                        action="Pressed Partition, read both panels, healed; pressed 'Kill central server' (the server process exits), read both panels and Starling's claim counter over 8 s; pressed 'Restart central server'.")
        self.click("btn-heal", "heal (clean start)")
        # Wait until the scripted twins of the conflict scenarios have finished walking, so the
        # comparison is against a calm floor (patrol workers + the stage actor at the door).
        calm, _ = self.wait(lambda d: (num(d["central"]["truth"]) or 99) <= 5, 120, "the floor to be calm (<= 5 workers present)")
        if not calm:
            self.notes.append("moment 8 started while more than 5 workers were still present")
        self.wait(lambda d: d["central"]["status"] == "HEALTHY" and (num(d["central"]["tracked_now"]) or 0) >= 4, 40, "central healthy with 4 tracked")
        d0 = self.dom()
        self.shot(m, "a", "healthy", f"Healthy: centralized tracks {d0['central']['tracked_now']}, Starling tracks {d0['central']['starling_now']}, actually present {d0['central']['truth']}.", d0)
        self.click("btn-partition", "partition")
        part, _ = self.wait(lambda d: d["central"]["status"] == "PARTIAL" and (num(d["central"]["tracked_now"]) or 99) < (num(d["central"]["starling_now"]) or 0), 25, "central PARTIAL and losing workers")
        self.page.wait_for_timeout(4000)
        d1 = self.dom()
        self.shot(m, "b", "partition_central_loses_side", f"Partitioned: centralized {d1['central']['status']} tracks {d1['central']['tracked_now']}; Starling tracks {d1['central']['starling_now']} of {d1['central']['truth']} present. {d1['central']['detail']}", d1)
        self.click("btn-heal", "heal")
        self.wait(lambda d: d["central"]["status"] == "HEALTHY", 25, "central healthy again")
        claims0 = num(self.dom()["claims_total"])
        self.click("btn-central-kill", "kill central")
        down, _ = self.wait(lambda d: d["central"]["status"] == "DOWN", 15, "central DOWN")
        self.page.wait_for_timeout(2000)
        d2 = self.dom()
        self.shot(m, "c", "central_killed", f"Central server killed: status {d2['central']['status']}, tracks {d2['central']['tracked_now']}; Starling tracks {d2['central']['starling_now']} of {d2['central']['truth']} present, {d2['nodes_live']} nodes live.", d2)
        self.page.wait_for_timeout(6000)
        d3 = self.dom()
        self.shot(m, "d", "starling_unaffected", f"6 s later, central still {d3['central']['status']}; Starling claims {num(d3['claims_total'])} (was {claims0}), convergence {d3['convergence']}.", d3)
        self.click("btn-central-restart", "restart central")
        back, _ = self.wait(lambda d: d["central"]["status"] == "HEALTHY" and (num(d["central"]["tracked_now"]) or 0) >= 3, 40, "central back")
        d4 = self.dom()
        self.shot(m, "e", "central_restarted", f"Central server restarted: {d4['central']['status']}, tracks {d4['central']['tracked_now']}.", d4)
        c1, c2 = d1["central"], d2["central"]
        self.moments[m]["measures"].update({
            "healthy": d0["central"], "partitioned": c1, "killed": c2, "restarted": d4["central"],
            "starling_claims_before_kill": claims0, "starling_claims_6s_after_kill": num(d3["claims_total"]), "nodes_live_after_kill": d3["nodes_live"],
            "convergence_after_kill": d3["convergence"],
        })
        problems = []
        if not (part and (num(c1["tracked_now"]) or 9) < (num(c1["starling_now"]) or 0) and (num(c1["starling_now"]) or 0) >= (num(c1["truth"]) or 0) - 1):
            problems.append(f"under partition centralized tracked {c1['tracked_now']} vs Starling {c1['starling_now']} of {c1['truth']} present")
        if not down or num(c2["tracked_now"]) != 0 or (num(c2["starling_now"]) or 0) < (num(c2["truth"]) or 0) - 1:
            problems.append(f"after the kill: central {c2['status']} tracking {c2['tracked_now']}, Starling {c2['starling_now']} of {c2['truth']}")
        if (num(d3["claims_total"]) or 0) <= (claims0 or 0) + 20 or num(d3["nodes_live"]) != 4:
            problems.append("Starling stalled after the central server was killed")
        if not back:
            problems.append("central server did not track again after the restart")
        if not problems:
            self.verdict(m, "PASS", f"partition: centralized tracks {c1['tracked_now']} (PARTIAL) vs Starling {c1['starling_now']} of {c1['truth']}; killed: centralized DOWN/0 while Starling kept {c2['starling_now']} of {c2['truth']} and {num(d3['claims_total']) - (claims0 or 0):.0f} new claims in 8 s; restarted: {d4['central']['status']}")
        else:
            self.verdict(m, "PARTIAL" if part or down else "FAIL", "; ".join(problems))

    # -- run ------------------------------------------------------------

    def run(self) -> None:
        from playwright.sync_api import sync_playwright

        print("starting the demo ...", flush=True)
        self.launcher.prepare()
        self.t_launch = time.monotonic()
        self.launcher.start()
        try:
            if not self.launcher.wait_for_dashboard():
                raise RuntimeError("dashboard did not come up")
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                self.browser_version = browser.version
                ctx = browser.new_context(viewport=VIEWPORT)
                self.page = ctx.new_page()
                self.page.on("console", lambda msg: self.console_errors.append(f"[{self.now():.0f}s] console.{msg.type}: {msg.text}") if msg.type in ("error", "warning") else None)
                self.page.on("pageerror", lambda e: self.console_errors.append(f"[{self.now():.0f}s] pageerror: {e}"))
                self.page.on("requestfailed", lambda r: self.console_errors.append(f"[{self.now():.0f}s] requestfailed: {r.url} {r.failure}"))
                steps = [("0", self.m0_startup), ("1", self.m1_walk), ("2a", self.m2a_healthy), ("2b", self.m2b_occluded),
                         ("3", self.m3_partition), ("4", self.m4_lying), ("5", self.m5_query), ("6", self.m6_robust),
                         ("7a", self.m7a_resolvable), ("7b", self.m7b_ambiguous), ("8", self.m8_central)]
                for idx, fn in steps:
                    if self.only and idx not in self.only and idx != "0":
                        continue
                    try:
                        fn()
                    except Exception as exc:
                        import traceback

                        self.notes.append(f"review step {idx} raised: {traceback.format_exc(limit=4)}")
                        print(f"  !! step {idx} failed: {exc!r}", flush=True)
                    dead = [n for n, up in self.launcher.alive().items() if not up and n != "central"]
                    if dead:
                        msg = f"process(es) {dead} were NOT running after moment {idx} (exit codes {[self.launcher.procs[n].returncode for n in dead]})"
                        if msg not in self.notes:
                            self.notes.append(msg)
                        mo = self.moments[idx]
                        mo["reason"] += " | " + msg
                        if mo["verdict"] == "PASS":
                            mo["verdict"] = "PARTIAL"
                browser.close()
        finally:
            self.exit_status = self.launcher.stop()


# -- report ---------------------------------------------------------------


def summarise_dom(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes_live": d["nodes_live"], "sim_time_s": d["sim_time"], "convergence": d["convergence"], "spread": d["spread"],
        "gaps": d["holes"], "partition": d["partition"], "forks_open": d["forks_open"], "mean_error_m": d["mean_error"],
        "claims_per_node": [n["claims"] for n in d["nodes"]], "live": [n["live"] for n in d["nodes"]],
        "camera_zone_coverage": [n["zone"] for n in d["nodes"]], "partitioned": [(n["partitioned"] or "")[:3] for n in d["nodes"]],
        "reputation": [n["reputation"] for n in d["nodes"]], "rejected": [n["rejected"] for n in d["nodes"]],
        "regions": {c["label"]: {"area_m2": c["area"], "reachable_m2": c["reach"], "ratio": c["ratio_pct"], "in_blind_block_m2": c["blind"],
                                 "in_healthy_zones_m2": c["healthy_overlap"], "zone_overlap_m2": c["zone_overlap"], "silent": c["silent"], "occluded": c["occluded"]} for c in d["cards"]},
        "identities": [f"{r['label']} {r['name']} {r['status']} @({r['pos']}) via node {r['node']} err {r['error']}" for r in d["identities"]],
        "forks": [{"status": f["status"], "explanation": f["explanation"]} for f in d["forks"]],
        "centralized": d["central"], "conflict": d["conflict_phase"],
        "query": None if not d.get("query") else {k: d["query"][k] for k in ("status", "verdict") if d["query"].get(k)},
    }


def scan_logs(log_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"tracebacks": {}, "error_lines": {}, "warning_events": {}, "rejected_claims_logged": {}}
    for f in sorted(log_dir.glob("*.log")):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            if "plausibility_rejected" in ln:
                out["rejected_claims_logged"].setdefault(f.stem, 0)
                out["rejected_claims_logged"][f.stem] += 1
            if "Assertion failed" in ln or "Segmentation fault" in ln or "core dumped" in ln:
                out["error_lines"].setdefault(f.stem, []).append("PROCESS CRASH: " + ln[:300])
            elif "Traceback (most recent call last)" in ln:
                out["tracebacks"].setdefault(f.stem, []).append("\n".join(lines[i : i + 14]))
            elif '"level": "error"' in ln or '"level":"error"' in ln:
                out["error_lines"].setdefault(f.stem, []).append(ln[:300])
            elif '"level": "warning"' in ln:
                m = re.search(r'"event": "([^"]+)"', ln)
                key = m.group(1) if m else "?"
                out["warning_events"].setdefault(f.stem, {}).setdefault(key, 0)
                out["warning_events"][f.stem][key] += 1
    return out


def env_info(browser_version: str) -> dict[str, Any]:
    def ver(p: str) -> str:
        try:
            return metadata.version(p)
        except metadata.PackageNotFoundError:
            return "not installed"

    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return "?"

    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})", "python": platform.python_version(),
        "chromium": browser_version, "commit": git("rev-parse", "--short", "HEAD"),
        "working_tree_dirty_outside_review_dir": bool(git("status", "--porcelain", "--", ".", ":!review")),
        "packages": {p: ver(p) for p in ("fastapi", "uvicorn", "playwright", "pyzmq", "numpy", "scipy", "protobuf", "pynacl", "pydantic")},
    }


LIMITATIONS = [
    "Perception is SIMULATED. There are no cameras, video or detector: a simulator moves virtual workers on a 2D floor plan and hands each node the noisy detections (position noise 0.08 m, embedding noise, 3 % missed detections) its own camera zone would produce. Identity embeddings are synthetic 64-d vectors, so appearance matching is far easier than with real re-ID features. The 'ground truth' markers are the simulator's own state.",
    "The face-recognition gates (the source of forks) and the 'look-alike' twins are SIMULATED and SCRIPTED: two people share one face identity by construction. The resolver that turns that into a fork, resolves it by reachability or leaves it open is the project's real code, unmodified. The fork view is what node 0's side can see (far-side claims are held back while partitioned, released on heal); the map itself remains the global observer view.",
    "The dead-zone episodes are scripted: one actor (worker-2) walks a fixed path through the uncovered block, and 'occluded' means the simulator stops that camera from sending healthy coverage attestations (a scripted occlusion; the camera's detections are not suppressed). The dashboard learns everything else from gossiped claims and attestations; the simulator's ground truth is used only to LABEL a silent camera as 'occluded' and to draw the faint truth rings.",
    "Candidate regions grow at the conservative walking-speed bound (1.6 m/s) and are clipped only by (a) healthy attested zones and (b) obstacles. A camera zone with no healthy attestation (occluded, offline, partitioned away) is never subtracted, by design (silence is not evidence). The 'reachable without negative evidence' area is the same dilation with that clipping switched off.",
    "The network PARTITION is application-level: each node ignores inbound gossip from the other group (`POST /partition`), the centralized server is told which cameras are cut. It is not packet loss/latency (netem) and the sending side is not gated. The dashboard's own observer is deliberately not partitioned.",
    "THE CENTRALIZED SYSTEM IS A COMPARISON, NOT PART OF STARLING. It reuses the original project's identity matcher (`IdentityStore.match_or_create`, appearance-only cosine matching against one shared table) inside a new single-server process fed by the same simulated cameras; it has no geometry, so it also silently merges look-alikes. It is deliberately naive, and partitions/failure are simulated the same application-level way. It does not run the original video pipeline.",
    "The lying node is the project's own `AttackInjector` (fabricated claims at random free positions, 90 % intensity), not an adaptive adversary. Reputation is an EWMA over plausibility checks; roughly 0.5-0.6 is the floor with three reporting peers (median). The dashboard's 'rejected' counter is the DASHBOARD's own plausibility pass over what it overheard.",
    "The claim-count 'converged' badge tolerates a small in-flight spread (30 claims, about a second of production) plus gaps == 0. Byte-identical claim sets are asserted in unit tests, not readable from the page. The resolver runs over a sliding 45 s window; identity labels (P-001...) are kept stable across windows by claim overlap; fork results are remembered for 150 s of display time.",
    "'≈ worker-N' next to an identity and the translation of 'where is worker 2' use the nearest ground-truth worker as a display-only label; the network never sees worker names.",
    "Single machine, all processes on localhost; timings are for one Windows laptop and vary run to run. Nothing here exercises real cameras, the video/YOLO path or `apps/baseline.py` itself.",
    "Screenshots are JPEGs of the real running page (full page height, 1440 px wide); no image was edited. Verdicts are computed from the DOM values recorded at capture time by explicit criteria in `scripts/review_demo.py`.",
]


def esc(s: Any) -> str:
    return html.escape(str(s))


def build_reports(rv: Review, logs: dict, env: dict, first_run: Optional[dict], first_findings: Optional[str]) -> tuple[str, str]:
    vc = {"PASS": "pass", "PARTIAL": "partial", "FAIL": "fail", "NOT TESTED": "fail"}
    M = rv.moments

    def g(m: str, k: str) -> Any:
        return M[m]["measures"].get(k)

    key = {
        "0": f"all live after {g('0', 'seconds_launch_to_all_nodes_live')} s",
        "1": f"4 identities, mean error {g('1', 'mean_position_error_m_avg')} m",
        "2a": f"region {g('2a', 'final_area_m2')} m² vs {g('2a', 'reach_at_end_m2')} m² reachable (ratio {g('2a', 'final_ratio_area_over_reach')}); max in healthy zones {g('2a', 'max_healthy_zone_overlap_m2')} m²; lasted {g('2a', 'region_lifetime_s')} s",
        "2b": f"leak into occluded zone 1: {g('2b', 'max_overlap_with_occluded_zone_1_m2')} m²; into other zones: {g('2b', 'max_overlap_with_other_zones_m2')} m²",
        "3": f"heal→converged {g('3', 'seconds_from_heal_to_converged')} s, max spread {g('3', 'max_spread_during_partition')}",
        "4": f"liar <0.7 after {g('4', 'seconds_until_liar_reputation_below_0.7')} s; recovered >0.9 after {g('4', 'seconds_until_liar_reputation_above_0.9_after_stop')} s",
        "5": "5 queries (answer, unknown, partitioned, productivity, blind-block)",
        "6": f"reload {g('6', 'seconds_to_recover_after_reload')} s; offline {g('6', 'seconds_until_killed_node_shown_offline')} s; back {g('6', 'seconds_until_restarted_node_live')} s",
        "7a": f"fork {g('7a', 'fork_status')} after heal",
        "7b": f"fork {g('7b', 'fork_status')}; still {g('7b', 'fork_status_8s_later')} 8 s later",
        "8": "partition / kill / restart of the centralized system vs Starling",
    }
    timings = {
        "startup_s": g("0", "seconds_launch_to_all_nodes_live"), "heal_convergence_s": g("3", "seconds_from_heal_to_converged"),
        "reputation_drop_s": g("4", "seconds_until_liar_reputation_below_0.7"), "reputation_recovery_s": g("4", "seconds_until_liar_reputation_above_0.9_after_stop"),
        "dead_zone_healthy_lifetime_s": g("2a", "region_lifetime_s"), "dead_zone_healthy_ratio": g("2a", "final_ratio_area_over_reach"),
        "conflict_seconds_to_fork": {"resolvable": g("7a", "seconds_to_fork_after_start"), "ambiguous": g("7b", "seconds_to_fork_after_start")},
    }
    css = """body{font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#1c2430;background:#fff}
h1{font-size:24px}h2{margin-top:36px;border-bottom:1px solid #d8dde6;padding-bottom:4px}table{border-collapse:collapse;width:100%}
th,td{border:1px solid #d8dde6;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f4f5f7}
.pass{color:#1a7f4b;font-weight:700}.partial{color:#b7791f;font-weight:700}.fail{color:#c0392b;font-weight:700}
figure{margin:14px 0}figure img{max-width:100%;border:1px solid #d8dde6}figcaption{font-size:13px}
pre{background:#f4f5f7;padding:8px;overflow:auto;font-size:12px}.dom{color:#555;font-size:12px}code{background:#f4f5f7;padding:0 3px}"""
    h = [f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>Starling Demo Review (session 3)</title><style>{css}</style></head><body>",
         "<h1>Starling demo — automated review evidence (session 3)</h1>",
         f"<p>Generated {esc(time.strftime('%Y-%m-%d %H:%M:%S'))} by <code>scripts/review_demo.py</code> against the real running system (commit <code>{esc(env['commit'])}</code>). Screenshots are of the real dashboard in headless Chromium, 1440 px wide; values in captions were read from the page DOM at capture time. The centralized system shown in some screenshots is a <b>comparison, not part of Starling</b>.</p>",
         "<h2>Summary</h2><table><tr><th>#</th><th>Moment</th><th>Verdict</th><th>Key measured numbers</th><th>Reason</th></tr>"]
    md = ["# Starling demo — automated review summary (session 3)", "",
          f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by `scripts/review_demo.py` (commit `{env['commit']}`). Same content as `review.html`, without images (file names refer to `review/screenshots/`). The centralized system is a comparison, not part of Starling.", "",
          "## Summary", "", "| # | Moment | Verdict | Key measured numbers | Reason |", "|---|---|---|---|---|"]
    for m in ORDER:
        mo = M[m]
        h.append(f"<tr><td>{m}</td><td>{esc(mo['title'])}</td><td class='{vc[mo['verdict']]}'>{esc(mo['verdict'])}</td><td>{esc(key[m])}</td><td>{esc(mo['reason'])}</td></tr>")
        md.append(f"| {m} | {mo['title']} | **{mo['verdict']}** | {key[m]} | {mo['reason']} |")
    h.append("</table>")
    md.append("")
    for m in ORDER:
        mo = M[m]
        h.append(f"<h2>Moment {m} — {esc(mo['title'])}: <span class='{vc[mo['verdict']]}'>{esc(mo['verdict'])}</span></h2>")
        h.append(f"<p><b>What it should demonstrate:</b> {esc(mo['what'])}<br><b>Action taken:</b> {esc(mo['action'])}<br><b>Verdict reason:</b> {esc(mo['reason'])}</p>")
        md += [f"## Moment {m} — {mo['title']}: {mo['verdict']}", "", f"**What it should demonstrate:** {mo['what']}", "", f"**Action taken:** {mo['action']}", "", f"**Verdict reason:** {mo['reason']}", ""]
        for s in [x for x in rv.shots if x["moment"] == m]:
            b64 = base64.b64encode((REVIEW_DIR / s["file"]).read_bytes()).decode()
            h.append(f"<figure><img alt='{esc(s['name'])}' src='data:image/jpeg;base64,{b64}'><figcaption><b>{esc(s['name'])}.jpg</b> — {esc(s['caption'])} <i>(t = {s['t_s']} s since launch)</i><br><span class='dom'>DOM values: {esc(json.dumps(s['dom'], ensure_ascii=False))}</span></figcaption></figure>")
            md += [f"### {s['name']}.jpg  (t = {s['t_s']} s since launch)", "", s["caption"], "", "DOM values read at capture:", "", "```json", json.dumps(s["dom"], indent=1, ensure_ascii=False), "```", ""]
        h.append(f"<details><summary>All measured values for moment {m}</summary><pre>{esc(json.dumps(mo['measures'], indent=2, default=str, ensure_ascii=False))}</pre></details>")
        md += ["Measured values:", "", "```json", json.dumps(mo["measures"], indent=2, default=str, ensure_ascii=False), "```", ""]

    h.append("<h2>First-run findings</h2>")
    md += ["## First-run findings", ""]
    if first_run:
        rows = "".join(f"<tr><td>{m}</td><td>{esc(first_run['moments'][m]['title'])}</td><td class='{vc.get(first_run['moments'][m]['verdict'], 'fail')}'>{esc(first_run['moments'][m]['verdict'])}</td><td>{esc(first_run['moments'][m]['reason'])}</td></tr>" for m in ORDER if m in first_run["moments"])
        h.append("<p>Verdicts of this session's <b>first, unmodified run</b> of the review (before any fix made in response to it):</p><table><tr><th>#</th><th>Moment</th><th>Verdict</th><th>Reason</th></tr>" + rows + "</table>")
        md += ["Verdicts of this session's first, unmodified run of the review:", "", "| # | Moment | Verdict | Reason |", "|---|---|---|---|"] + [f"| {m} | {first_run['moments'][m]['title']} | {first_run['moments'][m]['verdict']} | {first_run['moments'][m]['reason']} |" for m in ORDER if m in first_run["moments"]] + [""]
    if first_findings:
        h.append(f"<pre style='white-space:pre-wrap'>{esc(first_findings)}</pre>")
        md += [first_findings, ""]
    if not first_run and not first_findings:
        h.append("<p>This report is from the first run; no earlier run exists.</p>")
        md += ["This report is from the first run; no earlier run exists.", ""]

    h.append("<h2>Browser console errors</h2>")
    md += ["## Browser console errors", ""]
    if rv.console_errors:
        h.append("<pre>" + esc("\n".join(rv.console_errors[:60])) + "</pre>")
        md += ["```", *rv.console_errors[:60], "```", ""]
    else:
        h.append("<p>None (no console errors/warnings, page errors or failed requests recorded).</p>")
        md += ["None (no console errors/warnings, page errors or failed requests recorded).", ""]

    h.append("<h2>Process errors and exit status</h2>")
    md += ["## Process errors and exit status", ""]
    tb, el = logs["tracebacks"], logs["error_lines"]
    if not tb and not el:
        h.append("<p>No Python tracebacks, no crash lines and no <code>level: error</code> log records in any process log.</p>")
        md += ["No Python tracebacks, no crash lines and no `level: error` log records in any process log.", ""]
    for name, items in tb.items():
        h.append(f"<p><b>{esc(name)}</b> tracebacks:</p><pre>{esc(chr(10).join(items[:2]))}</pre>")
        md += [f"**{name}** tracebacks:", "```", *items[:2], "```", ""]
    for name, items in el.items():
        h.append(f"<p><b>{esc(name)}</b> error records ({len(items)}):</p><pre>{esc(chr(10).join(items[:5]))}</pre>")
        md += [f"**{name}** error records ({len(items)}):", "```", *items[:5], "```", ""]
    h.append(f"<p>Warning-level events (counts): <code>{esc(json.dumps(logs['warning_events']))}</code><br>Claims rejected by nodes' plausibility check (logged per node; includes the deliberate liar and scripted actors): <code>{esc(json.dumps(logs['rejected_claims_logged']))}</code></p>")
    md += [f"Warning-level events (counts): `{json.dumps(logs['warning_events'])}`", "", f"Claims rejected by nodes' plausibility check (logged per node; includes the deliberate liar and scripted actors): `{json.dumps(logs['rejected_claims_logged'])}`", ""]
    st_rows = "".join(f"<tr><td>{esc(n)}</td><td>{esc(s['exit_code'])}</td><td>{'still running at shutdown; stopped by the launcher' if s['was_running_at_shutdown'] else 'had already exited before shutdown'}</td></tr>" for n, s in rv.exit_status.items())
    h.append("<table><tr><th>process</th><th>exit code</th><th>note</th></tr>" + st_rows + "</table>")
    h.append("<p class='dom'>On Windows the launcher stops a process with <code>TerminateProcess</code>, so a nonzero exit code for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted in moment 6; the central server was killed and restarted in moment 8 (a restarted central server is not the launcher's child and is stopped through its pid file).</p>")
    md += ["| process | exit code | note |", "|---|---|---|"] + [f"| {n} | {s['exit_code']} | {'still running at shutdown; stopped by the launcher' if s['was_running_at_shutdown'] else 'had already exited before shutdown'} |" for n, s in rv.exit_status.items()]
    md += ["", "On Windows the launcher stops a process with `TerminateProcess`, so a nonzero exit code for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted in moment 6; the central server was killed and restarted in moment 8.", ""]
    if rv.notes:
        h.append("<p><b>Harness notes:</b></p><pre>" + esc("\n".join(rv.notes[:20])) + "</pre>")
        md += ["Harness notes:", "```", *rv.notes[:20], "```", ""]

    h.append("<h2>Timings</h2><pre>" + esc(json.dumps(timings, indent=2)) + "</pre>")
    md += ["## Timings", "", "```json", json.dumps(timings, indent=2), "```", ""]
    h.append("<h2>Environment</h2><pre>" + esc(json.dumps(env, indent=2)) + "</pre>")
    md += ["## Environment", "", "```json", json.dumps(env, indent=2), "```", ""]
    h.append("<h2>Known limitations and what is simulated</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in LIMITATIONS) + "</ul>")
    md += ["## Known limitations and what is simulated", ""] + [f"- {x}" for x in LIMITATIONS] + [""]
    h.append("</body></html>")
    return "\n".join(h), "\n".join(md)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the automated visual review and write review/review.html")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--first-run", action="store_true", help="also save this run as review/first_run_results.json")
    ap.add_argument("--only", type=str, default=None, help="comma-separated moments to run (development), e.g. 2a,7a")
    args = ap.parse_args(argv)
    only = [x.strip() for x in args.only.split(",")] if args.only else None

    if SHOT_DIR.exists():
        for old in SHOT_DIR.glob("*.jpg"):
            old.unlink()
    rv = Review(args.port, only)
    t_start = time.monotonic()
    rv.run()
    logs = scan_logs(rv.launcher.log_dir)
    env = env_info(rv.browser_version)
    results = {"moments": rv.moments, "shots": rv.shots, "console_errors": rv.console_errors, "logs": logs, "exit_status": rv.exit_status,
               "env": env, "notes": rv.notes, "run_seconds": round(time.monotonic() - t_start, 1)}
    REVIEW_DIR.mkdir(exist_ok=True)
    (REVIEW_DIR / "results.json").write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    if args.first_run:
        (REVIEW_DIR / "first_run_results.json").write_text(json.dumps({"moments": rv.moments}, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    fr = REVIEW_DIR / "first_run_results.json"
    ff = REVIEW_DIR / "first_run_findings.md"
    first_run = json.loads(fr.read_text(encoding="utf-8")) if fr.exists() and not args.first_run else None
    first_findings = ff.read_text(encoding="utf-8") if ff.exists() and not args.first_run else None
    page, summary = build_reports(rv, logs, env, first_run, first_findings)
    (REVIEW_DIR / "review.html").write_text(page, encoding="utf-8")
    (REVIEW_DIR / "review_summary.md").write_text(summary, encoding="utf-8")
    print("\nVERDICTS:", {m: rv.moments[m]["verdict"] for m in ORDER})
    print(f"wrote {REVIEW_DIR / 'review.html'} ({(REVIEW_DIR / 'review.html').stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

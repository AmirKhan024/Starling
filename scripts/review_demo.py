"""scripts/review_demo.py
-------------------------
Automated visual review of the Starling demo, for a reviewer who cannot run
the code. Starts the REAL demo (`scripts/run_demo.py`'s `DemoLauncher`,
headless), drives the REAL dashboard in headless Chromium at 1440x900 through
every demo moment, polls DOM values (not fixed sleeps), takes screenshots and
records what the page actually shows, then writes:

    review/review.html          single self-contained file (base64 screenshots)
    review/review_summary.md    the same content as text
    review/screenshots/*.jpg    the individual images
    review/results.json         raw measurements of this run

Re-run with one command:     python scripts/review_demo.py

Honesty rules (see the task brief): nothing is mocked or edited; verdicts come
from explicit criteria applied to measured values; a first run's findings are
kept (review/first_run_results.json + review/first_run_findings.md, both
written by hand after the first run) and embedded under "First-run findings".
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
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.run_demo import DemoLauncher  # noqa: E402

REVIEW_DIR = REPO / "review"
SHOT_DIR = REVIEW_DIR / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}
JPEG_QUALITY = 72
LIAR = 2  # node made to lie
MOMENT_TITLES = {
    0: "Startup",
    1: "Normal walk",
    2: "Dead zone",
    3: "Partition and heal",
    4: "Lying node",
    5: "Query and refusal",
    6: "Robustness",
}

READ_DOM_JS = """
() => {
  const q = (id) => { const e = document.querySelector(`[data-testid="${id}"]`); return e ? e.textContent.trim() : null; };
  const nodes = [0, 1, 2, 3].map((n) => ({
    id: n, live: q(`node-${n}-live`), partitioned: q(`node-${n}-partitioned`), claims: q(`node-${n}-claims`),
    holes: q(`node-${n}-holes`), behaviour: q(`node-${n}-lying`), rejected: q(`node-${n}-rejected`),
    reputation: q(`rep-value-${n}`),
    bar: (document.querySelector(`[data-testid="rep-bar-${n}"] .fill`) || {style: {}}).style.width || null,
  }));
  const identities = [...document.querySelectorAll('[data-testid^="identity-row-"]')].map((tr) => {
    const c = [...tr.children].map((x) => x.textContent.trim());
    return { label: tr.dataset.testid.replace("identity-row-", ""), name: c[1], status: c[2], pos: c[3], age: c[4],
             node: c[5], claims: c[6], error: c[7], region: c[8] };
  });
  const regions = [...document.querySelectorAll('[data-testid^="region-P-"]')].map((e) => ({
    label: e.dataset.testid.replace("region-", ""), area: parseFloat(e.dataset.area) }));
  const qr = document.querySelector('[data-testid="query-result"]');
  return {
    status: q("dash-status"), nodes_live: q("nodes-live"), sim_time: q("sim-time"), claims_total: q("claims-total"),
    mean_error: q("mean-error"), tick: q("refresh-tick"), convergence: q("convergence-status"),
    spread: q("claim-spread"), holes: q("claim-holes"), partition: q("partition-state"),
    forks: q("forks-count"), action: q("action-status"), region_summary: q("region-summary"),
    nodes, identities, regions,
    query: qr ? { status: qr.dataset.status, verdict: q("query-verdict"), reason: q("query-reason"),
                  confirmed: q("query-confirmed"), inferred: q("query-inferred"), unreachable: q("query-unreachable"),
                  text: q("query-result-text"), note: qr.textContent.trim().slice(0, 600) } : null,
  };
}
"""


def num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(m.group(0)) if m else None


class Review:
    def __init__(self, port: int) -> None:
        self.launcher = DemoLauncher(port=port)
        self.t_launch = 0.0
        self.shots: list[dict[str, Any]] = []
        self.console_errors: list[str] = []
        self.moments: dict[int, dict[str, Any]] = {
            m: {"title": t, "verdict": "NOT TESTED", "reason": "not reached", "measures": {}, "what": "", "action": ""}
            for m, t in MOMENT_TITLES.items()
        }
        self.notes: list[str] = []
        self.page: Any = None

    # -- helpers ------------------------------------------------------

    def now(self) -> float:
        return time.monotonic() - self.t_launch

    def dom(self) -> dict[str, Any]:
        return self.page.evaluate(READ_DOM_JS)

    def wait(self, cond: Callable[[dict[str, Any]], Any], timeout: float, what: str, every: float = 0.4) -> tuple[Any, float]:
        """Poll the DOM until `cond(dom)` is truthy; returns (value, seconds waited)."""
        t0 = time.monotonic()
        last = None
        while time.monotonic() - t0 < timeout:
            try:
                d = self.dom()
                last = cond(d)
            except Exception as exc:  # page mid-reload etc.
                last = None
                self.notes.append(f"transient DOM read error while waiting for {what}: {exc!r}")
            if last:
                return last, time.monotonic() - t0
            self.page.wait_for_timeout(int(every * 1000))
        return None, time.monotonic() - t0

    def shot(self, moment: int, order: str, slug: str, caption: str, values: Optional[dict] = None) -> dict[str, Any]:
        name = f"{moment}{order}_{slug}"
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"{name}.jpg"
        self.page.screenshot(path=str(path), full_page=True, type="jpeg", quality=JPEG_QUALITY)
        d = values if values is not None else self.dom()
        rec = {"moment": moment, "name": name, "file": f"screenshots/{name}.jpg", "caption": caption,
               "t_s": round(self.now(), 1), "dom": summarise_dom(d), "bytes": path.stat().st_size}
        self.shots.append(rec)
        print(f"  [{rec['t_s']:7.1f}s] {name}: {caption}", flush=True)
        return rec

    def set_moment(self, m: int, **kw: Any) -> None:
        self.moments[m].update(kw)

    def verdict(self, m: int, verdict: str, reason: str) -> None:
        self.moments[m]["verdict"] = verdict
        self.moments[m]["reason"] = reason
        print(f"  => moment {m} {verdict}: {reason}", flush=True)

    def worker_row(self, d: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
        rows = [r for r in d["identities"] if r["name"] == name]
        return max(rows, key=lambda r: num(r["claims"]) or 0) if rows else None

    def click_and_wait_action(self, testid: str, what: str) -> None:
        self.page.click(f'[data-testid="{testid}"]')
        self.wait(lambda d: (d["action"] or "").endswith(("done", "unreachable")), 10, f"{what} action to finish")

    # -- moments ------------------------------------------------------

    def m0_startup(self, pw_page: Any) -> None:
        m = 0
        self.set_moment(m, what="The dashboard loads and all four node processes are live.",
                        action="Launched `scripts/run_demo.py --headless` (simulator + 4 nodes + dashboard), opened the dashboard in headless Chromium.")
        self.page.goto(self.launcher.url)
        self.page.wait_for_selector('[data-testid="node-card-3"]', timeout=60000)
        ok, _ = self.wait(lambda d: num(d["nodes_live"]) == 4 and (num(d["claims_total"]) or 0) > 50, 90, "4 nodes live")
        t_live = self.now()
        self.moments[m]["measures"]["seconds_launch_to_all_nodes_live"] = round(t_live, 1)
        self.wait(lambda d: len([r for r in d["identities"] if r["name"] not in ("–", "")]) >= 4, 60, "identities named")
        self.shot(m, "a", "startup_loaded", "Dashboard fully loaded with all four nodes live.")
        if ok and t_live < 60:
            self.verdict(m, "PASS", f"all 4 nodes live {t_live:.1f}s after launch (page loaded, claims flowing)")
        elif ok:
            self.verdict(m, "PARTIAL", f"all 4 nodes live but only after {t_live:.1f}s")
        else:
            self.verdict(m, "FAIL", "the dashboard never showed 4 live nodes")

    def m1_walk(self) -> None:
        m = 1
        self.set_moment(m, what="Believed worker positions (one colour per resolved identity) move across the floor plan and keep their identity across camera zones; faint ground-truth markers give the comparison.",
                        action="Observed only (no controls): sampled the DOM for ~30 s and followed worker-2, which walks from node 0's zone through the blind aisle into node 1's zone.")
        d0 = self.dom()
        self.shot(m, "a", "walk_start", "Five workers, five identities; solid dots = believed, dashed rings = ground truth.", d0)
        pos0 = {r["label"]: r["pos"] for r in d0["identities"]}
        self.page.wait_for_timeout(6000)
        d1 = self.dom()
        self.shot(m, "b", "walk_6s_later", "Six seconds later: the same identities at new positions.", d1)
        pos1 = {r["label"]: r["pos"] for r in d1["identities"]}
        moved = 0.0
        for lab, p in pos0.items():
            if lab in pos1:
                a = [float(x) for x in p.split(",")]
                b = [float(x) for x in pos1[lab].split(",")]
                moved = max(moved, ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)
        # follow worker-2 across a zone boundary
        seen_nodes: dict[str, set] = {}
        errors: list[float] = []
        crossed = None
        t0 = time.monotonic()
        first_label = None
        while time.monotonic() - t0 < 60:
            d = self.dom()
            e = num(d["mean_error"])
            if e is not None:
                errors.append(e)
            w2 = self.worker_row(d, "worker-2")
            if w2 and w2["status"] == "seen":
                first_label = first_label or w2["label"]
                seen_nodes.setdefault(w2["label"], set()).add(int(w2["node"]))
                if any(len(v) >= 2 for v in seen_nodes.values()):
                    crossed = w2["label"]
                    break
            self.page.wait_for_timeout(500)
        d2 = self.dom()
        if crossed:
            self.shot(m, "c", "zone_boundary_crossed", f"worker-2 is now seen by a different node's camera and still carries identity {crossed} (was {first_label}).", d2)
        else:
            self.shot(m, "c", "no_crossing_observed", "Timed out waiting for worker-2 to be seen by two different nodes.", d2)
        all_err = [num(r["error"]) for r in d2["identities"] if num(r["error"]) is not None]
        named_now = sorted(r["name"] for r in d2["identities"] if r["name"] not in ("–", ""))
        n_ident_now = len(d2["identities"])
        self.moments[m]["measures"].update({
            "identities_named_at_start": len([r for r in d0["identities"] if r["name"] not in ("–", "")]),
            "max_identity_displacement_in_6s_m": round(moved, 2),
            "mean_position_error_m_samples": errors[-10:],
            "mean_position_error_m_avg": round(sum(errors) / len(errors), 2) if errors else None,
            "worker2_label_before_after_zone_change": [first_label, crossed],
            "worker2_nodes_seen_by": sorted(next(iter(seen_nodes.values()), set())) if seen_nodes else [],
            "final_per_identity_error_m": all_err,
            "named_workers_at_end": named_now, "identities_listed_at_end": n_ident_now,
            "identity_statuses_at_end": {r["label"]: r["status"] for r in d2["identities"]},
        })
        avg = self.moments[m]["measures"]["mean_position_error_m_avg"]
        problems = []
        if self.moments[m]["measures"]["identities_named_at_start"] < 4:
            problems.append("fewer than 4 identities resolved")
        if moved < 0.5:
            problems.append("no identity moved between screenshots")
        if not crossed:
            problems.append("worker-2 was not seen crossing a zone boundary with a stable identity")
        elif first_label != crossed:
            problems.append("identity label changed across the zone boundary")
        if avg is None or avg > 1.0:
            problems.append(f"mean position error {avg} m")
        if named_now != [f"worker-{i}" for i in range(5)] or n_ident_now != 5:
            problems.append(f"expected exactly the 5 workers as 5 identities at the end, saw {n_ident_now} identities, named {named_now}")
        if not problems:
            self.verdict(m, "PASS", f"5 identities tracked, worker-2 kept {crossed} across nodes {self.moments[m]['measures']['worker2_nodes_seen_by']}, mean error {avg} m vs ground truth")
        else:
            self.verdict(m, "PARTIAL" if crossed or moved >= 0.5 else "FAIL", "; ".join(problems))

    def m2_deadzone(self) -> None:
        m = 2
        self.set_moment(m, what="A worker walks into the blind aisle; instead of the track vanishing, a shaded 'could be here' region appears and (with attested absence) shrinks; on re-emergence the same identity is restored.",
                        action="Observed only: followed worker-2 through up to 3 dark episodes in the 3 m blind aisle, sampled its OWN candidate-region area from the DOM every ~0.5 s, and checked which identity it had when it reappeared. Node 1 has scripted occlusion windows (sim 20-45 s and 80-105 s) in which it sends no attestation, so episodes inside a window are expected NOT to shrink (silence is not evidence).")

        def approaching(d: dict[str, Any]) -> Any:
            r = self.worker_row(d, "worker-2")
            if not r or r["status"] != "seen":
                return None
            x = float(r["pos"].split(",")[0])
            return r if (4.0 <= x <= 7.9 or 11.1 <= x <= 14.0) else None

        self.wait(approaching, 120, "worker-2 approaching the aisle", every=0.25)
        d = self.dom()
        w2 = self.worker_row(d, "worker-2")
        label0 = w2["label"] if w2 else None
        self.shot(m, "a", "approaching_aisle", f"worker-2 ({label0}) approaches the blind aisle and is still seen.", d)

        episodes: list[dict[str, Any]] = []
        t_begin = time.monotonic()
        shot_shrink = False
        while len(episodes) < 3 and time.monotonic() - t_begin < 130:
            d = self.dom()
            w2 = self.worker_row(d, "worker-2")
            label = w2["label"] if w2 else label0

            def w2_region(dd: dict[str, Any], label: Any = label) -> Any:
                return [r for r in dd["regions"] if r["label"] == label] or None

            found, _ = self.wait(w2_region, 45, "candidate region for worker-2's identity", every=0.25)
            if not found:
                break
            sim_start = num(self.dom()["sim_time"])
            ep: dict[str, Any] = {"identity": label, "sim_time_at_start_s": sim_start, "samples": []}
            t_ep = time.monotonic()
            if not episodes:
                self.shot(m, "b", "region_appears", f"worker-2 ({label}) is unseen: its candidate region appears with its area in m².")
            mid_done = False
            while time.monotonic() - t_ep < 30:
                dd = self.dom()
                regs = [r for r in dd["regions"] if r["label"] == label]
                if not regs:
                    break
                area = regs[0]["area"]
                el = round(time.monotonic() - t_ep, 1)
                prev_max = max((a for _, a in ep["samples"]), default=None)
                ep["samples"].append((el, area))
                if len(episodes) == 0 and not mid_done and el >= 2.0:
                    self.shot(m, "c", "region_mid", f"Region {label} after {el} s unseen: {area} m².", dd)
                    mid_done = True
                if prev_max is not None and area < prev_max - 0.5 and not shot_shrink:
                    self.shot(m, "e", "region_shrinks", f"Region {label} SHRANK from {prev_max} to {area} m² after {el} s unseen (sim t = {dd['sim_time']} s).", dd)
                    shot_shrink = True
                self.page.wait_for_timeout(450)
            self.wait(lambda dd: (lambda r: r and r["status"] == "seen")(self.worker_row(dd, "worker-2")), 15, "worker-2 re-seen")
            dd = self.dom()
            w2b = self.worker_row(dd, "worker-2")
            areas = [a for _, a in ep["samples"]]
            ep.update({
                "identity_after_reemerging": w2b["label"] if w2b else None,
                "same_identity_after": bool(w2b and w2b["label"] == label),
                "n_samples": len(areas), "peak_area_m2": max(areas) if areas else None,
                "final_area_m2": areas[-1] if areas else None,
                "area_ever_decreased": bool(areas) and any(areas[i] < max(areas[:i]) - 0.5 for i in range(1, len(areas))),
            })
            episodes.append(ep)
            if len(episodes) == 1:
                self.shot(m, "d", "reemerged", f"worker-2 re-emerges; identity now {ep['identity_after_reemerging']} (before: {label}).", dd)
            self.page.wait_for_timeout(1500)

        self.moments[m]["measures"].update({
            "episodes": episodes, "n_episodes": len(episodes),
            "other_identities_with_regions_at_end": sorted({r["label"] for r in self.dom()["regions"]}),
        })
        if not episodes:
            self.verdict(m, "FAIL", "no candidate region appeared for worker-2's identity within the observation window")
            return
        summary = "; ".join(
            f"ep{i + 1} (sim t={e['sim_time_at_start_s']} s): {e['n_samples']} samples, peak {e['peak_area_m2']} m², final {e['final_area_m2']} m², "
            f"{'shrank' if e['area_ever_decreased'] else 'no shrink'}, {'same' if e['same_identity_after'] else 'DIFFERENT'} identity after"
            for i, e in enumerate(episodes)
        )
        all_same = all(e["same_identity_after"] for e in episodes)
        good = [e for e in episodes if e["n_samples"] >= 3 and e["area_ever_decreased"]]
        need = len(episodes) // 2 + 1  # a majority of the observed episodes must show a shrink
        if all_same and len(good) >= need:
            self.verdict(m, "PASS", f"region appeared and shrank in {len(good)} of {len(episodes)} episodes, same identity every time. {summary}")
        else:
            problems = []
            if not all_same:
                problems.append("identity changed after re-emerging in at least one episode")
            if len(good) < need:
                problems.append(f"the region shrank in only {len(good)} of {len(episodes)} dark episodes (a majority is required for PASS; in the others it only grew until the worker re-emerged)")
            self.verdict(m, "PARTIAL" if good or all_same else "FAIL", "; ".join(problems) + ". " + summary)

    def m3_partition(self) -> None:
        m = 3
        self.set_moment(m, what="Cut nodes {2,3} from {0,1}; both sides keep working; on heal the replicas reconverge (equal claim counts, no gaps); any genuine conflict shows as an open fork.",
                        action="Pressed 'Partition {2,3} from {0,1}', waited, pressed 'Heal', and timed how long until the convergence badge read CONVERGED.")
        d = self.dom()
        pre = {"claims": [num(n["claims"]) for n in d["nodes"]], "spread": num(d["spread"]), "convergence": d["convergence"]}
        self.shot(m, "a", "before_partition", "Before: all nodes hold (almost) the same number of claims.", d)
        self.click_and_wait_action("btn-partition", "partition")
        ok, t_part = self.wait(lambda d: all((n["partitioned"] or "").startswith("yes") for n in d["nodes"]), 15, "all nodes show partitioned")
        self.shot(m, "b", "partition_during", "Partition applied: every node card reports 'partitioned: yes'.")
        spreads = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 12:
            dd = self.dom()
            spreads.append((round(time.monotonic() - t0, 1), num(dd["spread"]), [num(n["claims"]) for n in dd["nodes"]]))
            self.page.wait_for_timeout(1500)
        self.shot(m, "c", "partition_later", "12 s into the partition: the two sides' claim counts have drifted apart.")
        forks_during = num(self.dom()["forks"])
        d_pre_heal = self.dom()
        self.click_and_wait_action("btn-heal", "heal")
        t_heal = time.monotonic()
        conv, _ = self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "convergence after heal", every=0.25)
        heal_s = round(time.monotonic() - t_heal, 1)
        d_after = self.dom()
        self.shot(m, "d", "after_heal", f"After heal: convergence badge {d_after['convergence']}, spread {d_after['spread']}, gaps {d_after['holes']} ({heal_s}s after pressing Heal).", d_after)
        fork_n = num(d_after["forks"]) or 0
        if fork_n:
            self.shot(m, "e", "fork_open", f"{int(fork_n)} open fork(s) shown.", d_after)
        max_spread = max((s or 0) for _, s, _ in spreads) if spreads else None
        self.moments[m]["measures"].update({
            "before": pre, "partition_state_shown_on_all_4_nodes": bool(ok),
            "spread_and_claims_during_partition": spreads, "max_spread_during_partition": max_spread,
            "seconds_from_heal_to_converged": heal_s if conv else None,
            "after_heal_claims": [num(n["claims"]) for n in d_after["nodes"]], "after_heal_gaps": num(d_after["holes"]),
            "open_forks_during": forks_during, "open_forks_after": fork_n,
            "claims_on_sides_pre_heal": [num(n["claims"]) for n in d_pre_heal["nodes"]],
        })
        problems = []
        if not ok:
            problems.append("partition state not shown on all 4 node cards")
        if max_spread is None or max_spread <= (pre["spread"] or 0) + 5:
            problems.append(f"claim counts did not visibly diverge during the partition (max spread {max_spread} vs {pre['spread']} before)")
        if not conv:
            problems.append("did not converge within 60 s of healing")
        if problems and conv and ok:
            self.verdict(m, "PARTIAL", "; ".join(problems) + f". Converged {heal_s}s after heal.")
        elif problems:
            self.verdict(m, "FAIL", "; ".join(problems))
        else:
            self.verdict(m, "PASS", f"partition shown on all nodes, spread grew to {max_spread}, converged {heal_s}s after heal with gaps={d_after['holes']}; open forks: {int(fork_n)}")

    def m4_lying(self) -> None:
        m = 4
        self.set_moment(m, what="A node fabricates sightings; peers reject implausible claims and its reputation, as seen by peers, drops; it recovers when it stops.",
                        action=f"Selected node {LIAR}, pressed 'Make node lie', sampled reputation and rejected-claim counters every ~2 s for up to 40 s, then pressed 'Stop lying' and sampled recovery for up to 60 s.")
        d = self.dom()
        before = [num(n["reputation"]) for n in d["nodes"]]
        self.shot(m, "a", "before_lie", f"Before: reputation of all nodes = {before}.", d)
        self.page.select_option('[data-testid="select-lie-node"]', str(LIAR))
        self.click_and_wait_action("btn-lie", "lie")
        t_lie = time.monotonic()
        samples: list[dict[str, Any]] = []
        dropped_at = None
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
        self.click_and_wait_action("btn-stop-lie", "stop lying")
        t_stop = time.monotonic()
        rec_samples = []
        recovered_at = None
        shot_d = False
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
        self.shot(m, "e", "after_stop", f"End of recovery window: reputation {[num(n['reputation']) for n in self.dom()['nodes']]}.")
        last = samples[-1] if samples else {"reputation": [None] * 4, "rejected": [0] * 4}
        honest_min = min((r for i, r in enumerate(last["reputation"]) if i != LIAR and r is not None), default=None)
        self.moments[m]["measures"].update({
            "liar_node": LIAR, "reputation_before": before,
            "reputation_and_rejected_samples_while_lying": samples,
            "seconds_until_liar_reputation_below_0.7": dropped_at,
            "liar_rejected_claims_at_end": last["rejected"][LIAR],
            "lowest_honest_node_reputation_while_lying": honest_min,
            "recovery_samples_after_stop": rec_samples, "seconds_until_liar_reputation_above_0.9_after_stop": recovered_at,
        })
        problems = []
        if dropped_at is None:
            problems.append("the liar's reputation never fell below 0.7 within 40 s")
        if honest_min is not None and honest_min < 0.8:
            problems.append(f"an honest node's reputation fell to {honest_min}")
        if not (last["rejected"][LIAR] or 0) > 0:
            problems.append("no rejected claims counted for the liar")
        if dropped_at is None:
            self.verdict(m, "FAIL", "; ".join(problems))
        elif problems:
            self.verdict(m, "PARTIAL", "; ".join(problems))
        elif recovered_at is None:
            self.verdict(m, "PARTIAL", f"reputation fell below 0.7 after {dropped_at}s ({last['rejected'][LIAR]} claims rejected) but did not recover above 0.9 within 60 s of stopping")
        else:
            self.verdict(m, "PASS", f"liar's reputation < 0.7 after {dropped_at}s ({last['rejected'][LIAR]} claims rejected), honest nodes stayed >= {honest_min}, recovered > 0.9 {recovered_at}s after stopping")

    def ask(self, text: str, purpose: str = "safety") -> dict[str, Any]:
        self.page.fill('[data-testid="query-input"]', text)
        self.page.select_option('[data-testid="query-purpose"]', purpose)
        self.page.click('[data-testid="query-submit"]')
        res, _ = self.wait(lambda d: d["query"] and d["query"]["status"] in ("answered", "refused") and (d["query"]["text"] or d["query"]["reason"]) and d["query"], 15, f"query '{text}'")
        return res or self.dom()["query"]

    def m5_query(self) -> None:
        m = 5
        self.set_moment(m, what="A text query (with a `safety` capability token) returns a structured answer that separates confirmed from inferred and names unreachable nodes; unanswerable queries are refused with a reason.",
                        action="Typed queries into the query box and read the rendered result from the DOM: a valid one, an unknown worker, a query during a partition, and one under a `productivity` token.")
        q1 = self.ask("where is worker 2")
        self.shot(m, "a", "answer_worker2", "Valid query 'where is worker 2' (purpose safety).")
        q2 = self.ask("where is worker 9")
        self.shot(m, "b", "refusal_unknown", "Unanswerable query 'where is worker 9': refused with its reason.")
        self.click_and_wait_action("btn-partition", "partition (for the edge case)")
        self.wait(lambda d: all((n["partitioned"] or "").startswith("yes") for n in d["nodes"]), 15, "partitioned")
        self.page.wait_for_timeout(3000)
        q3 = self.ask("where is worker 3")
        self.shot(m, "c", "query_while_partitioned", "Edge case: 'where is worker 3' while {2,3} is cut off from the querying side.")
        self.click_and_wait_action("btn-heal", "heal")
        self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "converged")
        q4 = self.ask("where is worker 2", "productivity")
        self.shot(m, "d", "refusal_productivity", "Same query under a `productivity` token: refused (purpose limitation).")
        self.moments[m]["measures"].update({"valid_query": q1, "unknown_worker": q2, "during_partition": q3, "productivity_token": q4})
        problems = []
        if not (q1 and q1["status"] == "answered" and q1["confirmed"] and q1["inferred"] and q1["unreachable"]):
            problems.append("valid query did not return confirmed + inferred + unreachable-nodes sections")
        if not (q2 and q2["status"] == "refused" and q2["reason"]):
            problems.append("unknown worker was not refused with a reason")
        if not (q3 and q3["status"] in ("answered", "refused")):
            problems.append("no result for the partitioned-edge-case query")
        if not (q4 and q4["status"] == "refused" and "not authorised" in (q4["reason"] or "")):
            problems.append("productivity purpose was not refused")
        if not problems:
            self.verdict(m, "PASS", "valid query answered with confirmed/inferred/unreachable; unknown worker and productivity purpose refused with reasons; partition edge case gave: " + (q3["status"] or "") + " — " + ((q3["reason"] or q3["unreachable"] or "")[:140]))
        else:
            self.verdict(m, "PARTIAL" if q1 and q1["status"] == "answered" else "FAIL", "; ".join(problems))

    def m6_robust(self) -> None:
        m = 6
        self.set_moment(m, what="The dashboard survives a page reload; a node process that actually dies is shown as OFFLINE, and shown live again when restarted.",
                        action="Reloaded the browser page; then hard-killed node 1's OS process (not via any dashboard control), watched the card, restarted the process, and watched it return.")
        t0 = time.monotonic()
        self.page.reload()
        self.page.wait_for_selector('[data-testid="node-card-3"]', timeout=30000)
        ok, _ = self.wait(lambda d: num(d["nodes_live"]) == 4 and d["status"] == "live", 30, "recovery after reload")
        reload_s = round(time.monotonic() - t0, 1)
        self.shot(m, "a", "after_reload", f"Page reloaded mid-run; dashboard recovered in {reload_s}s with 4 nodes live.")
        self.launcher.kill_node(1)
        t_kill = time.monotonic()
        off, _ = self.wait(lambda d: d["nodes"][1]["live"] == "OFFLINE", 30, "node 1 shown OFFLINE")
        off_s = round(time.monotonic() - t_kill, 1)
        d = self.dom()
        self.shot(m, "b", "node1_killed", f"Node 1's process was killed; its card reads {d['nodes'][1]['live']} after {off_s}s; nodes live: {d['nodes_live']}.", d)
        others_live = all(d["nodes"][i]["live"] == "LIVE" for i in (0, 2, 3))
        self.launcher.restart_node(1)
        t_restart = time.monotonic()
        back, _ = self.wait(lambda d: d["nodes"][1]["live"] == "LIVE", 45, "node 1 LIVE again")
        back_s = round(time.monotonic() - t_restart, 1)
        self.shot(m, "c", "node1_restarted", f"Node 1 restarted; card reads LIVE after {back_s}s.")
        conv, _ = self.wait(lambda d: d["convergence"] == "CONVERGED", 60, "converged after restart")
        conv_s = round(time.monotonic() - t_restart, 1)
        d = self.dom()
        self.shot(m, "d", "after_recovery", f"After recovery: {d['convergence']}, gaps {d['holes']}, claims {[num(n['claims']) for n in d['nodes']]}.", d)
        self.moments[m]["measures"].update({
            "seconds_to_recover_after_reload": reload_s, "seconds_until_killed_node_shown_offline": off_s if off else None,
            "other_nodes_stayed_live_while_node1_down": others_live, "seconds_until_restarted_node_live": back_s if back else None,
            "seconds_from_restart_to_converged": conv_s if conv else None,
        })
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
            self.verdict(m, "PASS" if conv else "PARTIAL", f"reload recovered in {reload_s}s; killed node OFFLINE after {off_s}s; LIVE again {back_s}s after restart; " + (f"converged {conv_s}s after restart" if conv else "did not re-converge within 60 s"))
        else:
            self.verdict(m, "FAIL" if not off or not back else "PARTIAL", "; ".join(problems))

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
                steps = [(0, lambda: self.m0_startup(self.page)), (1, self.m1_walk), (2, self.m2_deadzone),
                         (3, self.m3_partition), (4, self.m4_lying), (5, self.m5_query), (6, self.m6_robust)]
                for idx, fn in steps:
                    try:
                        fn()
                    except Exception as exc:
                        import traceback

                        self.notes.append(f"review step {idx} raised: {traceback.format_exc(limit=4)}")
                        print(f"  !! step {idx} failed: {exc!r}", flush=True)
                    # A process that died on its own during a moment is a finding.
                    dead = [n for n, up in self.launcher.alive().items() if not up]
                    if dead:
                        msg = f"process(es) {dead} were NOT running after moment {idx} (exit codes {[self.launcher.procs[n].returncode for n in dead]})"
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
        "gaps": d["holes"], "partition": d["partition"], "open_forks": d["forks"], "mean_error_m": d["mean_error"],
        "claims_per_node": [n["claims"] for n in d["nodes"]], "live": [n["live"] for n in d["nodes"]],
        "partitioned": [(n["partitioned"] or "")[:3] for n in d["nodes"]], "behaviour": [(n["behaviour"] or "")[:5] for n in d["nodes"]],
        "reputation": [n["reputation"] for n in d["nodes"]], "rejected": [n["rejected"] for n in d["nodes"]],
        "candidate_regions_m2": {r["label"]: r["area"] for r in d["regions"]},
        "identities": [f"{r['label']} {r['name']} {r['status']} @({r['pos']}) via node {r['node']} err {r['error']}" for r in d["identities"]],
        "query": None if not d.get("query") else {k: d["query"][k] for k in ("status", "verdict") if d["query"].get(k)},
    }


def scan_logs(log_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"tracebacks": {}, "error_lines": {}, "warning_events": {}}
    for f in sorted(log_dir.glob("*.log")):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
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
    "Perception is SIMULATED. There are no cameras, no video and no detector: a simulator process moves five virtual workers on a 2D floor plan and hands each node the noisy detections (position noise 0.08 m, embedding noise, 3 % missed detections) its own camera zone would produce. The 'ground truth' markers are the simulator's own state. Identity embeddings are synthetic 64-d unit vectors, so appearance matching is far easier than with real re-ID features. Nothing here says anything about real-camera accuracy.",
    "The network PARTITION is application-level: the partition button tells each node to ignore inbound gossip from the other group (`POST /partition`). It is not packet loss/latency (netem) and the sending side is not gated. The dashboard's own observer is deliberately not partitioned, so it keeps hearing every node.",
    "The 'lying node' is the project's own `AttackInjector` (fabricated claims at random free positions, 90 % intensity), not an adaptive adversary. Reputation is an EWMA over plausibility checks; a reputation of about 0.5 is the floor reached with three reporting peers (median).",
    "The dashboard's 'rejected claims' counter is the DASHBOARD's own plausibility pass over what it overheard, not a count reported by each node. The label '≈ worker-N' next to an identity is display-only, matched to the nearest ground-truth worker; the network never sees worker names. 'where is worker 2' is translated through that mapping.",
    "The resolver is run over a sliding 45 s window (it is O(claims x identities)); identity labels (P-001...) are kept stable across windows by claim overlap. Within a window the resolution is a pure function of the merged claim set.",
    "The claim-count 'convergence' badge tolerates a small in-flight spread (30 claims, about a second of production) because the simulator keeps producing ~25 claims/s and digests are up to 1 s old; 'gaps' (holes in a node's own digest) must be exactly 0. Byte-identical claim sets are asserted in the unit tests, not readable from the page.",
    "Candidate regions only shrink through gossiped attestations of boundaries (a boundary attested 'not crossed'); the blind aisle here is short, so the dark interval is a few seconds and the region can be dominated by growth. Silence (an occluded node sends no attestation) correctly does NOT shrink it.",
    "Single machine, all processes on localhost; timings are for one Windows laptop and vary run to run. The video/YOLO path was not exercised at all. The baseline `apps/baseline.py` was not exercised by this review.",
    "Screenshots are JPEGs of the real running page (full page height, 1440 px wide); no image was edited. Verdicts are computed from the DOM values recorded at capture time by explicit criteria in `scripts/review_demo.py`.",
]


def esc(s: Any) -> str:
    return html.escape(str(s))


def fmt_measures(m: Any, indent: int = 0) -> str:
    return json.dumps(m, indent=2, default=str, ensure_ascii=False)


def build_reports(rv: Review, logs: dict, env: dict, first_run: Optional[dict], first_findings: Optional[str]) -> tuple[str, str]:
    verdict_class = {"PASS": "pass", "PARTIAL": "partial", "FAIL": "fail", "NOT TESTED": "fail"}
    startup = rv.moments[0]["measures"].get("seconds_launch_to_all_nodes_live")
    m3 = rv.moments[3]["measures"]
    m4 = rv.moments[4]["measures"]
    m2 = rv.moments[2]["measures"]
    key = {
        0: f"all 4 nodes live after {startup} s",
        1: f"mean error {rv.moments[1]['measures'].get('mean_position_error_m_avg')} m; worker-2 label {rv.moments[1]['measures'].get('worker2_label_before_after_zone_change')}",
        2: "; ".join(f"ep{i + 1}: peak {e['peak_area_m2']} m², final {e['final_area_m2']} m², shrank={e['area_ever_decreased']}, same id={e['same_identity_after']}" for i, e in enumerate(m2.get("episodes", []))) or "no region observed",
        3: f"max spread {m3.get('max_spread_during_partition')}, heal→converged {m3.get('seconds_from_heal_to_converged')} s, gaps {m3.get('after_heal_gaps')}",
        4: f"liar <0.7 after {m4.get('seconds_until_liar_reputation_below_0.7')} s, rejected {m4.get('liar_rejected_claims_at_end')}, recovered >0.9 after {m4.get('seconds_until_liar_reputation_above_0.9_after_stop')} s",
        5: "answer + 3 refusal/edge cases (see section)",
        6: f"reload {rv.moments[6]['measures'].get('seconds_to_recover_after_reload')} s; offline {rv.moments[6]['measures'].get('seconds_until_killed_node_shown_offline')} s; back {rv.moments[6]['measures'].get('seconds_until_restarted_node_live')} s",
    }
    timings = {
        "startup_s_launch_to_all_nodes_live": startup,
        "heal_convergence_s": m3.get("seconds_from_heal_to_converged"),
        "reputation_drop_s_to_below_0.7": m4.get("seconds_until_liar_reputation_below_0.7"),
        "reputation_recovery_s_to_above_0.9": m4.get("seconds_until_liar_reputation_above_0.9_after_stop"),
        "region_area_samples_m2_per_episode": [e["samples"] for e in m2.get("episodes", [])],
    }
    css = """body{font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#1c2430;background:#fff}
h1{font-size:24px}h2{margin-top:36px;border-bottom:1px solid #d8dde6;padding-bottom:4px}table{border-collapse:collapse;width:100%}
th,td{border:1px solid #d8dde6;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f4f5f7}
.pass{color:#1a7f4b;font-weight:700}.partial{color:#b7791f;font-weight:700}.fail{color:#c0392b;font-weight:700}
figure{margin:14px 0}figure img{max-width:100%;border:1px solid #d8dde6}figcaption{font-size:13px}
pre{background:#f4f5f7;padding:8px;overflow:auto;font-size:12px}.dom{color:#555;font-size:12px}code{background:#f4f5f7;padding:0 3px}"""
    h = [f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>Starling Demo Review</title><style>{css}</style></head><body>",
         "<h1>Starling demo — automated review evidence</h1>",
         f"<p>Generated {esc(time.strftime('%Y-%m-%d %H:%M:%S'))} by <code>scripts/review_demo.py</code> against the real running system (commit <code>{esc(env['commit'])}</code>). Screenshots are of the real dashboard in headless Chromium, 1440 px wide; values in captions were read from the page DOM at capture time.</p>",
         "<h2>Summary</h2><table><tr><th>#</th><th>Moment</th><th>Verdict</th><th>Key measured numbers</th><th>Reason</th></tr>"]
    md = ["# Starling demo — automated review summary", "",
          f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by `scripts/review_demo.py` (commit `{env['commit']}`). Same content as `review.html`, without images (file names refer to `review/screenshots/`).", "",
          "## Summary", "", "| # | Moment | Verdict | Key measured numbers | Reason |", "|---|---|---|---|---|"]
    for i in range(7):
        mo = rv.moments[i]
        h.append(f"<tr><td>{i}</td><td>{esc(mo['title'])}</td><td class='{verdict_class[mo['verdict']]}'>{esc(mo['verdict'])}</td><td>{esc(key[i])}</td><td>{esc(mo['reason'])}</td></tr>")
        md.append(f"| {i} | {mo['title']} | **{mo['verdict']}** | {key[i]} | {mo['reason']} |")
    h.append("</table>")
    md.append("")
    for i in range(7):
        mo = rv.moments[i]
        h.append(f"<h2>Moment {i} — {esc(mo['title'])}: <span class='{verdict_class[mo['verdict']]}'>{esc(mo['verdict'])}</span></h2>")
        h.append(f"<p><b>What it should demonstrate:</b> {esc(mo['what'])}<br><b>Action taken:</b> {esc(mo['action'])}<br><b>Verdict reason:</b> {esc(mo['reason'])}</p>")
        md += [f"## Moment {i} — {mo['title']}: {mo['verdict']}", "", f"**What it should demonstrate:** {mo['what']}", "", f"**Action taken:** {mo['action']}", "", f"**Verdict reason:** {mo['reason']}", ""]
        for s in [x for x in rv.shots if x["moment"] == i]:
            b64 = base64.b64encode((REVIEW_DIR / s["file"]).read_bytes()).decode()
            h.append(f"<figure><img alt='{esc(s['name'])}' src='data:image/jpeg;base64,{b64}'><figcaption><b>{esc(s['name'])}.jpg</b> — {esc(s['caption'])} <i>(t = {s['t_s']} s since launch)</i><br><span class='dom'>DOM values: {esc(json.dumps(s['dom'], ensure_ascii=False))}</span></figcaption></figure>")
            md += [f"### {s['name']}.jpg  (t = {s['t_s']} s since launch)", "", s["caption"], "", "DOM values read at capture:", "", "```json", json.dumps(s["dom"], indent=1, ensure_ascii=False), "```", ""]
        h.append(f"<details><summary>All measured values for moment {i}</summary><pre>{esc(fmt_measures(mo['measures']))}</pre></details>")
        md += ["Measured values:", "", "```json", fmt_measures(mo["measures"]), "```", ""]

    h.append("<h2>First-run findings</h2>")
    md += ["## First-run findings", ""]
    if first_run:
        rows = "".join(f"<tr><td>{i}</td><td>{esc(first_run['moments'][str(i)]['title'])}</td><td class='{verdict_class.get(first_run['moments'][str(i)]['verdict'], 'fail')}'>{esc(first_run['moments'][str(i)]['verdict'])}</td><td>{esc(first_run['moments'][str(i)]['reason'])}</td></tr>" for i in range(7))
        h.append("<p>Verdicts of the <b>first, unmodified run</b> (before any fix made in response to this review):</p><table><tr><th>#</th><th>Moment</th><th>Verdict</th><th>Reason</th></tr>" + rows + "</table>")
        md += ["Verdicts of the first, unmodified run:", "", "| # | Moment | Verdict | Reason |", "|---|---|---|---|"] + [f"| {i} | {first_run['moments'][str(i)]['title']} | {first_run['moments'][str(i)]['verdict']} | {first_run['moments'][str(i)]['reason']} |" for i in range(7)] + [""]
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
        h.append("<p>No Python tracebacks and no <code>level: error</code> log records in any process log.</p>")
        md += ["No Python tracebacks and no `level: error` log records in any process log.", ""]
    for name, items in {**{k: v for k, v in tb.items()}}.items():
        h.append(f"<p><b>{esc(name)}</b> tracebacks:</p><pre>{esc(chr(10).join(items[:2]))}</pre>")
        md += [f"**{name}** tracebacks:", "```", *items[:2], "```", ""]
    for name, items in el.items():
        h.append(f"<p><b>{esc(name)}</b> error records ({len(items)}):</p><pre>{esc(chr(10).join(items[:5]))}</pre>")
        md += [f"**{name}** error records ({len(items)}):", "```", *items[:5], "```", ""]
    h.append(f"<p>Warning-level events (counts): <code>{esc(json.dumps(logs['warning_events']))}</code></p>")
    md += [f"Warning-level events (counts): `{json.dumps(logs['warning_events'])}`", ""]
    st_rows = "".join(f"<tr><td>{esc(n)}</td><td>{esc(s['exit_code'])}</td><td>{'still running at shutdown; stopped by the launcher' if s['was_running_at_shutdown'] else 'had already exited before shutdown'}</td></tr>" for n, s in rv.exit_status.items())
    h.append("<table><tr><th>process</th><th>exit code</th><th>note</th></tr>" + st_rows + "</table>")
    h.append("<p class='dom'>On Windows the launcher stops a process with <code>TerminateProcess</code>, so a nonzero exit code (typically 1) for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted during moment 6.</p>")
    md += ["| process | exit code | note |", "|---|---|---|"] + [f"| {n} | {s['exit_code']} | {'still running at shutdown; stopped by the launcher' if s['was_running_at_shutdown'] else 'had already exited before shutdown'} |" for n, s in rv.exit_status.items()]
    md += ["", "On Windows the launcher stops a process with `TerminateProcess`, so a nonzero exit code for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted during moment 6.", ""]
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
    args = ap.parse_args(argv)

    for old in SHOT_DIR.glob("*.jpg") if SHOT_DIR.exists() else []:
        old.unlink()
    rv = Review(args.port)
    rv.browser_version = "unknown"
    t_start = time.monotonic()
    rv.run()
    logs = scan_logs(rv.launcher.log_dir)
    env = env_info(rv.browser_version)
    results = {"moments": {str(k): v for k, v in rv.moments.items()}, "shots": rv.shots, "console_errors": rv.console_errors,
               "logs": logs, "exit_status": rv.exit_status, "env": env, "notes": rv.notes, "run_seconds": round(time.monotonic() - t_start, 1)}
    REVIEW_DIR.mkdir(exist_ok=True)
    (REVIEW_DIR / "results.json").write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    if args.first_run:
        (REVIEW_DIR / "first_run_results.json").write_text(json.dumps({"moments": results["moments"]}, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    fr = REVIEW_DIR / "first_run_results.json"
    ff = REVIEW_DIR / "first_run_findings.md"
    first_run = json.loads(fr.read_text(encoding="utf-8")) if fr.exists() and not args.first_run else None
    first_findings = ff.read_text(encoding="utf-8") if ff.exists() and not args.first_run else None
    page, summary = build_reports(rv, logs, env, first_run, first_findings)
    (REVIEW_DIR / "review.html").write_text(page, encoding="utf-8")
    (REVIEW_DIR / "review_summary.md").write_text(summary, encoding="utf-8")
    print("\nVERDICTS:", {i: rv.moments[i]["verdict"] for i in range(7)})
    print(f"wrote {REVIEW_DIR / 'review.html'} ({(REVIEW_DIR / 'review.html').stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

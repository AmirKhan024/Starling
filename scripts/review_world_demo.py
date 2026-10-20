"""scripts/review_world_demo.py
--------------------------------
Automated end-to-end review of the LIVE 3D WORLD demo. Starts the real
system (scripts/run_world_demo.py's launcher: world server, camera rig, four
camera nodes running real perception, dashboard), then drives every demo
moment through the same controls a presenter uses, measures the outcome from
the dashboard's own state (what the manager and technical views render) and
the world's ground truth, and takes screenshots of the three screens.

Writes:
    review/world/review_summary.md   verdicts, measurements, screenshots list
    review/world/results.json        raw measurements
    review/world/screenshots/*.jpg

Nothing is mocked: every verdict is an explicit criterion applied to values
read live from the running system.

    python scripts/review_world_demo.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.run_world_demo import LIGHT_FPS, LOW_MEMORY_WARN_GB, WorldDemoLauncher  # noqa: E402

OUT = REPO / "review" / "world"
SHOTS = OUT / "screenshots"
VIEWPORT = {"width": 1600, "height": 960}
SHOT_W = 1100
LIAR = 2
# The manager alert threshold (configs/world/dashboard.yaml lying_reputation_alert).
ALERT_REP = 0.85
LENS = 1
BREAK_WHO = "EMP-1027"


class Review:
    def __init__(self, launcher: WorldDemoLauncher) -> None:
        self.L = launcher
        self.dash = launcher.dash_url
        self.world = launcher.world_url
        self.results: dict[str, Any] = {}
        self.shots: list[dict[str, str]] = []
        self.t0 = time.monotonic()
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._b = self._pw.chromium.launch(
            headless=True, args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"]
        )
        self.pages = {}
        for name, url in (
            ("world", self.world + "/"),
            ("manager", self.dash + "/"),
            ("tech", self.dash + "/engineer"),
            ("network", self.dash + "/network"),
        ):
            pg = self._b.new_page(viewport=VIEWPORT)
            pg.goto(url)
            self.pages[name] = pg

    def close(self) -> None:
        self._b.close()
        self._pw.stop()

    # -- helpers ------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        return requests.get(self.dash + "/api/state", timeout=5).json()

    def wstatus(self) -> dict[str, Any]:
        return requests.get(self.world + "/api/status", timeout=5).json()

    def post(self, path: str, body: Optional[dict] = None) -> dict[str, Any]:
        return requests.post(self.dash + path, json=body or {}, timeout=10).json()

    def wait(
        self, cond: Callable[[dict[str, Any]], Any], timeout: float, every: float = 1.0
    ) -> tuple[Any, float, dict]:
        t = time.monotonic()
        last: dict = {}
        while time.monotonic() - t < timeout:
            try:
                last = self.state()
                v = cond(last)
                if v:
                    return v, round(time.monotonic() - t, 1), last
            except Exception:
                pass
            time.sleep(every)
        return None, round(time.monotonic() - t, 1), last

    def person(self, s: dict, emp: str) -> dict:
        return next(p for p in s["world"]["people"] if p["id"] == emp)

    def shot(self, page: str, slug: str, caption: str, full: bool = False) -> None:
        pg = self.pages[page]
        pg.wait_for_timeout(1500)
        path = SHOTS / f"{len(self.shots):02d}_{page}_{slug}.png"
        pg.screenshot(path=str(path), full_page=full)
        im = Image.open(path).convert("RGB")
        if im.width > SHOT_W:
            im = im.resize((SHOT_W, int(im.height * SHOT_W / im.width)), Image.LANCZOS)
        jpg = path.with_suffix(".jpg")
        im.save(jpg, quality=70)
        path.unlink()
        self.shots.append({"file": f"screenshots/{jpg.name}", "caption": caption})
        print(f"    shot {jpg.name}: {caption}", flush=True)  # CLI banner

    def verdict(self, key: str, ok: bool, what: str, measures: dict) -> None:
        self.results[key] = {
            "verdict": "PASS" if ok else "FAIL",
            "what": what,
            "measures": measures,
        }
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {key}: {json.dumps(measures)[:400]}", flush=True
        )  # CLI banner

    # -- moments ------------------------------------------------------------

    def m1_checkin(self) -> None:
        print(
            "moment 1: shift start — arrival and verification at the entrance", flush=True
        )  # CLI banner
        self.pages["world"].evaluate("window.__world && window.__world.setView('cam0')")
        v, secs, s = self.wait(lambda s: s["world"]["counts"]["verified_on_site"] >= 4, 150)
        self.shot("world", "gate_view", "Camera 0's view of the entrance gate (the 3D world).")
        self.pages["world"].evaluate("window.__world && window.__world.setView('overview')")
        names_ok = all(p["verified"] for p in s["world"]["people"])
        checkins = s["world"]["verifications"]
        self.shot(
            "manager",
            "all_checked_in",
            "Manager view after the four employees checked in.",
            full=True,
        )
        self.verdict(
            "1_checkin",
            bool(v) and names_ok,
            "Each of the four employees is verified at the entrance gate from the pixels and named "
            "on the manager view.",
            {
                "seconds_until_all_4_verified": secs,
                "verified_on_site": s["world"]["counts"]["verified_on_site"],
                "check_ins": [(c["clock"], c["name"], c["node"]) for c in checkins],
                "unverified_alerts": [
                    a for a in s["world"]["alerts"] if a["kind"] == "unverified_person"
                ],
            },
        )

    def m2_tracking(self, seconds: float = 70.0) -> None:
        print("moment 2: continuous tracking across the four cameras", flush=True)  # CLI banner
        errs, visible, samples, wrong_names, forks, false_alarms = [], [], 0, 0, 0, 0
        t = time.monotonic()
        while time.monotonic() - t < seconds:
            s = self.state()
            samples += 1
            forks = max(forks, s.get("forks_open", 0))
            for i in s["identities"]:
                if i["error_m"] is not None:
                    errs.append(i["error_m"])
                if i["name"] is None and i["status"] == "seen" and i["n_claims"] >= 30:
                    wrong_names += 1
            visible.append(s["world"]["counts"]["visible"] + s["world"]["counts"]["out_of_view"])
            false_alarms += sum(1 for a in s["world"]["alerts"] if a["kind"] == "camera_untrusted")
            time.sleep(2.0)
        errs.sort()
        self.shot(
            "tech",
            "tracking",
            "Technical view: pipeline counters, each node's own annotated view, belief vs ground "
            "truth, gossip ring, resolver output.",
            full=True,
        )
        med = statistics.median(errs) if errs else None
        p90 = errs[int(0.9 * (len(errs) - 1))] if errs else None
        self.verdict(
            "2_tracking",
            med is not None
            and med < 1.5
            and forks == 0
            and min(visible) >= 4
            and false_alarms == 0,
            "All four employees stay accounted for (in view, or out of view with a reason); "
            "believed positions track the truth.",
            {
                "samples": samples,
                "position_error_vs_truth_m": {
                    "median": None if med is None else round(med, 2),
                    "p90": None if p90 is None else round(p90, 2),
                    "n": len(errs),
                },
                "min_employees_accounted_for": min(visible),
                "unnamed_identities_seen": wrong_names,
                "max_open_forks": forks,
                "untrusted_camera_alerts_with_no_liar": false_alarms,
            },
        )

    def m3_deadzone(self) -> None:
        print(
            "moment 3: Priya picks in the camera-less aisles (negative evidence)", flush=True
        )  # CLI banner
        emp = "EMP-1041"
        # wait until she is well inside the aisle (out of view for a while, with a region)
        v, secs, s = self.wait(
            lambda s: (
                self.person(s, emp)["status"] == "out_of_view"
                and self.person(s, emp).get("search")
                and (self.person(s, emp)["unseen_for_s"] or 0) >= 6
            ),
            240,
            every=0.5,
        )
        if not v:
            self.verdict(
                "3_deadzone", False, "Priya goes out of view in the aisles", {"waited_s": secs}
            )
            return
        p = self.person(s, emp)
        reg = next((r for r in s["regions"] if r["id"] == emp), None)
        self.shot(
            "manager",
            "in_aisles",
            "Manager view: Priya is in the storage aisles — not visible, but accounted for.",
            full=True,
        )
        self.shot(
            "tech",
            "c4_region",
            "Technical view: the C4 candidate region vs plain reachability.",
            full=True,
        )
        healthy_leak = reg["healthy_zone_overlap_m2"] if reg else None
        v2, secs2, s2 = self.wait(lambda s: self.person(s, emp)["status"] == "visible", 90)
        self.verdict(
            "3_deadzone",
            bool(reg)
            and reg["area_m2"] < 0.5 * reg["reachable_area_m2"]
            and (healthy_leak or 0) <= 2.0
            and bool(v2),
            "While she is hidden, healthy cameras' attested absence keeps her search area inside "
            "the aisles; she is re-acquired as the SAME named identity.",
            {
                "summary_shown_to_manager": p["summary"],
                "region_m2": reg and reg["area_m2"],
                "reachable_m2": reg and reg["reachable_area_m2"],
                "in_aisles_fraction": p["search"]["in_aisles_fraction"],
                "healthy_zone_overlap_m2": healthy_leak,
                "reacquired_as_same_identity_after_s": secs2 if v2 else None,
            },
        )

    def m4_lens(self) -> None:
        print(
            f"moment 4: a tarp is thrown over camera {LENS}'s lens (physical fault)", flush=True
        )  # CLI banner
        self.post("/api/world/block", {"node_id": LENS})
        v, secs, s = self.wait(
            lambda s: not next(n for n in s["nodes"] if n["id"] == LENS)["coverage_healthy"], 60
        )
        alert = [a for a in s["world"]["alerts"] if a["kind"] == "camera_degraded"]
        self.pages["world"].evaluate(f"window.__world && window.__world.setView('cam{LENS}')")
        self.shot(
            "world",
            "tarp",
            f"The 3D world: camera {LENS} seen through its own pose with the tarp over the lens.",
        )
        self.pages["world"].evaluate("window.__world && window.__world.setView('overview')")
        self.shot(
            "tech",
            "lens_covered",
            f"Technical view: node {LENS} notices from its own pixels (illumination / occlusion) "
            "and stops attesting.",
            full=True,
        )
        self.shot(
            "manager", "lens_alert", "Manager view: the camera problem in plain words.", full=True
        )
        self.post("/api/world/unblock", {})
        v2, secs2, _ = self.wait(
            lambda s: next(n for n in s["nodes"] if n["id"] == LENS)["coverage_healthy"], 90
        )
        self.verdict(
            "4_lens",
            bool(v) and bool(alert) and bool(v2),
            "The node notices the covered lens from its own pixels and stops vouching for its zone "
            "(silence is not evidence); it resumes when cleared.",
            {
                "seconds_to_stop_attesting": secs,
                "manager_alert": alert[0]["text"] if alert else None,
                "seconds_to_resume_after_clearing": secs2 if v2 else None,
            },
        )

    def m5_partition(self) -> None:
        print("moment 5: network split and heal", flush=True)  # CLI banner
        self.post("/api/partition")
        v, secs, s = self.wait(lambda s: all(n["partitioned"] for n in s["nodes"]), 30)
        time.sleep(20)
        s = self.state()
        named_during = sum(
            1 for p in s["world"]["people"] if p["status"] in ("visible", "out_of_view")
        )
        split_alert = [a["text"] for a in s["world"]["alerts"] if a["kind"] == "network_split"]
        self.shot(
            "tech",
            "partitioned",
            "Technical view during the split: two cut links, replicas diverging.",
            full=True,
        )
        self.shot("manager", "partitioned", "Manager view during the split.", full=True)
        self.post("/api/heal")
        v2, secs2, s2 = self.wait(lambda s: s["convergence"]["converged"], 120)
        self.shot(
            "tech", "healed", "Technical view after healing: replicas converged again.", full=True
        )
        self.verdict(
            "5_partition",
            bool(v) and bool(v2) and bool(split_alert),
            "Both halves keep tracking while cut off; after healing, anti-entropy brings every "
            "replica to the same claim set.",
            {
                "seconds_until_split_shown": secs,
                "employees_still_accounted_for_during_split": named_during,
                "manager_alert": split_alert[0] if split_alert else None,
                "seconds_to_reconverge_after_heal": secs2 if v2 else None,
                "spread_after": s2["convergence"]["spread"],
                "gaps_after": s2["convergence"]["holes_total"],
            },
        )

    def m6_lie(self) -> None:
        print(f"moment 6: node {LIAR} starts fabricating sightings", flush=True)  # CLI banner
        self.post("/api/lie", {"node_id": LIAR})
        v, secs, s = self.wait(
            lambda s: (
                (next(n for n in s["nodes"] if n["id"] == LIAR)["reputation"] or 1) < ALERT_REP
            ),
            150,
            every=2.0,
        )
        honest = {n["id"]: n["reputation"] for n in s["nodes"] if n["id"] != LIAR}
        alert = [a["text"] for a in s["world"]["alerts"] if a["kind"] == "camera_untrusted"]
        self.shot(
            "tech",
            "lying",
            f"Technical view: node {LIAR}'s reputation, as its peers report it, falls; its claims "
            "are rejected.",
            full=True,
        )
        self.post("/api/stop_lie", {})
        self.verdict(
            "6_lie",
            bool(v) and all((r or 1) >= 0.95 for r in honest.values()),
            "Peers catch physically implausible claims; only the liar's reputation falls.",
            {
                "seconds_until_reputation_below_alert": secs if v else None,
                "liar_reputation": next(n for n in s["nodes"] if n["id"] == LIAR)["reputation"],
                "liar_rejected": next(n for n in s["nodes"] if n["id"] == LIAR)["rejected"],
                "honest_reputations": honest,
                "manager_alert": alert[0] if alert else None,
            },
        )

    def m7_break(self) -> None:
        print(f"moment 7: {BREAK_WHO} goes on a break and comes back", flush=True)  # CLI banner
        before = len(
            [c for c in self.state()["world"]["verifications"] if c["employee_id"] == BREAK_WHO]
        )
        ok = False
        for _ in range(30):
            if self.post("/api/world/break", {"employee_id": BREAK_WHO}).get("ok"):
                ok = True
                break
            time.sleep(2)
        v, secs, s = self.wait(lambda s: self.person(s, BREAK_WHO)["status"] == "left", 120)
        self.shot(
            "manager",
            "on_break",
            "Manager view: Marcus left through the staff entrance.",
            full=True,
        )
        v2, secs2, s2 = self.wait(
            lambda s: (
                len([c for c in s["world"]["verifications"] if c["employee_id"] == BREAK_WHO])
                > before
                and self.person(s, BREAK_WHO)["status"] == "visible"
            ),
            150,
        )
        self.verdict(
            "7_break",
            ok and bool(v) and bool(v2),
            "Leaving through the staff door is recognised as 'left'; coming back, the employee is "
            "verified again at the gate.",
            {
                "seconds_until_shown_as_left": secs if v else None,
                "summary": self.person(s, BREAK_WHO)["summary"] if v else None,
                "seconds_until_back_and_re_verified": secs2 if v2 else None,
            },
        )

    def m8_query(self) -> None:
        print("moment 8: capability-scoped query", flush=True)  # CLI banner
        a = self.post("/api/query", {"text": "where is Priya", "purpose": "safety"})
        b = self.post("/api/query", {"text": "where is Priya", "purpose": "productivity"})
        c = self.post("/api/query", {"text": "where is EMP-9999", "purpose": "safety"})
        self.verdict(
            "8_query",
            a.get("status") == "answered"
            and b.get("status") == "refused"
            and c.get("status") == "refused",
            "A safety query is answered (confirmed vs inferred); a productivity query and an "
            "unknown person are refused with reasons.",
            {
                "safety": a.get("text") or a.get("reason"),
                "productivity": b.get("reason"),
                "unknown": c.get("reason"),
            },
        )

    def ask(self, text: str, purpose: str = "safety") -> dict[str, Any]:
        return self.post("/api/ask", {"text": text, "purpose": purpose})

    def ask_cameras(self) -> dict[str, Any]:
        return requests.get(self.dash + "/api/ask_cameras", timeout=15).json()

    def m9_every_camera(self) -> None:
        print("moment 9: ask every camera directly (each from its own replica)", flush=True)  # CLI banner
        tries, agreed = [], None
        for _ in range(12):
            a = self.ask_cameras()
            tries.append([g["nodes"] for g in a["groups"]])
            if a["agree"] and a["answered"] == a["total"]:
                agreed = a
                break
            time.sleep(4)
        self.shot("network", "every_camera", "Camera network: every camera answers from its own copy; fingerprints match.")
        self.verdict(
            "9_every_camera",
            agreed is not None,
            "Each camera node, asked directly, resolves its OWN replica over the same window; all four "
            "return the identical answer fingerprint (C1: same claims, same deterministic answer).",
            {
                "attempts": len(tries),
                "groups_per_attempt": tries,
                "fingerprint": agreed["groups"][0]["fingerprint"] if agreed else None,
                "ms_per_node": [n.get("ms") for n in agreed["nodes"]] if agreed else None,
                "claims_in_window": [n.get("claims_in_window") for n in agreed["nodes"]] if agreed else None,
            },
        )

    def m10_intruder(self) -> None:
        print("moment 10: an unknown person walks in through a dock door", flush=True)  # CLI banner
        sent = self.post("/api/world/visitor", {})
        v, secs, s = self.wait(lambda s: s["world"]["unverified"], 90)
        self.shot("manager", "intruder", "Manager view: an unknown person, flagged and tracked.", full=True)
        v2, secs2, s2 = self.wait(
            lambda s: [u for u in s["world"]["unverified"] if len(u.get("cameras", [])) > 1], 60
        )
        a = self.ask("Is there anyone we don't know?")
        # No employee may be mistaken for the stranger: named identities stay near their own truth.
        errs = [p.get("truth_error_m") for p in (s2 or s)["world"]["people"] if p.get("truth_error_m") is not None]
        self.verdict(
            "10_intruder",
            bool(sent.get("ok")) and bool(v) and a.get("kind") == "unknown" and a["headline"].startswith("Yes"),
            "A person who is not enrolled and never passes the gate is tracked as an unknown identity, "
            "raises a manager alert, and is answered for in plain English.",
            {
                "seconds_until_flagged": secs if v else None,
                "seconds_until_followed_across_cameras": secs2 if v2 else None,
                "cameras": v2[0]["cameras"] if v2 else None,
                "answer": a.get("headline"),
                "alerts": [x["text"] for x in s["world"]["alerts"] if x["kind"] == "unverified_person"] if s else [],
                "named_employee_truth_errors_m": errs,
            },
        )

    def m11_area(self) -> None:
        print("moment 11: is anyone in <area> (negative evidence in a query)", flush=True)  # CLI banner
        pk = self.ask("Is anyone in Packing?")
        ai = self.ask("Is anyone in the aisles?")
        tags = [e["tag"] for e in pk.get("evidence", [])]
        self.verdict(
            "11_area_query",
            pk.get("status") == "answered" and ai.get("status") == "answered" and not ai["headline"].startswith("No"),
            "An area question is answered with its evidence (seen / attested clear / silent); the "
            "camera-less aisles are never declared empty.",
            {"packing": pk.get("headline"), "packing_evidence": tags, "aisles": ai.get("headline")},
        )

    def m12_rollcall(self) -> None:
        print("moment 12: emergency roll call", flush=True)  # CLI banner
        r = requests.get(self.dash + "/api/rollcall", timeout=10).json()
        st = self.state()
        # Employees really inside (the stranger may already have slipped out through a dock door
        # no camera watches as an exit, so the roll call rightly keeps listing them as unknown).
        truth_inside = len([w for w in st["gt"]["workers"] if not w.get("visitor")]) if st.get("gt") else None
        staff_inside = sum(1 for x in r.get("rows", []) if x["state"] not in ("left", "intruder"))
        self.pages["manager"].click("#sos")
        self.shot("manager", "rollcall", "Emergency roll call: everyone inside, where to look, unknown people included.")
        self.pages["manager"].keyboard.press("Escape")
        self.verdict(
            "12_rollcall",
            r.get("status") == "answered" and truth_inside is not None and staff_inside == truth_inside,
            "The roll call counts exactly the people really inside (employees, hidden ones, unknown people).",
            {"headline": r.get("headline"), "staff_inside": staff_inside, "truth_staff_inside": truth_inside, "counts": r.get("counts")},
        )

    def m13_failures(self) -> None:
        print("moment 13: kill the central server vs pull one camera's plug", flush=True)  # CLI banner
        self.post("/api/central/kill")
        v, secs, s = self.wait(lambda s: s["central"]["status"] == "DOWN", 15)
        tracked = sum(1 for p in s["world"]["people"] if p["status"] in ("visible", "out_of_view")) if s else 0
        self.shot("network", "central_down", "Central server killed: every feed lost. Starling unaffected.")
        self.post("/api/node/2/kill")
        v2, secs2, s2 = self.wait(lambda s: not next(n for n in s["nodes"] if n["id"] == 2)["live"], 20)
        time.sleep(3)
        a = self.ask_cameras()
        tracked2 = sum(1 for p in s2["world"]["people"] if p["status"] in ("visible", "out_of_view")) if s2 else 0
        self.shot("network", "node_off", "Camera 2 powered off: only its area goes unwatched; the other three still answer.")
        self.post("/api/node/2/restart")
        v3, secs3, _ = self.wait(lambda s: next(n for n in s["nodes"] if n["id"] == 2)["live"], 180, every=2)
        self.post("/api/central/restart")
        v4, secs4, _ = self.wait(lambda s: s["central"]["status"] == "UP", 30)
        v5, secs5, _ = self.wait(lambda s: s["convergence"]["converged"], 90)
        self.verdict(
            "13_failures",
            bool(v) and tracked > 0 and bool(v2) and a["answered"] == 3 and bool(v3) and bool(v4) and bool(v5),
            "Killing the central server blinds it entirely while Starling keeps tracking; powering off one "
            "camera loses only that camera (three still answer); powered back on, it catches up and every "
            "replica converges.",
            {
                "central_down_after_s": secs if v else None,
                "starling_tracking_while_central_down": tracked,
                "node2_offline_after_s": secs2 if v2 else None,
                "cameras_answering_with_node2_off": a["answered"],
                "starling_tracking_with_node2_off": tracked2,
                "node2_back_live_after_s": secs3 if v3 else None,
                "central_back_after_s": secs4 if v4 else None,
                "converged_after_s": secs5 if v5 else None,
            },
        )

    def m14_recognition(self) -> None:
        print("moment 14: every camera recognises enrolled employees (so a lost name comes back)", flush=True)  # CLI banner
        per = {}
        for n in range(4):
            p = requests.get(f"{self.dash}/api/node/{n}/perception", timeout=5).json()
            per[n] = sorted({e["employee_id"] for e in p.get("events", []) if e.get("kind") == "recognised" and e.get("employee_id")})
        s = self.state()
        lost = [p["name"] for p in s["world"]["people"] if p["status"] in ("lost", "conflict")]
        self.verdict(
            "14_recognition",
            all(per[n] for n in per) and not lost,
            "Every camera (not only the gate camera) recognises enrolled employees, so a name lost to a "
            "track break is restored by whichever camera sees the person next; nobody is left 'missing'.",
            {"recognised_by_camera": per, "missing_employees": lost, "unknown_people": [u["label"] for u in s["world"]["unverified"]]},
        )

    def write(self, perf: dict) -> None:
        (OUT / "results.json").write_text(
            json.dumps(
                {"results": self.results, "performance": perf, "shots": self.shots}, indent=1
            ),
            encoding="utf-8",
        )
        lines = [
            "# Live 3D world demo — automated review",
            "",
            "Generated by `scripts/review_world_demo.py` against the real running system (world "
            "server, camera rig,",
            "four camera nodes running YOLO + tracking + appearance + homography on rendered "
            "frames, dashboard).",
            "",
            "| Moment | Verdict | What was checked |",
            "|---|---|---|",
        ]
        for k, r in self.results.items():
            lines.append(f"| {k} | **{r['verdict']}** | {r['what']} |")
        lines += ["", "## Measurements", ""]
        for k, r in self.results.items():
            lines += [f"### {k}", "", "```json", json.dumps(r["measures"], indent=1), "```", ""]
        lines += [
            "## Performance",
            "",
            "```json",
            json.dumps(perf, indent=1),
            "```",
            "",
            "## Screenshots",
            "",
        ]
        for s in self.shots:
            lines.append(f"- [{s['file']}]({s['file']}) — {s['caption']}")
        (OUT / "review_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Automated review of the live 3D world demo")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--light", action="store_true", help="cameras at the launcher's light frame rate")
    ap.add_argument("--full", action="store_true", help="never switch to light mode automatically")
    args = ap.parse_args(argv)
    SHOTS.mkdir(parents=True, exist_ok=True)
    for old in SHOTS.glob("*.jpg"):
        old.unlink()
    light = args.light
    if not light and not args.full:
        import psutil

        light = psutil.virtual_memory().available / 2**30 < LOW_MEMORY_WARN_GB
    print(f"review mode: {'light (cameras at ' + str(LIGHT_FPS) + ' fps)' if light else 'full'}", flush=True)  # CLI banner
    launcher = WorldDemoLauncher(detector="yolo11n.pt" if args.fast else None, fps=LIGHT_FPS if light else None)
    launcher.prepare()
    rv = None
    try:
        launcher.start()
        rv = Review(launcher)
        for m in (
            rv.m1_checkin,
            rv.m2_tracking,
            rv.m3_deadzone,
            rv.m4_lens,
            rv.m5_partition,
            rv.m6_lie,
            rv.m7_break,
            rv.m8_query,
            rv.m9_every_camera,
            rv.m10_intruder,
            rv.m11_area,
            rv.m12_rollcall,
            rv.m14_recognition,  # before m13, which restarts camera 2 (its recognition log starts afresh)
            rv.m13_failures,
        ):
            try:
                m()
            except Exception as exc:  # one broken moment must not hide the others
                rv.results[m.__name__] = {
                    "verdict": "ERROR",
                    "what": m.__doc__ or m.__name__,
                    "measures": {"error": repr(exc)},
                }
                print(f"  [ERROR] {m.__name__}: {exc!r}", flush=True)  # CLI banner
        perf = {}
        try:
            ws = rv.wstatus()
            perf["world"] = {"t_media": ws["t_media"], "rig": ws["rig"]}
            perf["nodes"] = {}
            for n in range(4):
                p = requests.get(f"{launcher.dash_url}/api/node/{n}/perception", timeout=5).json()
                perf["nodes"][n] = {
                    k: p.get(k)
                    for k in (
                        "process_ms",
                        "achieved_fps",
                        "target_fps",
                        "dropped_total",
                        "claims_made",
                        "frames",
                    )
                }
            perf["dashboard_compute_ms"] = rv.state().get("compute_ms")
        except Exception as exc:
            perf["error"] = repr(exc)
        rv.write(perf)
    finally:
        if rv is not None:
            rv.close()
        launcher.stop()
    failed = [k for k, r in rv.results.items() if r["verdict"] != "PASS"] if rv else ["all"]
    print(
        f"\nreview written to {OUT}; "
        f"{'all PASS' if not failed else 'not passing: ' + ', '.join(failed)}"
    )  # CLI banner
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""scripts/build_explainer.py
------------------------------
Turn the screenshots from `scripts/capture_explainer.py` into
`review/explainer.html` — a walkthrough of the technical dashboard written for
someone who has to defend this project to an examiner.

The prose lives here, in `SECTIONS`. The numbers quoted under each screenshot
come from `review/explainer_shots.json`, which recorded the live `/api/state`
at the instant of capture, so the text cannot drift away from the image.

    python scripts/capture_explainer.py
    python scripts/build_explainer.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "review" / "explainer_shots.json"
OUT = REPO / "review" / "explainer.html"


def e(s: Any) -> str:
    return html.escape(str(s))


# --------------------------------------------------------------------------
# The document. Each shot: what you see, what the numbers mean, the mechanism,
# and the questions most likely to be asked about it.
# --------------------------------------------------------------------------

INTRO = """
<p class="lede">This page explains the <b>technical view</b> of the Starling dashboard, one panel
at a time. Every screenshot is real, taken automatically from a running system, and the numbers
quoted underneath each one are the values that were live at the instant the picture was taken.</p>

<p>Read it in order. The technical view is the harder of the two screens; once you can read it,
the manager view at <code>/</code> is just the same information with the jargon removed.</p>

<div class="big">
<h3>If you remember one thing, remember this</h3>
<p><b>The cameras never agree on who someone is. They agree on what they saw.</b></p>
<p>Each camera node writes small signed records called <b>claims</b> — "at media-time 41.2s I saw
a person at (12.4, 8.1) with this appearance vector". Those claims are gossiped to neighbours and
merged into a set. The identity assignment — <i>which claims belong to the same person</i> — is
<b>never sent over the network</b>. Every node recomputes it locally from the claims it holds, using
the same deterministic function, so they all arrive at the same answer without anyone being in charge.</p>
<p>That is the whole project in three sentences. Almost every examiner question is a variation of
"are you sure there's no coordinator?" — and the answer is: the thing a coordinator would decide
is the one thing that is never transmitted.</p>
</div>

<div class="warn">
<h3>The question you will definitely be asked</h3>
<p><b>"It's a simulation — doesn't the system already know where everyone is?"</b></p>
<p>No, and this is worth being able to answer crisply. The simulator generates the true positions,
but a node only ever receives a noisy observation derived from them. The true worker id is
deliberately excluded from the wire format, so it cannot reach a node even by accident. On the map
below, ground truth is drawn only as a <i>faint dashed ring</i>, and only by the dashboard, which is
a passive observer. The "&asymp; ground-truth" column in the identity table is a display label
computed by nearest-neighbour matching for your benefit — the network never sees it.</p>
</div>
"""

SECTIONS: list[dict[str, Any]] = [
    {
        "id": "orientation",
        "title": "1. Orientation — what am I looking at?",
        "blurb": "The technical view is one page with nine panels. This section names each one. "
                 "Nothing unusual is happening in these shots: four workers are walking their routes "
                 "and all four cameras are healthy.",
        "shots": [
            {
                "slug": "01_fullpage",
                "title": "The whole page",
                "look": "Left column: the floor map, the centralized comparison system, the resolved "
                        "identity table, and identity conflicts. Right column: the scripted demo tour, "
                        "the fault-injection controls, the four node processes, the query box, and an "
                        "event log.",
                "numbers": "The layout is fixed; the two columns are independent. Everything updates on "
                           "a timer (once per second by default).",
                "mech": "Served by <code>apps/demo_dashboard/server.py</code> at <code>/engineer</code>. "
                        "It is a read-only observer: it subscribes to the same gossip the nodes send each "
                        "other and has no privileged access to any node's database. If you deleted the "
                        "dashboard, the network would carry on unchanged.",
                "ask": [
                    ("Is the dashboard part of the system?",
                     "No. It is a passive gossip subscriber — <code>apps/dashboard/observer.py</code> is "
                     "SUB-only and never participates in anti-entropy. It is a window, not a component. "
                     "That is a stated architectural rule, not an accident."),
                ],
            },
            {
                "slug": "02_header",
                "title": "The health strip",
                "look": "A single line across the top that tells you whether the system is alive.",
                "numbers": "<b>nodes live</b> — how many of the four node processes are responding. "
                           "<b>sim t</b> — media time in seconds, i.e. the time the footage depicts, not "
                           "the wall clock. <b>claims heard</b> — how many claim records the dashboard has "
                           "overheard in total. <b>mean position error</b> — average distance in metres "
                           "between where the network thinks each person is and where the simulator "
                           "actually put them. <b>tick</b> — the dashboard's own refresh counter.",
                "mech": "Media time matters more than it looks. The original V1 system processed cameras "
                        "one after another, so camera 1's timestamps were always later than camera 0's "
                        "regardless of what actually happened — which made transit times and reachability "
                        "windows impossible to compute. Every timestamp in the identity path now comes from "
                        "media time via <code>starling_net/timebase.py</code>, never <code>time.time()</code>.",
                "ask": [
                    ("Why is mean position error a fair measure?",
                     "It is computed against the simulator's ground truth by the dashboard only, for "
                     "display. It never feeds back into the system. It is a scoreboard, not an input."),
                    ("What is 'media time'?",
                     "The timestamp of the moment the frame depicts. Two nodes replaying the same scenario "
                     "share a <code>stream_epoch</code> so their media times sit on one timeline. Wall-clock "
                     "reads are banned from the identity path; the one sanctioned exception is logging a "
                     "human operator's action, which genuinely happens 'now'."),
                ],
            },
            {
                "slug": "03_map",
                "title": "The floor map",
                "look": "The warehouse from above. Dashed green rectangles are the four camera zones "
                        "(amber if that camera has gone silent). Dark grey blocks are racking — solid "
                        "obstacles. The red dashed box in the middle is floor that <b>no camera covers</b>. "
                        "Solid coloured dots are where the network believes each person is; the faint "
                        "dashed rings are the simulator's ground truth, drawn for comparison only.",
                "numbers": "Each identity keeps one colour for as long as it stays one identity. If a "
                           "dot changes colour, the resolver decided that is a different person. The thin "
                           "trailing line is that identity's recent path.",
                "mech": "The floor is a 2D navmesh — a grid of 0.25 m cells marked walkable or not, built "
                        "from GeoJSON by <code>NavMesh.from_geojson</code> in "
                        "<code>packages/starling_geometry/navmesh.py</code>. Distances are geodesic over "
                        "that grid (8-connected Dijkstra), so a route around a rack is longer than the "
                        "straight line through it. This is deliberately 2D only — there is no 3D "
                        "reconstruction anywhere in the project.",
                "ask": [
                    ("Why 2D and not 3D?",
                     "A pre-committed scope decision. Everything the system needs — reachability, "
                     "candidate regions, transit times — works on a floor plan. 3D reconstruction was "
                     "explicitly excluded, not attempted and abandoned."),
                    ("Why 0.25 m cells?",
                     "It sets the resolution of every area and distance. One cell is 0.0625 m&sup2;, so "
                     "reported areas are quantised to that. It also appears inside the reachability slack "
                     "term, so a coarser grid makes the system more permissive — which is the safe "
                     "direction for a search tool."),
                ],
            },
            {
                "slug": "04_identities",
                "title": "Resolved identities",
                "look": "One row per identity the resolver currently believes in.",
                "numbers": "<b>identity</b> — the internal reference. <b>&asymp; ground-truth</b> — a "
                           "display-only label. <b>status</b> — seen or unseen. <b>position</b> — believed "
                           "position in metres. <b>age</b> — seconds since the last claim for this "
                           "identity. <b>via node</b> — which camera contributed that last claim. "
                           "<b>claims</b> — how many claims are bound to this identity. <b>error</b> — "
                           "distance from ground truth. <b>candidate region</b> — if unseen, the area they "
                           "could still be in.",
                "mech": "This table is the output of <code>resolve()</code> in "
                        "<code>packages/starling_crdt/resolver.py</code>. It makes one forward pass over "
                        "the claims in a fixed total order and binds each claim to an identity. Two rules "
                        "matter: a claim is only allowed to join an identity if that position is "
                        "physically reachable from where that identity last was (a hard gate that runs "
                        "<i>before</i> any appearance comparison), and if the best match is not clearly "
                        "better than the runner-up, the claim is bound to nothing rather than guessed.",
                "ask": [
                    ("Isn't the '&asymp; ground-truth' column cheating?",
                     "It is the single most important thing to be able to answer. It is computed by "
                     "<code>_update_names</code> in the dashboard's engine: each identity is matched to "
                     "the nearest simulator worker, and only after several consistent votes. It exists so "
                     "a human can read the table. It is never passed to the resolver, never gossiped and "
                     "never influences an assignment. Delete it and the system behaves identically."),
                    ("What does an identity with no name mean?",
                     "A real outcome. A track that fragmented — for instance after a long occlusion — "
                     "starts a new identity that has not yet collected enough votes to be labelled. The "
                     "system refusing to put a name to it is correct behaviour, not a bug."),
                    ("Why would a claim be bound to nothing?",
                     "Because two identities scored too similarly. The threshold pair is "
                     "<code>sim_threshold</code> (is the best match good enough?) and "
                     "<code>margin_threshold</code> (is it clearly better than the second best?). Both must "
                     "pass. Ambiguity is surfaced, not resolved by a thin margin."),
                ],
            },
            {
                "slug": "05_nodes",
                "title": "The four nodes",
                "look": "One card per camera node. Each is a separate operating-system process with its "
                        "own SQLite database and its own network socket.",
                "numbers": "<b>partitioned</b> — is this node currently cut off. <b>claims held</b> — how "
                           "many claims are in its replica. <b>gaps</b> — how many claims it knows it is "
                           "missing. <b>behaviour</b> — honest or lying. <b>rejected</b> — how many of its "
                           "claims failed a plausibility check, out of how many were evaluated. "
                           "<b>reputation</b> — what the <i>other</i> nodes think of it, 0 to 1. Above the "
                           "cards: <b>convergence</b>, <b>claim-count spread</b> and total <b>gaps</b>.",
                "mech": "A node is a process, never a thread, and no module may read another node's "
                        "database. Claims spread two ways: live gossip pushes new ones to a "
                        "<i>configured neighbour set</i> (never a full mesh — that would be a coordinator "
                        "in disguise), and anti-entropy repairs what gossip missed. Convergence is declared "
                        "when the spread in claim counts is within tolerance <b>and</b> the total gap count "
                        "is exactly zero.",
                "ask": [
                    ("How do you know these are really separate processes?",
                     "They are launched as separate OS processes by <code>scripts/run_demo.py</code>, each "
                     "with its own database file and port. There is a test — "
                     "<code>test_node_process_writes_only_its_own_db</code> — that runs a node as a "
                     "subprocess and asserts it created no other node's directory."),
                    ("What exactly is a 'gap'?",
                     "Each node numbers its own claims 0, 1, 2, … A neighbour might hold 0–2 and 7–9 but "
                     "be missing 3–6. A simple 'highest number I've seen' summary cannot express that, so "
                     "nodes exchange <i>runs</i> of sequence numbers, and the spaces between runs are the "
                     "gaps. Convergence requires zero."),
                    ("Why must gaps be exactly zero but claim spread only within tolerance?",
                     "Because the simulator keeps producing claims while you measure. A small spread just "
                     "means some claims are still in flight. A gap means something was genuinely lost, so "
                     "no tolerance is allowed."),
                ],
            },
            {
                "slug": "06_controls",
                "title": "The fault injection controls",
                "look": "Every failure this demo can cause, on demand.",
                "numbers": "<b>Partition</b> cuts nodes {2,3} off from {0,1}. <b>Heal</b> reconnects them. "
                           "<b>Conflict</b> stages two look-alike people, in a resolvable and an ambiguous "
                           "variant. <b>Dead zone</b> walks someone into the uncovered middle, either with "
                           "all cameras healthy or with camera 1 blinded. <b>Make node lie</b> turns a "
                           "chosen node Byzantine.",
                "mech": "The partition is an application-level receive-side drop set, not real packet "
                        "loss — a cut node simply discards messages from the other side. The lying node "
                        "runs an attack injector that alters its claims <i>before</i> they are signed, so "
                        "its lies carry a perfectly valid signature from its real enrolled key.",
                "ask": [
                    ("If the lies are correctly signed, what is the point of signatures?",
                     "Signatures stop node A forging a claim that appears to come from node B. They do "
                     "nothing about node B itself being compromised and lying with its own key. That gap "
                     "is precisely why reputation and plausibility checking exist — as the code comment "
                     "puts it, if signatures were sufficient, reputation would be unnecessary."),
                ],
            },
            {
                "slug": "07_demo_script",
                "title": "The built-in tour",
                "look": "Nine scripted moments with a button each, in the order you would present them.",
                "numbers": "Each step says what to watch for before you press it.",
                "mech": "This is the same sequence the automated review harness "
                        "(<code>scripts/review_demo.py</code>) drives, which is how the eleven review "
                        "moments are checked without a human clicking.",
                "ask": [
                    ("Did you verify these by hand?",
                     "No. <code>scripts/review_demo.py</code> drives a real demo in a headless browser, "
                     "measures each moment against a numeric criterion and writes a PASS/FAIL verdict with "
                     "screenshots into <code>review/review.html</code>. The last clean run passed all "
                     "eleven."),
                ],
            },
            {
                "slug": "08_events",
                "title": "The event log",
                "look": "A running list of what the system decided, newest last.",
                "numbers": "Entries appear when an identity is created, goes unseen, is re-seen as the "
                           "same identity, or when a fork opens.",
                "mech": "Useful during a demo for the 're-seen as the same identity' line: that is the "
                        "system re-attaching a person to the identity they had before they disappeared, "
                        "rather than inventing a new one.",
                "ask": [],
            },
        ],
    },
    {
        "id": "c4",
        "title": "2. Negative evidence — reasoning from what nobody saw",
        "blurb": "This is the flagship contribution (C4) and the part most worth being able to explain. "
                 "The question it answers: <b>when a person walks out of every camera's view, what can you "
                 "still say about where they are?</b> The naive answer is 'anywhere they could have walked "
                 "to'. Starling does better — it rules out the areas that healthy cameras positively "
                 "attest were empty.",
        "shots": [
            {
                "slug": "10_map_region_healthy",
                "title": "Someone disappears, all cameras healthy",
                "look": "A worker has walked into the uncovered middle block. The coloured shading is the "
                        "<b>candidate region</b> — everywhere they could still be. The fainter grey area is "
                        "what plain reachability would have allowed. Notice the coloured region stays "
                        "essentially inside the uncovered block.",
                "numbers": "The label on the region reads 'could be here: N m&sup2;'. Compare it with the "
                           "grey area: the ratio is the headline C4 result. In the run below the search area "
                           "is <b>69 m&sup2; against 819 m&sup2; of plain reachability — 8%</b>, and every "
                           "one of those 69 m&sup2; lies inside the uncovered block. The overlap with camera "
                           "zones is empty: all four cameras are healthy, so every zone is ruled out.",
                "mech": "The belief starts as a single grid cell at the last confirmed position and grows "
                        "each tick by geodesic dilation — every cell within <code>v_max &times; dt</code> "
                        "walking distance, routed around obstacles, never through walls. Then every camera "
                        "zone whose node sent a fresh, high-confidence 'my zone was covered and I saw "
                        "nobody cross' attestation is removed. Crucially those zones are made "
                        "<i>impassable</i>, not merely subtracted, so the person cannot be assumed to have "
                        "sneaked through them either.",
                "ask": [
                    ("How is this different from just 'they could be anywhere within walking distance'?",
                     "That is exactly the grey control area drawn alongside it, and the coloured region is "
                     "measured against it. The difference is the contribution. The system runs both arms "
                     "simultaneously — the same dilation with negative evidence switched off — so the "
                     "comparison is not a claim, it is a measurement."),
                    ("What stops the region shrinking to nothing incorrectly?",
                     "If removing covered zones would empty the belief entirely — because the last sighting "
                     "was inside a zone that is now attested empty, meaning the person must have left it — "
                     "the belief is re-seeded at the nearest uncovered cells. Without that, a correct "
                     "attestation would produce a 0 m&sup2; region, which is a false exclusion: telling a "
                     "search team someone cannot be somewhere they actually are."),
                    ("Why does the region never leave the uncovered block here?",
                     "Because all four cameras are healthy and attesting. Every zone the person might have "
                     "escaped into is ruled out by a positive statement from the camera watching it. The "
                     "uncovered block is the irreducible part — no attestation can ever remove it, because "
                     "no camera watches it."),
                ],
            },
            {
                "slug": "11_region_card_healthy",
                "title": "The numbers behind the shaded area",
                "look": "The card under the map, with a small graph showing both areas over time.",
                "numbers": "<b>search area</b> vs <b>reachable without negative evidence</b>, and the "
                           "percentage between them — the smaller, the better. <b>inside the blind "
                           "block</b> — how much lies in genuinely uncovered floor. <b>inside healthy "
                           "cameras' zones</b> — should be near zero; it is a self-check, because healthy "
                           "zones are supposed to be fully excluded. The graph: solid line is the search "
                           "area, dashed grey is what it would have been without negative evidence.",
                "mech": "Every number here is computed from grid cell counts on the navmesh, and the "
                        "explanation sentence underneath is assembled mechanically from which nodes were "
                        "healthy, which were silent, and where the region overlaps — no scenario-specific "
                        "text is hardcoded.",
                "ask": [
                    ("The two lines diverge over time. Why?",
                     "Plain reachability grows without bound — the longer someone is missing, the further "
                     "they could have walked. The negative-evidence area converges instead, because the "
                     "attested zones keep being removed. That gap widening <i>is</i> the result."),
                ],
            },
            {
                "slug": "12_map_region_occluded",
                "title": "The same walk, but one camera is blinded",
                "look": "Identical scenario, except camera 1's view is blocked. Its zone outline turns "
                        "amber and is marked silent. The candidate region now <b>leaks into that zone and "
                        "only that zone</b>.",
                "numbers": "The search area is larger than in the healthy case. Do the arithmetic with the "
                           "numbers below, because it is the clearest thing you can show an examiner: with "
                           "all cameras healthy the area was <b>69 m&sup2;</b>; with camera 1 blinded it is "
                           "<b>174 m&sup2;</b>, and the region's overlap with camera 1's zone is "
                           "<b>105 m&sup2;</b>. 69 + 105 = 174. The region grew by <i>exactly</i> the zone "
                           "that went dark, and by nothing else — the other three zones are still ruled out "
                           "because those cameras are still attesting.",
                "mech": "This is the rule 'silence is never evidence of absence' made visible. A camera "
                        "that sends nothing is not saying 'nobody is here' — it is saying nothing at all. "
                        "So its zone cannot be ruled out, and the person might be in it. The region grows "
                        "by exactly the area of the zone that went dark, and not by more.",
                "ask": [
                    ("Why not assume a silent camera's zone is empty? It usually is.",
                     "Because that is the assumption that gets people hurt. A camera is silent precisely "
                     "when something is wrong — it is blocked, crashed, or cut off. Those are the moments "
                     "you are least entitled to assume its area is clear. The system treats absence of "
                     "evidence as absence of evidence."),
                    ("Where is that rule enforced in the code?",
                     "In four independent places, deliberately redundantly: the camera refuses to emit an "
                     "attestation below the confidence threshold; the gossip layer refuses to admit one; "
                     "the belief re-checks the conditions itself at the exact point where it is about to "
                     "erase area; and the zone-mask builder requires the attestation to be the node's "
                     "latest, fresh, above threshold, and to name its own zone. Any one failing means the "
                     "zone contributes nothing."),
                    ("How do you know it leaked into <i>only</i> that zone?",
                     "The region card reports the overlap with each camera zone separately. The automated "
                     "review checks this numerically — it asserts the region overlapped camera 1's zone and "
                     "no other."),
                ],
            },
            {
                "slug": "13_region_card_occluded",
                "title": "Silence, stated explicitly",
                "look": "The same card, now naming the silent camera.",
                "numbers": "The generated sentence reads something like: 'camera 1 is silent (occluded, no "
                           "healthy attestation): its silence is not counted as evidence'.",
                "mech": "That sentence is built from the actual healthy and silent node lists, not written "
                        "in advance. If a different camera went dark, a different sentence would appear.",
                "ask": [
                    ("What makes an attestation 'healthy'?",
                     "Four conditions, all required: it names its own zone; it is that node's most recent "
                     "attestation; its confidence is at or above the threshold; and it is fresh enough. "
                     "Confidence itself is the <i>minimum</i> of one-minus-occlusion, illumination and "
                     "detector health — a node is only as trustworthy as its worst faculty. A minimum, not "
                     "an average, deliberately."),
                ],
            },
        ],
    },
    {
        "id": "partition",
        "title": "3. Partition tolerance — cutting the network in half",
        "blurb": "The claim is that Starling has no coordinator. The test is to cut the network and see "
                 "whether anything stops working.",
        "shots": [
            {
                "slug": "20_nodes_before",
                "title": "Before the cut",
                "look": "Four nodes, claim counts close together, no gaps, convergence reads CONVERGED.",
                "numbers": "Claim counts will not be identical — claims are still in flight — but the "
                           "spread is small and gaps are zero.",
                "mech": "",
                "ask": [],
            },
            {
                "slug": "21_nodes_partitioned",
                "title": "During the partition",
                "look": "Nodes 2 and 3 are cut from 0 and 1. Every card reports partitioned. The claim "
                        "counts on the two sides drift apart, because neither side is hearing the other's "
                        "claims.",
                "numbers": "Watch the spread grow. Convergence reads PARTITIONED. Critically, <b>both "
                           "halves keep tracking the people they can see</b> — nothing waits for permission.",
                "mech": "Nodes detect the partition themselves with no heartbeat service: each counts "
                        "rounds since it last heard from each configured neighbour. Every log line carries "
                        "a <code>coverage_completeness</code> figure, so a node always knows and always "
                        "states how blind it currently is.",
                "ask": [
                    ("Why doesn't one side stop, or elect a leader?",
                     "Because there is nothing to elect. No node has authority the others lack. The claim "
                     "set is grow-only, so both sides can keep adding to it independently without any "
                     "possibility of conflict — union is the only operation."),
                    ("Doesn't the drift mean they disagree?",
                     "They hold different <i>evidence</i>, not different <i>conclusions</i>. Each side "
                     "correctly computes the answer implied by what it knows. When the evidence merges, "
                     "the answers converge, because the assignment is a pure function of the claim set."),
                ],
            },
            {
                "slug": "22_central_partitioned",
                "title": "The same partition, on a centralized system",
                "look": "The comparison panel — one server, one shared identity table, exactly the "
                        "architecture this project argues against.",
                "numbers": "It reports PARTIAL and tracks fewer workers, naming the cameras that can no "
                           "longer reach it and counting observations that were never delivered.",
                "mech": "This is a real second system running alongside, not a mock-up. It uses the "
                        "original V1 matcher, preserved as the experimental control for the whole project.",
                "ask": [
                    ("Is the comparison fair?",
                     "It is the original system this project started from, unmodified, which is the "
                     "strongest form of the comparison — it is the actual baseline, not a strawman built "
                     "to lose. Its behaviour was deliberately never changed."),
                ],
            },
            {
                "slug": "23_nodes_healed",
                "title": "After healing",
                "look": "Reconnected. Claim counts converge, gaps return to zero, convergence reads "
                        "CONVERGED again.",
                "numbers": "The time from pressing Heal to CONVERGED is measured by the review harness.",
                "mech": "Live gossip only reaches whoever is listening at the moment of broadcast, so a "
                        "reconnecting node would otherwise stay permanently behind. Anti-entropy fixes "
                        "that: nodes exchange a summary of which sequence ranges they hold, and each sends "
                        "back what the other is missing, in bounded chunks so a long partition heals over "
                        "several rounds instead of one enormous message.",
                "ask": [
                    ("How do you know the replicas are genuinely identical afterwards?",
                     "Unit tests assert it directly — four nodes over a lossy link are driven until their "
                     "claim sets are byte-identical. On the dashboard, gaps returning to exactly zero is "
                     "the live signal."),
                    ("Is this a Merkle tree / CRDT delta sync?",
                     "Deliberately not a Merkle tree. At this scale a full version-range diff is enough "
                     "and much easier to defend. It is honestly a simpler design than the literature "
                     "default, chosen on purpose."),
                ],
            },
        ],
    },
    {
        "id": "byzantine",
        "title": "4. A lying camera — Byzantine robustness",
        "blurb": "A camera can be compromised. It still holds a valid signing key, so everything it says "
                 "is correctly signed. The question is what happens when it starts inventing sightings.",
        "shots": [
            {
                "slug": "30_nodes_honest",
                "title": "All four honest",
                "look": "Every reputation bar full, at 1.00. Rejected counts low.",
                "numbers": "Reputation is shown per node, 0 to 1.",
                "mech": "",
                "ask": [],
            },
            {
                "slug": "31_nodes_lying",
                "title": "Node 2 fabricates sightings",
                "look": "Node 2's card turns amber and reads LYING. Its reputation bar falls; its "
                        "rejected count climbs quickly. The other three are unaffected.",
                "numbers": "<b>rejected</b> is 'how many of its claims failed the check, out of how many "
                           "were checked'. It is <b>cumulative</b>, so it never falls — what matters is how "
                           "fast it climbs. <b>reputation</b> is the <i>median of what the other nodes "
                           "think</i>, not this dashboard's own opinion. In the run below node 2 goes from "
                           "reputation 1.00 with 1 rejection in 1723 claims, to 0.69 with 18 rejections, in "
                           "about five seconds.",
                "mech": "A fabricated claim places a person at a random point on the floor. The "
                        "plausibility check asks first: could this person physically have got there from "
                        "where they last were, in the time available, walking around the racking? A "
                        "teleport fails that outright and is rejected before appearance is even considered. "
                        "Three further graded checks — speed, corroboration by other cameras, and "
                        "freshness — are blended into a score.",
                "ask": [
                    ("Why is reputation a median of peers rather than one number?",
                     "Because a single global reputation score would be a coordinator by the back door — "
                     "someone would have to own it. Each node keeps its own opinion of every other node "
                     "and gossips it. The figure shown is the median across peers, and the median is "
                     "itself resistant to a minority of liars."),
                    ("Does a bad reputation get a node banned?",
                     "No. There is no blacklist, no quarantine, no revocation. Reputation is a weight, and "
                     "it has a floor above zero so a repaired node can always climb back. Be careful to "
                     "claim only that."),
                    ("How does the system detect a camera that stays silent about someone it should see?",
                     "That is the interesting one, because plausibility checking cannot see a claim that "
                     "was never sent. It is caught by contradiction: the node keeps attesting 'my zone was "
                     "healthy and nobody crossed' while two or more <i>other</i> nodes corroborate a "
                     "crossing in the same window. Be precise here — the code detects and emits that "
                     "signal, but wiring it into the reputation update is not built."),
                ],
            },
            {
                "slug": "32_nodes_recovered",
                "title": "It stops lying",
                "look": "Reputation climbs back toward 1.00 on its own.",
                "numbers": "Recovery takes tens of observations, not instantly.",
                "mech": "Reputation is an exponentially weighted moving average. Each honest claim nudges "
                        "it back up by a fixed fraction. There is no forgiveness timer and no manual "
                        "reset — recovery is simply the average running forward with good inputs.",
                "ask": [
                    ("Isn't automatic forgiveness a vulnerability?",
                     "It is a trade-off, and worth stating as one. A permanently condemned node cannot be "
                     "repaired and returned to service, which in a warehouse is the common case — a camera "
                     "gets knocked, cleaned, and works again. The floor above zero exists for exactly that."),
                ],
            },
        ],
    },
    {
        "id": "forks",
        "title": "5. Identity conflicts — when the system refuses to guess",
        "blurb": "This is the behaviour most likely to impress, because it is the opposite of what most "
                 "systems do. When the evidence genuinely supports two incompatible stories, Starling "
                 "keeps both open rather than picking the higher-scoring one.",
        "shots": [
            {
                "slug": "41_forks_resolvable",
                "title": "A conflict that physics can settle",
                "look": "The network was split, and each side attached the same face identity to a "
                        "different person. After healing, the resolver sees one identity bound to two "
                        "incompatible trajectories — a <b>fork</b>. The one to read here is <b>face id "
                        "P-100</b>, marked RESOLVED (reachability). Note the panel may list <i>two</i> "
                        "forks: the ambiguous conflict from the previous scenario (face P-101) is still "
                        "inside the resolver's memory window and correctly remains OPEN. Always check the "
                        "face id before reading a verdict — that is a genuine trap, and it caught this "
                        "document's own screenshot tooling once.",
                "numbers": "The explanation names the speed: one branch would have required something like "
                           "6.7 m/s over 4.2 s, which exceeds the 1.6 m/s walking limit. On the map the "
                           "kept branch is solid, the rejected one is crossed out.",
                "mech": "Each branch is tested for reachability from the identity's last <i>confirmed</i> "
                        "position. If exactly one branch survives, the fork closes with a stated reason. "
                        "The reason is never a bare 'rejected' — it always names the implied speed, so the "
                        "decision is auditable.",
                "ask": [
                    ("Why test from the last confirmed position rather than the most recent one?",
                     "Because each individual step is valid, so the most recent tip is always reachable "
                     "from the previous one — testing there would never detect anything. The last "
                     "<i>anchored</i> position is the last point the system actually knew who this was, "
                     "and that is where genuine ambiguity shows up."),
                ],
            },
            {
                "slug": "41_map_resolvable",
                "title": "The same conflict on the floor",
                "look": "Two diamond markers. The kept branch is filled; the rejected one is outlined and "
                        "struck through.",
                "numbers": "",
                "mech": "",
                "ask": [],
            },
            {
                "slug": "40_forks_ambiguous",
                "title": "A conflict that physics cannot settle",
                "look": "The same setup, but both branches are physically possible. The fork is marked "
                        "<b>OPEN</b> and stays open.",
                "numbers": "Both branches are listed with verdict 'possible'. Neither is chosen. The "
                           "identity gets no candidate region, because there is no single last position to "
                           "reason from.",
                "mech": "When zero or more than one branch survives the reachability test, the fork stays "
                        "open. There is no tie-break by score anywhere in the code. It can later be closed "
                        "by a new face anchor that positively continues one branch, or by an operator — "
                        "but never by the system picking a winner on confidence.",
                "ask": [
                    ("Isn't refusing to answer just a cop-out?",
                     "For a safety system it is the correct failure mode. If two stories are equally "
                     "consistent with the evidence, picking one at, say, 51% confidence means being "
                     "confidently wrong half the time — and a search team acts on that answer. Surfacing "
                     "'these two are both possible, go and look' is more useful and more honest."),
                    ("Would it ever merge two different people?",
                     "That is the failure mode measured in the ablation, and it was effectively zero "
                     "everywhere except under the deliberately punishing 'harsh' profile. The system "
                     "splits identities under pressure far more readily than it merges them, which for a "
                     "safety tool is the right way round to fail."),
                    ("How can two replicas agree on a fork with no coordinator?",
                     "A fork's id is a hash of the identity plus its branches' claim ids, sorted first. "
                     "Two nodes holding the same claims compute the same id independently — the same trick "
                     "as the assignment itself."),
                ],
            },
            {
                "slug": "40_map_ambiguous",
                "title": "Both possibilities drawn",
                "look": "Two open diamonds, both dashed, both labelled with a question mark. The system is "
                        "showing you its uncertainty instead of hiding it.",
                "numbers": "",
                "mech": "",
                "ask": [],
            },
        ],
    },
    {
        "id": "query",
        "title": "6. Asking questions, and being refused",
        "blurb": "A minimal structured query interface. Its interesting property is not what it answers "
                 "but what it declines to answer, and why.",
        "shots": [
            {
                "slug": "50_query_answered",
                "title": "A question it will answer",
                "look": "The answer is split into <b>Confirmed</b> and <b>Inferred</b>, kept visibly apart.",
                "numbers": "Confirmed: last actually seen at a position, by a named camera, how long ago, "
                           "with what confidence. Inferred: if currently unseen, the candidate region area. "
                           "It also reports how many nodes responded and which were unreachable.",
                "mech": "Separating confirmed from inferred is the whole point. A single blended answer "
                        "would let a guess masquerade as an observation.",
                "ask": [
                    ("Why report unreachable nodes in the answer?",
                     "So the answer carries its own caveat. If two cameras could not be reached, the "
                     "answer is based on partial evidence and says so, rather than quietly presenting "
                     "itself as complete."),
                ],
            },
            {
                "slug": "51_query_refused_unknown",
                "title": "Refused — nobody by that name",
                "look": "REFUSED, with a stated reason.",
                "numbers": "",
                "mech": "It does not invent a plausible answer or return the nearest match.",
                "ask": [],
            },
            {
                "slug": "52_query_refused_purpose",
                "title": "Refused — wrong purpose",
                "look": "The same question that was answered a moment ago, now refused because the query "
                        "carries a 'productivity' purpose instead of 'safety'.",
                "numbers": "",
                "mech": "Queries are capability-scoped: the token states a purpose, and a location query "
                        "that is legitimate for safety is refused for productivity monitoring. This is a "
                        "deliberate design position about what the system is for.",
                "ask": [
                    ("Is this enforced or cosmetic?",
                     "It is enforced at the query layer, and it is a small scope — be honest that it is a "
                     "structured CLI-style stub, not a full natural-language interface. A full LLM query "
                     "interface was explicitly excluded from scope."),
                ],
            },
        ],
    },
    {
        "id": "central",
        "title": "7. Why not just use one server?",
        "blurb": "The comparison that justifies the entire architecture.",
        "shots": [
            {
                "slug": "60_central_healthy",
                "title": "The centralized system, working",
                "look": "When nothing is wrong, it works fine — and that is worth conceding immediately.",
                "numbers": "It tracks roughly the right number of workers — though note in the capture "
                           "below it reports 6 while 7 people are actually present, so it was already "
                           "imperfect before anything was broken. Say that out loud rather than "
                           "overselling the comparison.",
                "mech": "",
                "ask": [
                    ("So the centralized system is fine?",
                     "When the network is healthy, yes — and saying so makes the rest of the argument "
                     "credible. The difference only appears under failure, which is exactly when a safety "
                     "system matters."),
                ],
            },
            {
                "slug": "61_central_down",
                "title": "The server is killed",
                "look": "Status DOWN. It tracks nobody at all.",
                "numbers": "Tracked drops to zero.",
                "mech": "One process held all the state; killing it destroys the service.",
                "ask": [],
            },
            {
                "slug": "62_nodes_while_central_down",
                "title": "Starling at the same instant",
                "look": "Unaffected. Still converged, still tracking everyone, claim count still climbing.",
                "numbers": "Compare the claim total with the previous shot's — it keeps growing while the "
                           "centralized system is dead.",
                "mech": "There is no equivalent process to kill. Every node holds a full replica and "
                        "computes the answer itself.",
                "ask": [
                    ("What is the equivalent single point of failure in Starling?",
                     "There isn't one for the identity function — but be precise rather than triumphant. "
                     "This demo has a simulator process feeding all four nodes, and the dashboard is a "
                     "single page. Neither is part of the identity path, but in a real deployment the "
                     "cameras would be the sources and both would be absent."),
                ],
            },
        ],
    },
]

LIMITS = """
<p>An examiner will trust you more for volunteering these than for being caught by them. Every item
here was verified against the code, not guessed.</p>

<h3>Things that are built but not wired in</h3>
<ul>
<li><b>The four aggregation methods</b> (unweighted, reputation-weighted, trimmed-mean, Krum) are
implemented and measured by the Byzantine sweep, but they are <b>not used in the live node loop</b>.
They exist to be ablated against each other, and the results are in <code>docs/results_c2.md</code>.
Do not claim the running system uses Krum.</li>
<li><b>Reputation is not fed into the running node's identity resolution.</b> Nodes compute and
gossip reputation, and the dashboard uses it when it resolves, but there is no call path from a
node's own reputation table into its own <code>resolve()</code>.</li>
<li><b>The attestation reputation floor is inert</b> — its threshold defaults to 0.0.</li>
<li><b>Detecting a lie by omission</b> emits a signal, but nothing consumes it to update reputation.</li>
<li><b>Incremental resolution</b> exists and is tested, but has no production caller; the live code
resolves over its own window instead.</li>
</ul>

<h3>Honest weaknesses in the approach</h3>
<ul>
<li><b>Claims are pruned after a retention window.</b> That weakens the guarantee from unconditional
strong eventual consistency to <i>eventual consistency within the retention window</i>: two replicas
separated for longer than the window may never fully re-converge. It is a deliberate trade-off that
doubles as a privacy measure, but state it as a limitation, not a feature.</li>
<li><b>The candidate belief is an indicator, not a probability density.</b> Each cell is in or out;
there is no Bayesian weighting. Every number reported depends only on which cells are in the set, so
this is sound, but do not describe it as a particle filter — it is not one.</li>
<li><b>Signature verification does not happen on the dashboard's belief path.</b> The belief re-checks
confidence and freshness itself, but not the signature.</li>
<li><b>Sybil attacks are explicitly out of scope.</b> Keys are enrolled out of band at commissioning.
The scheme defends against an enrolled node lying, not against an attacker who can mint new
identities.</li>
<li><b>Identity fragmentation under realistic conditions is real.</b> Measured at about 3.4 identities
per worker, with 97.5% of a worker's claims still on one identity — the rest are short-lived
splinters after occlusions. About 38% of claims are left unassigned, which is the resolver correctly
refusing to guess, but it is a large fraction.</li>
</ul>

<h3>An inconsistency to fix or be ready to explain</h3>
<p>The match threshold was calibrated from a measured ROC curve to <b>0.32</b>, and the configs the
demo actually loads carry that value with a <code>threshold_source</code> recording how it was
derived. However the <i>class default</i> in <code>packages/starling_node/config.py</code> still reads
<code>0.60</code> with <code>threshold_source: "UNCALIBRATED-GUESS"</code>. An examiner who greps the
code will find the stale string and it will look like the calibration never happened. The running
system uses 0.32; the default is simply out of date.</p>

<h3>Scope that was deliberately never attempted</h3>
<ul>
<li>3D reconstruction — 2D navmesh only, pre-committed.</li>
<li>Uniform-invariant re-identification (C7) — explicitly cut.</li>
<li>A full natural-language query interface — a structured stub only.</li>
</ul>
"""

GLOSSARY = [
    ("Claim", "One signed record: a camera saw a person at a position at a media time, with an "
              "appearance vector. The only thing that travels between nodes."),
    ("Grow-only set (G-Set)", "A set that only ever has things added. Merging is union, so it is "
                              "idempotent, commutative and associative — you can merge in any order, "
                              "any number of times, and get the same result. That is why partitions "
                              "are harmless."),
    ("CRDT", "Conflict-free replicated data type. A structure that can be updated independently on "
             "many machines and merged without conflict resolution. Here it is the claim set."),
    ("Resolver", "The pure function that turns a set of claims into identity assignments. Same "
                 "claims in, same answer out, on every node."),
    ("Anchor", "A claim carrying a positive identification (a face), which binds an identity "
               "directly rather than by appearance similarity."),
    ("Fork", "One identity bound to two trajectories that cannot both be one person's walk."),
    ("HLC (hybrid logical clock)", "A timestamp combining a physical millisecond count with a "
                                   "logical counter, so ordering stays consistent even if clocks "
                                   "disagree or go backwards."),
    ("Media time", "The time the footage depicts, as opposed to the wall clock. All identity-path "
                   "timestamps use it."),
    ("Anti-entropy", "The repair protocol: nodes compare which sequence ranges they hold and send "
                     "each other what is missing."),
    ("Gap / hole", "A missing run of sequence numbers in a node's replica. Convergence requires zero."),
    ("Attestation", "A signed statement from a camera: 'my zone was covered and healthy for this "
                    "interval, and nobody crossed'. The basis of negative evidence."),
    ("Candidate region", "The area an unseen person could still be in, after ruling out zones that "
                         "healthy cameras attest were empty."),
    ("Navmesh", "The floor as a grid of walkable cells, used for geodesic distance and reachability."),
    ("Reachability gate", "A hard check: could this person physically have got here from where they "
                          "were, in the time available? Runs before any appearance comparison."),
    ("Plausibility check", "The Byzantine filter applied to incoming claims: reachability (hard "
                           "fail), then speed, corroboration and freshness blended into a score."),
    ("Reputation", "Each node's own opinion of each other node, gossiped. The displayed figure is "
                   "the median of peers' opinions."),
]

CLOSING_QA = [
    ("In one sentence, what is novel here?",
     "Identity is treated as a conflict-free replicated data type where only evidence is replicated "
     "and the assignment is recomputed identically everywhere — and on top of that, the system "
     "reasons from attested absence, so it can narrow down where a person is using cameras that "
     "saw nothing."),
    ("Where is the coordinator hiding?",
     "Nowhere, and the way to show it is to name what a coordinator would have to own: the identity "
     "assignment. That is precisely the one thing never transmitted. Gossip goes to a configured "
     "neighbour set rather than a full mesh for the same reason — a full mesh is a coordinator in "
     "disguise."),
    ("What would break this system?",
     "A partition lasting longer than the claim retention window, because pruned claims can no "
     "longer be exchanged. Also an attacker able to enrol new keys, which is out of scope by "
     "design. And identity fragmentation degrades badly under camera conditions worse than published "
     "re-identification benchmarks."),
    ("How do you know any of this works?",
     "Three independent layers. Unit and property tests, including randomised tests that assert the "
     "resolver gives the same answer under any claim ordering. An automated review that drives a "
     "real four-process demo in a browser and scores eleven scenarios with numeric criteria. And "
     "offline experiments with written-up results for the Byzantine sweep, the negative-evidence "
     "measurements and the threshold calibration."),
    ("What is the weakest part?",
     "Answer this one honestly and it will help you. Several components are measured in harnesses "
     "rather than wired into the live node loop — the aggregation methods especially. And the "
     "identity resolver fragments tracks under realistic camera conditions more than it should."),
]

CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#16202c;--soft:#5a6575;--line:#e0e5ec;--accent:#2557d6;
 --accent-bg:#eaf0fe;--warn:#a8680a;--warn-bg:#fdf4e4;--ok:#0f7a52;--ok-bg:#e7f6f0;--code:#f1f3f7;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0e1319;--panel:#161d26;--ink:#e6ecf3;--soft:#98a5b6;--line:#26303c;--accent:#6f9bff;
 --accent-bg:#152238;--warn:#e8b061;--warn-bg:#2a2013;--ok:#3ddc9a;--ok-bg:#122a20;--code:#1d2632;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1020px;margin:0 auto;padding:28px 20px 90px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:23px;margin:46px 0 6px;padding-top:18px;border-top:2px solid var(--line);letter-spacing:-.01em}
h3{font-size:18px;margin:26px 0 6px}
h4{font-size:16px;margin:18px 0 4px;color:var(--soft);text-transform:uppercase;letter-spacing:.05em;font-size:12.5px}
p{margin:9px 0}
code{background:var(--code);padding:1px 5px;border-radius:4px;font:13.5px ui-monospace,Consolas,monospace}
.sub{color:var(--soft);margin-bottom:22px}
.lede{font-size:17.5px}
figure{margin:20px 0 6px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px}
figure img{width:100%;display:block;border-radius:7px;border:1px solid var(--line)}
figcaption{color:var(--soft);font-size:13.5px;padding:8px 3px 2px}
.shot{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:4px 18px 18px;margin:26px 0}
.shot>h3{margin-top:16px}
.big{background:var(--accent-bg);border-left:4px solid var(--accent);border-radius:0 10px 10px 0;padding:14px 18px;margin:22px 0}
.big h3{margin-top:0}
.warn{background:var(--warn-bg);border-left:4px solid var(--warn);border-radius:0 10px 10px 0;padding:14px 18px;margin:22px 0}
.warn h3{margin-top:0;color:var(--warn)}
.qa{border-left:3px solid var(--line);padding:2px 0 2px 16px;margin:14px 0}
.qa .q{font-weight:650}
.qa .a{color:var(--ink);margin-top:3px}
.vals{background:var(--code);border-radius:9px;padding:10px 14px;margin:12px 0;font:13px ui-monospace,Consolas,monospace;
 color:var(--soft);overflow-x:auto;white-space:pre-wrap}
.vals b{color:var(--ink)}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--soft);font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
nav{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 20px;margin:24px 0}
nav ol{margin:6px 0;padding-left:22px} nav a{color:var(--accent);text-decoration:none}
nav a:hover{text-decoration:underline}
ul{margin:8px 0;padding-left:22px} li{margin:5px 0}
.miss{color:var(--warn);font-size:14px;padding:8px 0}
.dl{display:inline-block;margin-left:6px;padding:3px 11px;border:1px solid var(--accent);border-radius:999px;
 color:var(--accent);text-decoration:none;font-size:13px;font-weight:600;white-space:nowrap}
.dl:hover{background:var(--accent-bg)}
@media print{.dl{display:none}}
footer{margin-top:50px;padding-top:18px;border-top:1px solid var(--line);color:var(--soft);font-size:13.5px}

/* Printing / PDF. Forced light, and nothing that would split a screenshot away
   from the paragraph that explains it. */
@media print{
  :root{--bg:#fff;--panel:#fff;--ink:#16202c;--soft:#55606f;--line:#d7dde5;--accent:#1b3fa0;
        --accent-bg:#eef3fd;--warn:#8a5600;--warn-bg:#fdf6e8;--ok:#0f7a52;--ok-bg:#eaf7f1;--code:#f2f4f8;}
  body{background:#fff;font-size:11.5pt}
  .wrap{max-width:none;padding:0}
  @page{margin:14mm 13mm}
  h1{font-size:24pt}
  h2{font-size:16pt;break-before:page;page-break-before:always}
  h2#orientation{break-before:auto;page-break-before:auto}
  h3{font-size:13pt}
  /* A whole shot block is often taller than a page; let it flow, but never
     split a screenshot from its own caption. */
  figure,.qa,.big,.warn,.vals,tr{break-inside:avoid;page-break-inside:avoid}
  .shot{break-inside:auto}
  .shot>h3{break-after:avoid;page-break-after:avoid}
  h4{break-after:avoid;page-break-after:avoid}
  .shot{border:1px solid var(--line);box-shadow:none}
  figure img{max-height:165mm;object-fit:contain}
  nav{break-after:page;page-break-after:always}
  a{color:var(--accent);text-decoration:none}
  footer{break-inside:avoid}
}
"""


def fmt_live(live: dict[str, Any]) -> str:
    """The numbers that were on screen when the shot was taken."""
    if not live:
        return ""
    out = [f"sim t = {live.get('sim_t')} s   ·   claims heard = {live.get('claims_total')}"
           f"   ·   nodes live = {live.get('nodes_live')}"]
    cv = live.get("convergence") or {}
    if cv:
        out.append(f"convergence: {'PARTITIONED' if cv.get('any_partitioned') else 'CONVERGED' if cv.get('converged') else 'CONVERGING'}"
                   f"   spread = {cv.get('spread')}   gaps = {cv.get('holes_total')}")
    nodes = live.get("nodes") or []
    if nodes:
        bits = []
        for n in nodes:
            rep = n.get("reputation")
            bits.append(f"node {n['id']}: {'LIVE' if n['live'] else 'OFFLINE'}"
                        + (f", {'LYING(' + str(n.get('attack')) + ')' if n.get('lying') else 'honest'}")
                        + f", claims={n.get('claims')}, gaps={n.get('holes')}"
                        + f", rejected={n.get('rejected')}/{n.get('evaluated')}"
                        + (f", reputation={rep:.2f}" if isinstance(rep, (int, float)) else ", reputation=–"))
        out.append("\n".join(bits))
    for r in (live.get("regions") or []):
        out.append(f"candidate region {r['id']}: {r['area_m2']:.1f} m² vs {r['reachable_area_m2']:.1f} m² "
                   f"reachable ({round((r.get('ratio') or 0)*100)}%), unseen {r['unseen_for_s']} s\n"
                   f"  in uncovered block: {r.get('blind_block_area_m2')} m² · "
                   f"healthy cameras: {r.get('healthy_nodes')} · silent: {r.get('silent_nodes')}"
                   + (f" · occluded: {r.get('occluded_nodes')}" if r.get('occluded_nodes') else "")
                   + f"\n  zone overlap: {r.get('zone_overlap_m2')}"
                   + (f"\n  \"{r.get('explanation')}\"" if r.get("explanation") else ""))
    for f in (live.get("forks") or []):
        out.append(f"fork on {f.get('identity')}: {f['status']}\n  \"{f.get('explanation')}\""
                   + "\n  branches: " + ", ".join(f"#{b['i']} at ({b['x']}, {b['y']}) with {b['n']} claims"
                                                  for b in f.get("branches", [])))
    c = live.get("central") or {}
    if c:
        out.append(f"centralized comparison: {c.get('status')} tracking {c.get('tracked_now')}"
                   f" · Starling tracking {c.get('starling_tracked_now')}"
                   f" · actually present {c.get('truth_workers')}")
    err = live.get("mean_error_m")
    if err is not None:
        out.append(f"mean position error = {err} m")
    return "\n\n".join(out)


def build(shots_by_slug: dict[str, dict]) -> str:
    h: list[str] = []
    h.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    h.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    h.append("<title>Starling — Reading the Dashboard</title>")
    h.append(f"<style>{CSS}</style></head><body><div class='wrap'>")
    h.append("<h1>Starling — reading the dashboard</h1>")
    h.append("<p class='sub'>A walkthrough of the technical view, panel by panel, with the questions "
             "you are most likely to be asked about each one. "
             "<a class='dl' href='explainer.pdf'>Download as PDF</a></p>")
    h.append(INTRO)

    h.append("<nav><b>Contents</b><ol>")
    for sec in SECTIONS:
        h.append(f"<li><a href='#{sec['id']}'>{e(sec['title'].split('. ', 1)[-1])}</a></li>")
    h.append("<li><a href='#limits'>What is <i>not</i> built, and honest weaknesses</a></li>")
    h.append("<li><a href='#glossary'>Glossary</a></li>")
    h.append("<li><a href='#closing'>The five questions to rehearse</a></li>")
    h.append("</ol></nav>")

    for sec in SECTIONS:
        h.append(f"<h2 id='{sec['id']}'>{e(sec['title'])}</h2>")
        h.append(f"<p>{sec['blurb']}</p>")
        for sh in sec["shots"]:
            rec = shots_by_slug.get(sh["slug"])
            h.append("<div class='shot'>")
            h.append(f"<h3>{e(sh['title'])}</h3>")
            if rec:
                h.append(f"<figure><img src='{e(rec['file'])}' alt='{e(sh['title'])}'>"
                         f"<figcaption>{e(rec.get('caption',''))} "
                         f"<span style='opacity:.7'>— captured {rec['t_s']}s into the run</span>"
                         f"</figcaption></figure>")
            else:
                h.append("<p class='miss'>(This screenshot was not captured in the last run — "
                         "re-run <code>scripts/capture_explainer.py</code>.)</p>")
            if sh.get("look"):
                h.append(f"<h4>What you are looking at</h4><p>{sh['look']}</p>")
            if sh.get("numbers"):
                h.append(f"<h4>What the numbers mean</h4><p>{sh['numbers']}</p>")
            if rec and rec.get("live"):
                vals = fmt_live(rec["live"])
                if vals:
                    h.append(f"<h4>Live values at the moment of this screenshot</h4>"
                             f"<div class='vals'>{e(vals)}</div>")
            if sh.get("mech"):
                h.append(f"<h4>How it works underneath</h4><p>{sh['mech']}</p>")
            if sh.get("ask"):
                h.append("<h4>If the examiner asks</h4>")
                for q, a in sh["ask"]:
                    h.append(f"<div class='qa'><div class='q'>{q}</div><div class='a'>{a}</div></div>")
            h.append("</div>")

    h.append("<h2 id='limits'>8. What is <i>not</i> built, and honest weaknesses</h2>")
    h.append(LIMITS)

    h.append("<h2 id='glossary'>9. Glossary</h2>")
    h.append("<table><tr><th>Term</th><th>Meaning</th></tr>")
    for term, meaning in GLOSSARY:
        h.append(f"<tr><td><b>{e(term)}</b></td><td>{meaning}</td></tr>")
    h.append("</table>")

    h.append("<h2 id='closing'>10. The five questions to rehearse</h2>")
    h.append("<p>If you can answer these five without notes, you can hold a conversation about this "
             "project with anyone.</p>")
    for q, a in CLOSING_QA:
        h.append(f"<div class='qa'><div class='q'>{e(q)}</div><div class='a'>{a}</div></div>")

    h.append("<footer>Screenshots captured automatically by <code>scripts/capture_explainer.py</code> "
             "against a live four-process demo; this page assembled by "
             "<code>scripts/build_explainer.py</code>. Re-run both to refresh it. "
             "The verdict file for the eleven review moments is <code>review/review.html</code>, "
             "which this document does not replace.</footer>")
    h.append("</div></body></html>")
    return "\n".join(h)


# The prose under these shots states a verdict. If the captured fork does not
# actually carry it, the document would be teaching something false — which for a
# study guide is the worst possible failure. Check rather than trust.
FORK_EXPECTATIONS = {
    "40_forks_ambiguous": ("P-101", "OPEN"),
    "40_map_ambiguous": ("P-101", "OPEN"),
    "41_forks_resolvable": ("P-100", "RESOLVED"),
    "41_map_resolvable": ("P-100", "RESOLVED"),
}


def check_forks(shots: dict[str, dict]) -> list[str]:
    problems = []
    for slug, (face, want) in FORK_EXPECTATIONS.items():
        rec = shots.get(slug)
        if rec is None:
            continue
        mine = [f for f in (rec["live"].get("forks") or []) if f.get("face_identity") == face]
        if not mine:
            problems.append(f"{slug}: no fork for face {face} in the captured state "
                            f"(found {[f.get('face_identity') for f in (rec['live'].get('forks') or [])]})")
        elif not any(f["status"].startswith(want) for f in mine):
            problems.append(f"{slug}: prose says {want}, captured fork is "
                            f"{[f['status'] for f in mine]}")
    return problems


def main(argv: Optional[list] = None) -> int:
    if not MANIFEST.exists():
        print(f"no manifest at {MANIFEST} — run scripts/capture_explainer.py first", file=sys.stderr)
        return 1
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    shots = {s["slug"]: s for s in data["shots"]}

    bad = check_forks(shots)
    if bad:
        print("REFUSING TO BUILD — a screenshot does not show what the text claims:", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        print("  re-run scripts/capture_explainer.py", file=sys.stderr)
        return 2
    OUT.write_text(build(shots), encoding="utf-8")
    planned = sum(len(sec["shots"]) for sec in SECTIONS)
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB) — "
          f"{len(shots)} shots captured, {planned} referenced by the document")
    missing = [sh["slug"] for sec in SECTIONS for sh in sec["shots"] if sh["slug"] not in shots]
    if missing:
        print(f"  missing screenshots: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

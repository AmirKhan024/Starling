# Presenting Starling to judges

This is the playbook for showing Starling live: what to open, what to click,
what to say, and how to answer the questions judges usually ask. Every
number quoted below is measured by the running system or by a committed
experiment. None of it is a slide.

## Before you start (2 minutes)

```bash
python scripts/run_world_demo.py
```

The launcher opens the **Present** tab
(`http://127.0.0.1:8765/tour`). Every page has the same five tabs: Live
monitor, Inside the system, What if, How it works, Present.

**The laptop needs about 4 GB of free memory.** Close what you don't need
before presenting: extra editor windows, chat apps, and coding assistants
such as Claude Code sessions. If memory is low, the launcher switches to
`--light` by itself (cameras at 2 frames per second, so every camera keeps
up) and says so. A yellow "this computer is overloaded" banner on the pages
means the cameras are falling behind. That is the moment people can be
missed at the gate.

Start the launcher about a minute before you present. The four employees
arrive and check in during the first 40 seconds. Use the tour's arrow keys
or its Next button to move between chapters.

## The one-sentence pitch

> **Starling is a camera network with no central server: each camera thinks
> for itself, they share only small signed facts, and together they still
> know where everyone is, even someone no camera can see.**

## The presentation (Present tab, 11 steps)

Press **Autopilot** (bottom left) and the whole presentation runs by itself in
about five minutes: it opens each page, presses each scenario button and
restores everything at the end, so you can simply talk. Press any step or
Stop to take control.

Each step shows a title, one sentence, one or two buttons and a live check
that turns green. "Presenter note" (hidden by default) holds the line to say.

| # | Step | Click | What turns green |
|---|---|---|---|
| 1 | A warehouse with four cameras | — | all four cameras running |
| 2 | Much more than spotting people | — | notes flowing, zero video |
| 3 | Everyone, named and placed | — | employees checked in at the gate |
| 4 | Ask, and the right camera opens | **Follow Priya** | the camera panel follows her; press 1 Detect to 4 Share |
| 5 | No boss computer | **Ask every camera** | all four give the identical answer |
| 6 | Finding someone no camera can see | **Ask: Where is Priya?** | Priya hidden, her area known |
| 7 | When something breaks | **The server room fails**, **Cut the network** | server down, Starling still places everyone |
| 8 | A camera that lies | **Make camera 2 lie**, then **Stop** | camera 2's trust falls |
| 9 | A stranger walks in | **Send a stranger in** | stranger detected and followed |
| 10 | Emergency roll call | **Press roll call** | roll call answered |
| 11 | Private by design | **Ask how hard Daniel worked** | refused by every camera |

Short slot? Do steps 2, 4, 7, 9 and 10.

## What is real and what is simulated

Say this before anyone asks. It builds trust.

- **Real:**
  - every camera node is its own OS process with its own database;
  - every message is signed with ed25519 and gossiped over the network;
  - detection is YOLO on the actual rendered frames;
  - positions come from calibrated camera geometry;
  - identity, negative evidence, reputation and queries all run in the real code.
- **Simulated:**
  - the building and its people are a 3D world, filmed by virtual cameras;
  - the "network split" button drops messages in the application, rather than unplugging a cable.
- **The comparison server is real too.** It is an actual process receiving
  the four real video streams. It is not part of Starling; it exists to be
  compared with.

## Questions judges ask, and the honest answers

**"Isn't this just a distributed database?"**
No database decides who anyone is. Cameras share *signed observations*,
never identities. Each camera works out the identities itself with the
same deterministic recipe. The answer is a pure function of the
observations, so identical copies give identical answers. The fingerprints
on `/network` prove it live. This is a CRDT applied to identity, which is
contribution C1.

**"Why not a central server? It's simpler."**
Kill it during the demo. A central server is one box that sees everyone and
holds everyone's footage, and when it fails every camera is blind. It also
has to receive every camera's video. On the live demo the four cameras
produce about 2 MB/s of video. Starling's whole network carries tens of
KB/s of signed facts, roughly 50× less on this small site and zero frames.
The exact live ratio is on `/network`. Each fact carries a 384-byte
appearance signature, and gossip re-sends some facts; both can shrink. In a real deployment it would also be the difference between
shipping everyone's footage and shipping none of it.

**"How do you find someone no camera can see?"**
Negative evidence (C4). Working cameras sign "my view is clear and I saw
nobody". Each signed absence removes area from where the person could be.
A broken or covered camera signs nothing, and its silence never counts as
evidence.

**"What if a camera is hacked?"**
Nobody can forge another camera's claims, because every claim is signed.
A camera can still lie in its own name. Its peers check each claim against
physics (could anyone walk there that fast?) and against what other healthy
cameras vouched they saw. A camera caught contradicting the others loses
trust, and its claims count for less (C2). Demo: tour chapter 11.

**"What about an unknown person?"**
They are tracked anyway. The cameras follow people by appearance and
physics, not by name. A person never verified at the gate is flagged on the
manager view, appears on the roll call, and can be asked about ("is there
anyone we don't know?").

**"What happens if the network splits?"**
Both halves keep tracking and answering. When the link returns, the copies
merge by themselves and become identical again. In the scale experiment
that took 2.5 s after healing. If the two halves saw genuinely
contradictory things, the conflict stays open for a human; it is never
settled by picking a winner.

**"Does it scale?"** (see [`results_scale.md`](results_scale.md))
- We measured 4 to 64 separate node processes, each talking to four
  neighbours. Every copy ended up identical.
- A sighting reached all 64 nodes in about 2 s (p50) or 3 s (p95).
- The busiest Starling node received 80–120× less than a central server
  would have to.
- Honest limit: today every camera keeps every sighting, so *total* network
  traffic grows with the square of the camera count. It would pass "everyone
  streams video" at roughly 80–110 cameras.
- The next step is sharing sightings only among nearby cameras. It is
  designed but not built yet. Say so.

**"Is it private?"**
- No video leaves a camera; only facts do.
- Every question carries a signed purpose. Safety, incident and audit
  questions are answered; productivity monitoring is refused.
- Each camera verifies the purpose itself. Demo: tour chapter 14, or ask
  with purpose "Productivity" on the manager view.

**"How accurate is it?"** (see [`results_world_perception.md`](results_world_perception.md))
- Median position error is about 0.3 m against the true position.
- Every employee was named correctly at the gate in the automated review.
- `review/world/review_summary.md` grades every demo moment against ground
  truth.

**"What doesn't work yet?"**
- The appearance signature is clothing colour, tuned for distinct uniforms.
  Two people dressed identically are separated by physics and gate checks,
  not by looks.
- A lie placed inside the liar's own unwatched area can't be contradicted.
- Each camera keeps every sighting, as described under scale above.

## If something goes wrong on stage

- **A yellow "this computer is overloaded" banner:** the laptop cannot keep
  the four camera nodes at their frame rate (usually low memory: close the
  browser tabs you are not using, editors and chat apps; or restart with
  `--fast`). At a low frame rate a camera can miss someone's few seconds at
  the gate.
- **An employee shows as "not verified" and an "Unknown #1" appears:** the
  gate missed their check-in, so Starling follows them without a name. It
  never guesses one. Ask "where is <name>?": it says it cannot verify them
  and points at the unverified person who may be them. The answer is honest,
  and you can say exactly that. Any camera that later recognises them names
  them again.

- **A page looks stuck:** reload it. Every page is a read-only view, and
  reloading changes nothing in the system.
- **Fingerprints differ for a few seconds:** that is honest. A sighting may
  still be travelling round the ring, so ask again. During a network split
  they *should* differ; that is the point of chapter 10.
- **You powered off a camera:** "Power it back on" restarts it. It needs
  about 20–30 s to load its detector, then catches up from its neighbours.
- **Start over:** stop the launcher with Ctrl+C and run it again. Every run
  starts a fresh shift.

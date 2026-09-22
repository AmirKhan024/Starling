# Starling demo — automated review summary (session 3)

Generated 2026-09-22 18:20:46 by `scripts/review_demo.py` (commit `61869f4`). Same content as `review.html`, without images (file names refer to `review/screenshots/`). The centralized system is a comparison, not part of Starling.

## Summary

| # | Moment | Verdict | Key measured numbers | Reason |
|---|---|---|---|---|
| 0 | Startup | **PASS** | all live after 6.6 s | all 4 nodes live and central server healthy 6.6s after launch; all camera zones healthy; demo-script panel lists 9 steps |
| 1 | Normal walk | **PASS** | 4 identities, mean error 0.21 m | 4 identities tracked, labels unchanged for 25 s, max displacement 21.7 m, mean error 0.21 m vs ground truth |
| 2a | Dead zone, healthy exits | **PASS** | region 69 m² vs 932.5 m² reachable (ratio 0.074); max in healthy zones 0 m²; lasted 26.0 s | region confined to the block for 26.0 s (0 m² in healthy zones, at most 0.5 m² outside the block), final 69 m² vs 932.5 m² reachable (ratio 0.074), same identity P-005 on re-emergence |
| 2b | Dead zone, occluded exit | **PASS** | leak into occluded zone 1: 105 m²; into other zones: 0.0 m² | region leaked into camera 1's zone (up to 105 m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in 25 of 25 samples; same identity on re-emergence |
| 3 | Partition and heal | **PASS** | heal→converged 4.2 s, max spread 56.0 | partition shown on all nodes, spread grew to 56.0, converged 4.2s after heal with gaps=0 |
| 4 | Lying node | **PASS** | liar <0.7 after 13.3 s; recovered >0.9 after 8.3 s | liar's reputation < 0.7 after 13.3s (79.0 claims rejected), honest nodes stayed >= 1.0 (their rejected counters grew by [16.0, 0, 0] during the test), recovered > 0.9 8.3s after stopping |
| 5 | Query and refusal | **PASS** | 5 queries (answer, unknown, partitioned, productivity, blind-block) | valid query answered (confirmed/inferred/unreachable); unknown worker and productivity purpose refused with reasons; partition edge case: refused; blind-block query reported: Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothes |
| 6 | Robustness | **PASS** | reload 0.1 s; offline 4.9 s; back 2.9 s | reload recovered in 0.1s; killed node OFFLINE after 4.9s (its camera zone: silent); LIVE again 2.9s after restart; converged 4.8s after restart |
| 7a | Conflict, resolvable | **PASS** | fork RESOLVED_REACHABILITY after heal | no fork while partitioned (363 far-side claims held back); after healing the fork appeared and was resolved by reachability: Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s. |
| 7b | Conflict, ambiguous | **PASS** | fork OPEN; still OPEN 8 s later | no fork while partitioned; after healing one fork appeared and stayed OPEN 8 s later; 2 branch markers drawn at [(5.02, 21.49), (33.37, 12.58)]; explanation: Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is |
| 8 | Centralized comparison | **PASS** | partition / kill / restart of the centralized system vs Starling | partition: centralized tracks 3 (PARTIAL) vs Starling 5 of 5; killed: centralized DOWN/0 while Starling kept 5 of 5 and 227 new claims in 8 s; restarted: HEALTHY |

## Moment 0 — Startup: PASS

**What it should demonstrate:** The dashboard loads and all four node processes, the simulator and the centralized comparison server are up.

**Action taken:** Launched the demo in presenter mode (`scripts/run_demo.py --presenter`, launched here via `DemoLauncher`) and opened the dashboard in headless Chromium.

**Verdict reason:** all 4 nodes live and central server healthy 6.6s after launch; all camera zones healthy; demo-script panel lists 9 steps

### 0a_startup_loaded.jpg  (t = 6.8 s since launch)

Dashboard loaded: 4 nodes live, all four camera zones outlined green (healthy), Demo script panel present.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.6",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.12",
 "claims_per_node": [
  "51",
  "55",
  "51",
  "51"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 18",
  "0 of 16",
  "0 of 17",
  "0 of 17"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.8, 1.5) via node 0 err 0.03",
  "P-002 worker-4 seen @(19.5, 17.7) via node 2 err 0.21",
  "P-003 worker-3 seen @(28.6, 1.4) via node 3 err 0.08",
  "P-004 worker-1 seen @(17.5, 1.4) via node 1 err 0.14"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 59 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "seconds_launch_to_all_nodes_live": 6.6,
  "demo_script_steps_listed": 9,
  "zones_coverage": [
    "healthy",
    "healthy",
    "healthy",
    "healthy"
  ]
}
```

## Moment 1 — Normal walk: PASS

**What it should demonstrate:** Believed worker positions (one colour per resolved identity) move across the floor plan; identities stay consistent; faint ground-truth markers give the comparison.

**Action taken:** Observed only for ~25 s. The four patrol workers stay inside their own camera zones (the stage actor worker-2 only appears in the dead-zone episodes), so 'identity across zones' is exercised in moment 2a.

**Verdict reason:** 4 identities tracked, labels unchanged for 25 s, max displacement 21.7 m, mean error 0.21 m vs ground truth

### 1a_walk_start.jpg  (t = 7.0 s since launch)

Four workers, four identities (P-00x) with ground-truth rings.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.6",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.12",
 "claims_per_node": [
  "51",
  "55",
  "51",
  "51"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 18",
  "0 of 16",
  "0 of 17",
  "0 of 17"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.8, 1.5) via node 0 err 0.03",
  "P-002 worker-4 seen @(19.5, 17.7) via node 2 err 0.21",
  "P-003 worker-3 seen @(28.6, 1.4) via node 3 err 0.08",
  "P-004 worker-1 seen @(17.5, 1.4) via node 1 err 0.14"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 59 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 1b_walk_later.jpg  (t = 15.2 s since launch)

Same identities at new positions a few seconds later.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "12.4",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.14",
 "claims_per_node": [
  "206",
  "209",
  "206",
  "208"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 52",
  "0 of 53",
  "0 of 54",
  "0 of 53"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 1.9) via node 0 err 0.10",
  "P-002 worker-4 seen @(24.9, 18.1) via node 2 err 0.14",
  "P-003 worker-3 seen @(33.9, 1.4) via node 3 err 0.17",
  "P-004 worker-1 seen @(22.1, 1.4) via node 1 err 0.15"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 214 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 1c_walk_25s.jpg  (t = 32.7 s since launch)

25 s in: identities unchanged.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "29.4",
 "convergence": "CONVERGED",
 "spread": "16",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.42",
 "claims_per_node": [
  "557",
  "543",
  "557",
  "559"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 139",
  "0 of 139",
  "0 of 143",
  "0 of 142"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 22.3) via node 0 err 0.21",
  "P-002 worker-4 seen @(15.7, 23.5) via node 2 err 0.74",
  "P-003 worker-3 seen @(39.0, 10.3) via node 3 err 0.09",
  "P-004 worker-1 seen @(19.2, 7.6) via node 1 err 0.65"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 569 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "named_workers": [
    "worker-0",
    "worker-1",
    "worker-3",
    "worker-4"
  ],
  "identities_listed": 4,
  "labels_unchanged_over_25s": true,
  "max_displacement_m": 21.68,
  "mean_position_error_m_avg": 0.21,
  "mean_position_error_m_samples": [
    0.1,
    0.37,
    0.37,
    0.7,
    0.65,
    0.49,
    0.41,
    0.49
  ],
  "per_identity_error_m": [
    0.21,
    0.74,
    0.09,
    0.65
  ]
}
```

## Moment 2a — Dead zone, healthy exits: PASS

**What it should demonstrate:** A worker disappears into the 12x7 m uncovered block for ~27 s. Every exit is watched by a healthy camera that saw nobody leave, so the candidate region must stay inside the block, never include a healthy camera's zone, and be much smaller than plain reachability allows; the same identity is restored on re-emergence.

**Action taken:** Pressed 'Dead zone - healthy exits' (the simulator moves worker-2 from the west door through the block and out through the east zone), then sampled the page (region area, reachable-without-negative-evidence area, healthy-zone overlap, area outside the block) about every second.

**Verdict reason:** region confined to the block for 26.0 s (0 m² in healthy zones, at most 0.5 m² outside the block), final 69 m² vs 932.5 m² reachable (ratio 0.074), same identity P-005 on re-emergence

### 2a1_before.jpg  (t = 32.9 s since launch)

Before the episode: cameras all healthy (green); worker-2 is not in the building yet.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "29.4",
 "convergence": "CONVERGED",
 "spread": "16",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.42",
 "claims_per_node": [
  "557",
  "543",
  "557",
  "559"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 139",
  "0 of 139",
  "0 of 143",
  "0 of 142"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 22.3) via node 0 err 0.21",
  "P-002 worker-4 seen @(15.7, 23.5) via node 2 err 0.74",
  "P-003 worker-3 seen @(39.0, 10.3) via node 3 err 0.09",
  "P-004 worker-1 seen @(19.2, 7.6) via node 1 err 0.65"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 569 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a2_hidden_0s.jpg  (t = 51.2 s since launch)

P-005 hidden 2.4 s: search area 18.3 m² vs 40.9 m² reachable without negative evidence (45%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "47.4",
 "convergence": "CONVERGED",
 "spread": "5",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "953",
  "958",
  "954",
  "956"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 285",
  "0 of 222",
  "0 of 227",
  "0 of 223"
 ],
 "regions": {
  "P-005": {
   "area_m2": 18.3,
   "reachable_m2": 40.9,
   "ratio": "45%",
   "in_blind_block_m2": 18.2,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 16.8) via node 0 err 0.42",
  "P-002 worker-4 seen @(24.5, 17.6) via node 2 err 0.15",
  "P-003 worker-3 seen @(38.7, 23.5) via node 3 err 0.48",
  "P-004 worker-1 seen @(22.9, 1.5) via node 1 err 0.33",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 974 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a3_hidden_5s.jpg  (t = 56.3 s since launch)

P-005 hidden 6.2 s: search area 49.3 m² vs 240.5 m² reachable without negative evidence (21%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "51.2",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.52",
 "claims_per_node": [
  "1033",
  "1037",
  "1033",
  "1035"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 304",
  "0 of 242",
  "0 of 247",
  "0 of 243"
 ],
 "regions": {
  "P-005": {
   "area_m2": 49.3,
   "reachable_m2": 240.5,
   "ratio": "21%",
   "in_blind_block_m2": 49.3,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 12.1) via node 0 err 0.55",
  "P-002 worker-4 seen @(25.0, 19.4) via node 2 err 0.65",
  "P-003 worker-3 seen @(34.6, 23.5) via node 3 err 0.75",
  "P-004 worker-1 seen @(25.1, 2.8) via node 1 err 0.13",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1053 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a4_hidden_10s.jpg  (t = 61.9 s since launch)

P-005 hidden 12.6 s: search area 69 m² vs 695.6 m² reachable without negative evidence (10%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "57.6",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.32",
 "claims_per_node": [
  "1169",
  "1153",
  "1170",
  "1170"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 338",
  "0 of 277",
  "0 of 283",
  "0 of 279"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 695.6,
   "ratio": "10%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 6.7) via node 0 err 0.44",
  "P-002 worker-4 seen @(23.4, 23.5) via node 2 err 0.18",
  "P-003 worker-3 seen @(27.6, 23.5) via node 3 err 0.31",
  "P-004 worker-1 seen @(24.9, 6.8) via node 1 err 0.37",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1174 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a5_hidden_16s.jpg  (t = 67.9 s since launch)

P-005 hidden 17.4 s: search area 69 m² vs 862.3 m² reachable without negative evidence (8%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "62.4",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.45",
 "claims_per_node": [
  "1268",
  "1252",
  "1269",
  "1269"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 357",
  "0 of 297",
  "0 of 303",
  "0 of 298"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 862.3,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 2.6) via node 0 err 0.64",
  "P-002 worker-4 seen @(19.4, 23.3) via node 2 err 0.48",
  "P-003 worker-3 seen @(26.9, 23.2) via node 3 err 0.11",
  "P-004 worker-1 seen @(21.0, 7.4) via node 1 err 0.58",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1276 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a6_hidden_22s.jpg  (t = 74.0 s since launch)

P-005 hidden 23.4 s: search area 69 m² vs 932.5 m² reachable without negative evidence (7%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "68.4",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.59",
 "claims_per_node": [
  "1382",
  "1367",
  "1384",
  "1383"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 389",
  "0 of 330",
  "0 of 337",
  "0 of 333"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 932.5,
   "ratio": "7%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(4.9, 1.4) via node 0 err 0.70",
  "P-002 worker-4 seen @(15.0, 22.0) via node 2 err 0.50",
  "P-003 worker-3 seen @(27.0, 17.2) via node 3 err 0.71",
  "P-004 worker-1 seen @(14.9, 7.3) via node 1 err 0.45",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1391 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a7_reemerged.jpg  (t = 78.2 s since launch)

worker-2 re-emerges from the block; identity now P-005 (before: P-005).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "72.4",
 "convergence": "CONVERGED",
 "spread": "23",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.55",
 "claims_per_node": [
  "1465",
  "1445",
  "1467",
  "1468"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "0.97"
 ],
 "rejected": [
  "1 of 407",
  "0 of 350",
  "0 of 357",
  "0 of 359"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(6.7, 1.4) via node 0 err 1.02",
  "P-002 worker-4 seen @(15.0, 18.1) via node 2 err 0.61",
  "P-003 worker-3 seen @(27.0, 15.4) via node 3 err 0.01",
  "P-004 worker-1 seen @(15.1, 6.3) via node 1 err 0.61",
  "P-005 worker-2 seen @(26.8, 12.0) via node 3 err 0.48"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 1472 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

Measured values:

```json
{
  "seconds_click_to_region_on_page": 17.4,
  "identity_measured": "P-005",
  "identity_after_reemerging": "P-005",
  "same_identity_after": true,
  "n_samples": 25,
  "region_lifetime_s": 26.0,
  "first_area_m2": 18.3,
  "max_area_m2": 69,
  "final_area_m2": 69,
  "reach_at_end_m2": 932.5,
  "final_ratio_area_over_reach": 0.074,
  "max_healthy_zone_overlap_m2": 0,
  "max_area_outside_blind_block_m2": 0.10000000000000142,
  "samples": [
    {
      "t": 0.0,
      "area": 18.3,
      "reach": 40.9,
      "ratio_pct": "45%",
      "blind": 18.2,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 2.4,
      "explanation": "worker-2 unseen 2 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 18 m² instead of 41 m² reachable."
    },
    {
      "t": 1.4,
      "area": 27.7,
      "reach": 77.2,
      "ratio_pct": "36%",
      "blind": 27.7,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 3.4,
      "explanation": "worker-2 unseen 3 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 28 m² instead of 77 m² reachable."
    },
    {
      "t": 2.3,
      "area": 33.8,
      "reach": 125.6,
      "ratio_pct": "27%",
      "blind": 33.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 4.4,
      "explanation": "worker-2 unseen 4 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 34 m² instead of 126 m² reachable."
    },
    {
      "t": 3.3,
      "area": 40.8,
      "reach": 183.1,
      "ratio_pct": "22%",
      "blind": 40.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 5.4,
      "explanation": "worker-2 unseen 5 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 41 m² instead of 183 m² reachable."
    },
    {
      "t": 4.2,
      "area": 49.3,
      "reach": 240.5,
      "ratio_pct": "21%",
      "blind": 49.3,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 6.2,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 49 m² instead of 240 m² reachable."
    },
    {
      "t": 5.1,
      "area": 49.3,
      "reach": 240.5,
      "ratio_pct": "21%",
      "blind": 49.3,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 6.2,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 49 m² instead of 240 m² reachable."
    },
    {
      "t": 6.5,
      "area": 57.9,
      "reach": 328,
      "ratio_pct": "18%",
      "blind": 57.9,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 7.2,
      "explanation": "worker-2 unseen 7 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 58 m² instead of 328 m² reachable."
    },
    {
      "t": 7.5,
      "area": 63.5,
      "reach": 406.4,
      "ratio_pct": "16%",
      "blind": 63.5,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 8.2,
      "explanation": "worker-2 unseen 8 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 64 m² instead of 406 m² reachable."
    },
    {
      "t": 8.4,
      "area": 68.9,
      "reach": 485.5,
      "ratio_pct": "14%",
      "blind": 68.9,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 9.2,
      "explanation": "worker-2 unseen 9 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 486 m² reachable."
    },
    {
      "t": 10.8,
      "area": 69,
      "reach": 695.6,
      "ratio_pct": "10%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 12.6,
      "explanation": "worker-2 unseen 13 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 696 m² reachable."
    },
    {
      "t": 12.1,
      "area": 69,
      "reach": 733.4,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 13.6,
      "explanation": "worker-2 unseen 14 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 733 m² reachable."
    },
    {
      "t": 13.0,
      "area": 69,
      "reach": 769.2,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 14.6,
      "explanation": "worker-2 unseen 15 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 769 m² reachable."
    },
    {
      "t": 13.9,
      "area": 69,
      "reach": 809,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 15.6,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 809 m² reachable."
    },
    {
      "t": 14.8,
      "area": 69,
      "reach": 840.3,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 16.6,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 840 m² reachable."
    },
    {
      "t": 15.8,
      "area": 69,
      "reach": 840.3,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 16.6,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 840 m² reachable."
    },
    {
      "t": 16.7,
      "area": 69,
      "reach": 862.3,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 17.4,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 862 m² reachable."
    },
    {
      "t": 18.0,
      "area": 69,
      "reach": 917.1,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 19.6,
      "explanation": "worker-2 unseen 20 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 917 m² reachable."
    },
    {
      "t": 19.0,
      "area": 69,
      "reach": 929.8,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 20.6,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 930 m² reachable."
    },
    {
      "t": 19.9,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 21.4,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 20.8,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 21.4,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 21.8,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 23.4,
      "explanation": "worker-2 unseen 23 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 22.7,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 23.4,
      "explanation": "worker-2 unseen 23 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 24.2,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 25.4,
      "explanation": "worker-2 unseen 25 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 25.1,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 26.4,
      "explanation": "worker-2 unseen 26 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 26.0,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 26.4,
      "explanation": "worker-2 unseen 26 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    }
  ]
}
```

## Moment 2b — Dead zone, occluded exit: PASS

**What it should demonstrate:** Same walk, but the north exit camera (node 1) is occluded for the whole episode, so it sends no healthy attestation. Its silence must NOT be counted as evidence: the region should leak into that camera's zone, and only that one, and the dashboard should say why.

**Action taken:** Waited for worker-2 to be back at the door, then pressed 'Dead zone - occluded camera 1' (the simulator occludes camera 1 and repeats the walk); sampled the page about every second.

**Verdict reason:** region leaked into camera 1's zone (up to 105 m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in 25 of 25 samples; same identity on re-emergence

### 2b1_before.jpg  (t = 175.4 s since launch)

Before the episode: cameras all healthy (green); worker-2 waits at the door.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "165.4",
 "convergence": "CONVERGED",
 "spread": "21",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.25",
 "claims_per_node": [
  "3701",
  "3680",
  "3696",
  "3700"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1133",
  "0 of 798",
  "1 of 866",
  "0 of 906"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(9.9, 23.5) via node 0 err 0.08",
  "P-002 worker-4 seen @(24.3, 23.5) via node 2 err 0.27",
  "P-003 worker-3 seen @(26.9, 13.6) via node 3 err 0.44",
  "P-004 worker-1 seen @(19.6, 1.6) via node 1 err 0.16",
  "P-014 worker-2 seen @(0.7, 14.4) via node 0 err 0.30"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 3697 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b2_hidden_0s.jpg  (t = 195.3 s since launch)

P-014 hidden 2.2 s: search area 13.4 m² vs 34.8 m² reachable without negative evidence (39%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "184.2",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.18",
 "claims_per_node": [
  "4132",
  "4136",
  "4132",
  "4134"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1305",
  "0 of 890",
  "1 of 959",
  "0 of 997"
 ],
 "regions": {
  "P-014": {
   "area_m2": 13.4,
   "reachable_m2": 34.8,
   "ratio": "39%",
   "in_blind_block_m2": 13.4,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 14.7) via node 0 err 0.08",
  "P-002 worker-4 seen @(15.1, 17.8) via node 2 err 0.44",
  "P-003 worker-3 seen @(30.2, 1.6) via node 3 err 0.15",
  "P-004 worker-1 seen @(25.1, 6.5) via node 1 err 0.06",
  "P-014 worker-2 unseen @(14.0, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4148 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b3_hidden_5s.jpg  (t = 200.4 s since launch)

P-014 hidden 7.4 s: search area 90.8 m² vs 346.4 m² reachable without negative evidence (26%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 33.3}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "189.4",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.41",
 "claims_per_node": [
  "4228",
  "4232",
  "4229",
  "4230"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1325",
  "0 of 910",
  "1 of 980",
  "0 of 1016"
 ],
 "regions": {
  "P-014": {
   "area_m2": 90.8,
   "reachable_m2": 346.4,
   "ratio": "26%",
   "in_blind_block_m2": 57.4,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 33.3
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 10.2) via node 0 err 0.50",
  "P-002 worker-4 seen @(20.0, 17.6) via node 2 err 0.44",
  "P-003 worker-3 seen @(32.4, 1.5) via node 3 err 0.04",
  "P-004 worker-1 seen @(25.1, 7.5) via node 1 err 0.67",
  "P-014 worker-2 unseen @(14.0, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4248 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b4_hidden_10s.jpg  (t = 205.8 s since launch)

P-014 hidden 12.4 s: search area 172.7 m² vs 689.4 m² reachable without negative evidence (25%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 103.7}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "194.4",
 "convergence": "CONVERGED",
 "spread": "18",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.36",
 "claims_per_node": [
  "4344",
  "4329",
  "4326",
  "4328"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1354",
  "0 of 937",
  "1 of 1010",
  "0 of 1046"
 ],
 "regions": {
  "P-014": {
   "area_m2": 172.7,
   "reachable_m2": 689.4,
   "ratio": "25%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 103.7
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 7.3) via node 0 err 0.53",
  "P-002 worker-4 seen @(24.9, 17.5) via node 2 err 0.42",
  "P-003 worker-3 seen @(33.2, 1.6) via node 3 err 0.13",
  "P-004 worker-1 seen @(19.7, 7.3) via node 1 err 0.35",
  "P-014 worker-2 unseen @(14.0, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4345 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b5_hidden_16s.jpg  (t = 212.1 s since launch)

P-014 hidden 18 s: search area 174 m² vs 885.9 m² reachable without negative evidence (20%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 105}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "200.0",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.54",
 "claims_per_node": [
  "4441",
  "4445",
  "4442",
  "4441"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1382",
  "0 of 964",
  "1 of 1036",
  "0 of 1074"
 ],
 "regions": {
  "P-014": {
   "area_m2": 174,
   "reachable_m2": 885.9,
   "ratio": "20%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 105
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.9, 1.5) via node 0 err 0.80",
  "P-002 worker-4 seen @(24.9, 23.1) via node 2 err 0.44",
  "P-003 worker-3 seen @(35.9, 1.5) via node 3 err 0.31",
  "P-004 worker-1 seen @(16.2, 7.5) via node 1 err 0.61",
  "P-014 worker-2 unseen @(14.0, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4465 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b6_hidden_22s.jpg  (t = 217.3 s since launch)

P-014 hidden 23 s: search area 174 m² vs 932.5 m² reachable without negative evidence (19%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 105}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "205.0",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.32",
 "claims_per_node": [
  "4540",
  "4544",
  "4541",
  "4540"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1407",
  "0 of 989",
  "1 of 1060",
  "0 of 1098"
 ],
 "regions": {
  "P-014": {
   "area_m2": 174,
   "reachable_m2": 932.5,
   "ratio": "19%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 105
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(6.0, 1.5) via node 0 err 0.50",
  "P-002 worker-4 seen @(20.4, 23.5) via node 2 err 0.59",
  "P-003 worker-3 seen @(39.0, 2.5) via node 3 err 0.07",
  "P-004 worker-1 seen @(14.9, 3.8) via node 1 err 0.10",
  "P-014 worker-2 unseen @(14.0, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4567 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b7_reemerged.jpg  (t = 221.6 s since launch)

worker-2 re-emerges from the block; identity now P-014 (before: P-014).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "209.0",
 "convergence": "CONVERGED",
 "spread": "5",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.64",
 "claims_per_node": [
  "4618",
  "4623",
  "4618",
  "4619"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1427",
  "0 of 1010",
  "1 of 1081",
  "0 of 1123"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(10.6, 1.4) via node 0 err 0.76",
  "P-002 worker-4 seen @(18.5, 23.5) via node 2 err 0.66",
  "P-003 worker-3 seen @(38.9, 5.5) via node 3 err 0.70",
  "P-004 worker-1 seen @(15.5, 1.6) via node 1 err 0.48",
  "P-014 worker-2 seen @(26.3, 12.0) via node 3 err 0.59"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4626 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

Measured values:

```json
{
  "seconds_click_to_region_on_page": 18.5,
  "identity_measured": "P-014",
  "identity_after_reemerging": "P-014",
  "same_identity_after": true,
  "n_samples": 25,
  "region_lifetime_s": 25.4,
  "first_area_m2": 13.4,
  "max_area_m2": 174,
  "final_area_m2": 174,
  "reach_at_end_m2": 932.5,
  "final_ratio_area_over_reach": 0.187,
  "max_healthy_zone_overlap_m2": 0,
  "max_area_outside_blind_block_m2": 105,
  "samples": [
    {
      "t": 0.0,
      "area": 13.4,
      "reach": 34.8,
      "ratio_pct": "39%",
      "blind": 13.4,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 2.2,
      "explanation": "worker-2 unseen 2 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. Search area 13 m² instead of 35 m² reachable."
    },
    {
      "t": 1.5,
      "area": 21.8,
      "reach": 68.9,
      "ratio_pct": "32%",
      "blind": 21.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 3.2,
      "explanation": "worker-2 unseen 3 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. Search area 22 m² instead of 69 m² reachable."
    },
    {
      "t": 2.4,
      "area": 32.2,
      "reach": 114.8,
      "ratio_pct": "28%",
      "blind": 30.9,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 1.3
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 4.2,
      "explanation": "worker-2 unseen 4 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 32 m² instead of 115 m² reachable."
    },
    {
      "t": 3.3,
      "area": 47.5,
      "reach": 184.1,
      "ratio_pct": "26%",
      "blind": 38.4,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 9.1
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 5.4,
      "explanation": "worker-2 unseen 5 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 48 m² instead of 184 m² reachable."
    },
    {
      "t": 4.2,
      "area": 67.6,
      "reach": 259.5,
      "ratio_pct": "26%",
      "blind": 48.4,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 19.2
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 6.4,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 68 m² instead of 260 m² reachable."
    },
    {
      "t": 5.2,
      "area": 90.8,
      "reach": 346.4,
      "ratio_pct": "26%",
      "blind": 57.4,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 33.3
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 7.4,
      "explanation": "worker-2 unseen 7 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 91 m² instead of 346 m² reachable."
    },
    {
      "t": 6.6,
      "area": 111.9,
      "reach": 423.5,
      "ratio_pct": "26%",
      "blind": 63.1,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 48.8
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 8.4,
      "explanation": "worker-2 unseen 8 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 112 m² instead of 424 m² reachable."
    },
    {
      "t": 7.6,
      "area": 137.6,
      "reach": 505.3,
      "ratio_pct": "27%",
      "blind": 68.9,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 68.8
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 9.4,
      "explanation": "worker-2 unseen 9 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 138 m² instead of 505 m² reachable."
    },
    {
      "t": 8.5,
      "area": 156.1,
      "reach": 582.8,
      "ratio_pct": "27%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 87.1
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 10.4,
      "explanation": "worker-2 unseen 10 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 156 m² instead of 583 m² reachable."
    },
    {
      "t": 9.4,
      "area": 167.4,
      "reach": 645.5,
      "ratio_pct": "26%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 98.4
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 11.4,
      "explanation": "worker-2 unseen 11 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 167 m² instead of 646 m² reachable."
    },
    {
      "t": 10.3,
      "area": 172.7,
      "reach": 689.4,
      "ratio_pct": "25%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 103.7
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 12.4,
      "explanation": "worker-2 unseen 12 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 173 m² instead of 689 m² reachable."
    },
    {
      "t": 12.0,
      "area": 174,
      "reach": 731.3,
      "ratio_pct": "24%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 13.4,
      "explanation": "worker-2 unseen 13 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 731 m² reachable."
    },
    {
      "t": 12.9,
      "area": 174,
      "reach": 776.7,
      "ratio_pct": "22%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 14.6,
      "explanation": "worker-2 unseen 15 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 777 m² reachable."
    },
    {
      "t": 13.8,
      "area": 174,
      "reach": 815.9,
      "ratio_pct": "21%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 15.6,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 816 m² reachable."
    },
    {
      "t": 14.8,
      "area": 174,
      "reach": 815.9,
      "ratio_pct": "21%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 15.6,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 816 m² reachable."
    },
    {
      "t": 15.7,
      "area": 174,
      "reach": 852.1,
      "ratio_pct": "20%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 16.8,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 852 m² reachable."
    },
    {
      "t": 16.6,
      "area": 174,
      "reach": 885.9,
      "ratio_pct": "20%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 18,
      "explanation": "worker-2 unseen 18 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 886 m² reachable."
    },
    {
      "t": 18.3,
      "area": 174,
      "reach": 926,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 20,
      "explanation": "worker-2 unseen 20 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 926 m² reachable."
    },
    {
      "t": 19.2,
      "area": 174,
      "reach": 931.9,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 21,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 20.2,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 22,
      "explanation": "worker-2 unseen 22 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 21.1,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 22,
      "explanation": "worker-2 unseen 22 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 22.0,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 23,
      "explanation": "worker-2 unseen 23 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 23.6,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 24,
      "explanation": "worker-2 unseen 24 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 24.5,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 25,
      "explanation": "worker-2 unseen 25 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 25.4,
      "area": 174,
      "reach": 932.5,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 26.2,
      "explanation": "worker-2 unseen 26 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    }
  ],
  "max_overlap_with_occluded_zone_1_m2": 105,
  "max_overlap_with_other_zones_m2": 0.0,
  "samples_where_page_explains_the_silence": 25,
  "explanation_at_peak_leak": "worker-2 unseen 13 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 731 m² reachable."
}
```

## Moment 3 — Partition and heal: PASS

**What it should demonstrate:** Cut nodes {2,3} from {0,1}; both sides keep working; on heal the replicas reconverge (equal claim counts, no gaps).

**Action taken:** Pressed 'Partition {2,3} from {0,1}', waited, pressed 'Heal', and timed how long until the convergence badge read CONVERGED.

**Verdict reason:** partition shown on all nodes, spread grew to 56.0, converged 4.2s after heal with gaps=0

### 3a_before_partition.jpg  (t = 222.1 s since launch)

Before: all nodes hold (almost) the same number of claims.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "210.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.61",
 "claims_per_node": [
  "4643",
  "4644",
  "4643",
  "4644"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1427",
  "0 of 1010",
  "1 of 1081",
  "0 of 1123"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 1.4) via node 0 err 0.65",
  "P-002 worker-4 seen @(17.2, 23.4) via node 2 err 0.45",
  "P-003 worker-3 seen @(38.8, 6.6) via node 3 err 0.70",
  "P-004 worker-1 seen @(16.4, 1.5) via node 1 err 0.63",
  "P-014 worker-2 seen @(27.2, 11.9) via node 3 err 0.61"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4650 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 3b_partition_during.jpg  (t = 225.3 s since launch)

Partition applied: every node card reports 'partitioned: yes'.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "213.2",
 "convergence": "PARTITIONED",
 "spread": "19",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.88",
 "claims_per_node": [
  "4717",
  "4709",
  "4726",
  "4728"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1449",
  "0 of 1032",
  "1 of 1103",
  "0 of 1164"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.1, 5.2) via node 0 err 0.87",
  "P-002 worker-4 seen @(15.0, 22.7) via node 2 err 0.82",
  "P-003 worker-3 seen @(39.1, 10.1) via node 3 err 0.94",
  "P-004 worker-1 seen @(19.5, 1.6) via node 1 err 0.92",
  "P-014 worker-2 seen @(30.0, 12.0) via node 3 err 0.87"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (26 observations never delivered)."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 3c_partition_later.jpg  (t = 238.0 s since launch)

12 s into the partition: the two sides' claim counts have drifted apart.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "225.4",
 "convergence": "PARTITIONED",
 "spread": "71",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.83",
 "claims_per_node": [
  "4831",
  "4833",
  "4900",
  "4902"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1509",
  "0 of 1088",
  "1 of 1162",
  "0 of 1282"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 19.8) via node 0 err 0.91",
  "P-002 worker-4 seen @(22.0, 17.5) via node 2 err 0.79",
  "P-003 worker-3 seen @(38.9, 21.3) via node 3 err 0.92",
  "P-004 worker-1 seen @(24.2, 7.6) via node 1 err 0.77",
  "P-014 worker-2 seen @(30.4, 17.5) via node 3 err 0.74"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "2",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (194 observations never delivered)."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 3d_after_heal.jpg  (t = 243.3 s since launch)

After heal: CONVERGED, spread 3, gaps 0 (4.2s after pressing Heal).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "230.0",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.64",
 "claims_per_node": [
  "5124",
  "5124",
  "5124",
  "5127"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1531",
  "0 of 1110",
  "1 of 1184",
  "0 of 1322"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(10.2, 23.4) via node 0 err 0.69",
  "P-002 worker-4 seen @(24.9, 19.1) via node 2 err 0.61",
  "P-003 worker-3 seen @(36.2, 23.5) via node 3 err 0.78",
  "P-004 worker-1 seen @(19.5, 7.5) via node 1 err 0.50",
  "P-014 worker-2 seen @(26.3, 17.4) via node 3 err 0.61"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4932 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

Measured values:

```json
{
  "before": {
    "claims": [
      4643.0,
      4644.0,
      4643.0,
      4644.0
    ],
    "spread": 1.0,
    "convergence": "CONVERGED"
  },
  "partition_state_shown_on_all_4_nodes": true,
  "spread_and_claims_during_partition": [
    [
      0.0,
      19.0,
      [
        4717.0,
        4709.0,
        4726.0,
        4728.0
      ]
    ],
    [
      1.5,
      21.0,
      [
        4726.0,
        4719.0,
        4739.0,
        4740.0
      ]
    ],
    [
      3.0,
      19.0,
      [
        4736.0,
        4738.0,
        4754.0,
        4755.0
      ]
    ],
    [
      4.6,
      29.0,
      [
        4755.0,
        4757.0,
        4783.0,
        4784.0
      ]
    ],
    [
      6.1,
      36.0,
      [
        4764.0,
        4766.0,
        4798.0,
        4800.0
      ]
    ],
    [
      7.6,
      45.0,
      [
        4784.0,
        4785.0,
        4828.0,
        4829.0
      ]
    ],
    [
      9.1,
      52.0,
      [
        4793.0,
        4795.0,
        4843.0,
        4845.0
      ]
    ],
    [
      10.6,
      56.0,
      [
        4803.0,
        4805.0,
        4858.0,
        4859.0
      ]
    ]
  ],
  "max_spread_during_partition": 56.0,
  "seconds_from_heal_to_converged": 4.2,
  "after_heal_claims": [
    5124.0,
    5124.0,
    5124.0,
    5127.0
  ],
  "after_heal_gaps": 0.0
}
```

## Moment 4 — Lying node: PASS

**What it should demonstrate:** A node fabricates sightings; peers reject implausible claims and its reputation, as seen by peers, drops; it recovers when it stops. Honest nodes must not lose reputation.

**Action taken:** Selected node 2, pressed 'Make node lie', sampled reputation and rejected-claim counters every ~2 s for up to 40 s, then pressed 'Stop lying' and sampled recovery for up to 60 s.

**Verdict reason:** liar's reputation < 0.7 after 13.3s (79.0 claims rejected), honest nodes stayed >= 1.0 (their rejected counters grew by [16.0, 0, 0] during the test), recovered > 0.9 8.3s after stopping

### 4a_before_lie.jpg  (t = 243.9 s since launch)

Before: reputation [1.0, 1.0, 1.0, 1.0], rejected [17.0, 0.0, 1.0, 0.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "230.0",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.64",
 "claims_per_node": [
  "5124",
  "5124",
  "5124",
  "5127"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "17 of 1531",
  "0 of 1110",
  "1 of 1184",
  "0 of 1322"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(10.2, 23.4) via node 0 err 0.69",
  "P-002 worker-4 seen @(24.9, 19.1) via node 2 err 0.61",
  "P-003 worker-3 seen @(36.2, 23.5) via node 3 err 0.78",
  "P-004 worker-1 seen @(19.5, 7.5) via node 1 err 0.50",
  "P-014 worker-2 seen @(26.3, 17.4) via node 3 err 0.61"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4932 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4b_lying_early.jpg  (t = 250.3 s since launch)

5.5s after 'Make node 2 lie': reputation [1.0, 1.0, 0.72, 1.0], rejected [17.0, 0.0, 19.0, 0.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "237.6",
 "convergence": "CONVERGED",
 "spread": "13",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.29",
 "claims_per_node": [
  "5307",
  "5320",
  "5313",
  "5314"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.72",
  "1.00"
 ],
 "rejected": [
  "17 of 1563",
  "0 of 1141",
  "19 of 1265",
  "0 of 1354"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(1.3, 23.7) via node 0 err 0.44",
  "P-003 worker-3 seen @(27.8, 23.5) via node 3 err 0.27",
  "P-004 worker-1 seen @(15.1, 6.8) via node 1 err 0.16"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "3",
  "truth": "5",
  "detail": "5 identities in the shared table; 5112 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4c_lying_dropped.jpg  (t = 266.9 s since launch)

Node 2's reputation has dropped: [1.0, 1.0, 0.78, 1.0], rejected [17.0, 0.0, 79.0, 0.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "254.2",
 "convergence": "CONVERGED",
 "spread": "13",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.11",
 "claims_per_node": [
  "5798",
  "5804",
  "5791",
  "5799"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.78",
  "1.00"
 ],
 "rejected": [
  "17 of 1691",
  "0 of 1220",
  "79 of 1448",
  "0 of 1437"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(0.9, 7.9) via node 0 err 0.12",
  "P-003 worker-3 seen @(27.0, 9.7) via node 3 err 0.21",
  "P-004 worker-1 seen @(23.6, 1.5) via node 1 err 0.05",
  "P-014 worker-2 seen @(4.4, 17.5) via node 0 err 0.08"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 5507 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4d_recovering.jpg  (t = 273.7 s since launch)

6.0s after 'Stop lying': reputation [0.74, 1.0, 0.89, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "259.2",
 "convergence": "CONVERGED",
 "spread": "9",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.30",
 "claims_per_node": [
  "5926",
  "5928",
  "5919",
  "5923"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "0.74",
  "1.00",
  "0.89",
  "1.00"
 ],
 "rejected": [
  "33 of 1751",
  "0 of 1249",
  "82 of 1480",
  "0 of 1466"
 ],
 "regions": {
  "P-014": {
   "area_m2": 29.4,
   "reachable_m2": 69.7,
   "ratio": "42%",
   "in_blind_block_m2": 29.4,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-002 worker-4 seen @(19.0, 17.4) via node 2 err 0.11",
  "P-003 worker-3 seen @(27.1, 4.0) via node 3 err 0.44",
  "P-004 worker-1 seen @(25.1, 5.2) via node 1 err 0.36",
  "P-014 worker-2 unseen @(14.2, 17.5) via node 2 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "3",
  "truth": "5",
  "detail": "5 identities in the shared table; 5632 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4e_after_stop.jpg  (t = 276.0 s since launch)

End of recovery window: reputation [0.94, 1.0, 0.95, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "262.2",
 "convergence": "CONVERGED",
 "spread": "9",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.44",
 "claims_per_node": [
  "5999",
  "6003",
  "5994",
  "5998"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "0.94",
  "1.00",
  "0.95",
  "1.00"
 ],
 "rejected": [
  "33 of 1783",
  "0 of 1265",
  "82 of 1496",
  "0 of 1482"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(4.2, 1.4) via node 0 err 0.63",
  "P-002 worker-4 seen @(20.7, 17.4) via node 2 err 0.17",
  "P-003 worker-3 seen @(27.9, 1.5) via node 3 err 0.58",
  "P-004 worker-1 seen @(24.4, 7.6) via node 1 err 0.66",
  "P-014 worker-2 seen @(1.1, 14.5) via node 0 err 0.15"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5707 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

Measured values:

```json
{
  "liar_node": 2,
  "reputation_before": [
    1.0,
    1.0,
    1.0,
    1.0
  ],
  "rejected_before": [
    17.0,
    0.0,
    1.0,
    0.0
  ],
  "samples_while_lying": [
    {
      "t": 0.0,
      "reputation": [
        1.0,
        1.0,
        1.0,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        1.0,
        0.0
      ]
    },
    {
      "t": 1.8,
      "reputation": [
        1.0,
        1.0,
        0.91,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        6.0,
        0.0
      ]
    },
    {
      "t": 3.7,
      "reputation": [
        1.0,
        1.0,
        0.78,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        14.0,
        0.0
      ]
    },
    {
      "t": 5.5,
      "reputation": [
        1.0,
        1.0,
        0.72,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        19.0,
        0.0
      ]
    },
    {
      "t": 7.8,
      "reputation": [
        1.0,
        1.0,
        0.71,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        28.0,
        0.0
      ]
    },
    {
      "t": 9.6,
      "reputation": [
        1.0,
        1.0,
        0.74,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        36.0,
        0.0
      ]
    },
    {
      "t": 11.4,
      "reputation": [
        1.0,
        1.0,
        0.7,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        45.0,
        0.0
      ]
    },
    {
      "t": 13.3,
      "reputation": [
        1.0,
        1.0,
        0.63,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        50.0,
        0.0
      ]
    },
    {
      "t": 15.1,
      "reputation": [
        1.0,
        1.0,
        0.54,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        57.0,
        0.0
      ]
    },
    {
      "t": 16.9,
      "reputation": [
        1.0,
        1.0,
        0.56,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        67.0,
        0.0
      ]
    },
    {
      "t": 18.7,
      "reputation": [
        1.0,
        1.0,
        0.61,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        70.0,
        0.0
      ]
    },
    {
      "t": 20.5,
      "reputation": [
        1.0,
        1.0,
        0.65,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        74.0,
        0.0
      ]
    },
    {
      "t": 22.4,
      "reputation": [
        1.0,
        1.0,
        0.78,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        79.0,
        0.0
      ]
    }
  ],
  "seconds_until_liar_reputation_below_0.7": 13.3,
  "liar_rejected_claims_at_end_of_lying": 79.0,
  "lowest_honest_reputation_while_lying": 1.0,
  "honest_nodes_rejected_claims_added_during_test": [
    16.0,
    0,
    0
  ],
  "recovery_samples": [
    {
      "t": 0.0,
      "reputation": [
        1.0,
        1.0,
        0.78,
        1.0
      ]
    },
    {
      "t": 2.0,
      "reputation": [
        0.86,
        1.0,
        0.77,
        1.0
      ]
    },
    {
      "t": 4.0,
      "reputation": [
        0.65,
        1.0,
        0.87,
        1.0
      ]
    },
    {
      "t": 6.0,
      "reputation": [
        0.74,
        1.0,
        0.89,
        1.0
      ]
    },
    {
      "t": 8.3,
      "reputation": [
        0.94,
        1.0,
        0.95,
        1.0
      ]
    }
  ],
  "seconds_until_liar_reputation_above_0.9_after_stop": 8.3
}
```

## Moment 5 — Query and refusal: PASS

**What it should demonstrate:** A text query (with a `safety` capability token) returns a structured answer separating confirmed from inferred and naming unreachable nodes; unanswerable queries are refused with a reason; a query about a worker in the blind block reports the candidate region, not a made-up position.

**Action taken:** Typed queries into the query box and read the rendered result from the DOM: a valid one, an unknown worker, a query during a partition, one under a `productivity` token, and (during moment 2a) one about the worker hidden in the uncovered block.

**Verdict reason:** valid query answered (confirmed/inferred/unreachable); unknown worker and productivity purpose refused with reasons; partition edge case: refused; blind-block query reported: Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothes

### 5e_query_worker_in_blind_block.jpg  (t = 60.6 s since launch)

Query 'where is worker 2' while worker-2 is hidden in the uncovered block: the answer reports the last confirmed position and the candidate region, not a made-up position.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "55.2",
 "convergence": "CONVERGED",
 "spread": "4",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "1114",
  "1117",
  "1113",
  "1115"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 328",
  "0 of 266",
  "0 of 271",
  "0 of 267"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 564.1,
   "ratio": "12%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 9.4) via node 0 err 0.25",
  "P-002 worker-4 seen @(24.8, 23.5) via node 2 err 0.22",
  "P-003 worker-3 seen @(30.3, 23.6) via node 3 err 0.60",
  "P-004 worker-1 seen @(25.1, 4.4) via node 1 err 0.31",
  "P-005 worker-2 unseen @(13.9, 14.5) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1137 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 5a_answer_worker3.jpg  (t = 276.7 s since launch)

Valid query 'where is worker 3' (purpose safety).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "263.2",
 "convergence": "CONVERGED",
 "spread": "9",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.47",
 "claims_per_node": [
  "6024",
  "6028",
  "6019",
  "6023"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "0.97",
  "1.00",
  "0.96",
  "1.00"
 ],
 "rejected": [
  "33 of 1792",
  "0 of 1270",
  "82 of 1501",
  "0 of 1487"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.1, 1.6) via node 0 err 0.97",
  "P-002 worker-4 seen @(20.5, 17.5) via node 2 err 0.07",
  "P-003 worker-3 seen @(29.0, 1.5) via node 3 err 0.61",
  "P-004 worker-1 seen @(23.4, 7.5) via node 1 err 0.61",
  "P-014 worker-2 seen @(1.1, 14.6) via node 0 err 0.09"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5736 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 5b_refusal_unknown.jpg  (t = 277.4 s since launch)

Unanswerable query 'where is worker 9': refused with its reason.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "263.2",
 "convergence": "CONVERGED",
 "spread": "9",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.47",
 "claims_per_node": [
  "6024",
  "6028",
  "6019",
  "6023"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "0.97",
  "1.00",
  "0.96",
  "1.00"
 ],
 "rejected": [
  "33 of 1792",
  "0 of 1270",
  "82 of 1501",
  "0 of 1487"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.1, 1.6) via node 0 err 0.97",
  "P-002 worker-4 seen @(20.5, 17.5) via node 2 err 0.07",
  "P-003 worker-3 seen @(29.0, 1.5) via node 3 err 0.61",
  "P-004 worker-1 seen @(23.4, 7.5) via node 1 err 0.61",
  "P-014 worker-2 seen @(1.1, 14.6) via node 0 err 0.09"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5736 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5c_query_while_partitioned.jpg  (t = 283.2 s since launch)

Edge case: 'where is worker 3' while {2,3} is cut off from the querying side.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "268.4",
 "convergence": "PARTITIONED",
 "spread": "17",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "6136",
  "6124",
  "6119",
  "6120"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "0.99",
  "1.00",
  "0.98",
  "1.00"
 ],
 "rejected": [
  "33 of 1841",
  "0 of 1295",
  "82 of 1526",
  "0 of 1512"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.6, 1.4) via node 0 err 0.72",
  "P-002 worker-4 seen @(24.0, 17.4) via node 2 err 0.06",
  "P-003 worker-3 seen @(34.6, 1.6) via node 3 err 0.93",
  "P-004 worker-1 seen @(19.8, 7.4) via node 1 err 0.77",
  "P-014 worker-2 seen @(1.1, 14.5) via node 0 err 0.05"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "3",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (252 observations never delivered)."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5d_refusal_productivity.jpg  (t = 286.3 s since launch)

Same query under a `productivity` token: refused (purpose limitation).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "272.0",
 "convergence": "CONVERGED",
 "spread": "9",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.40",
 "claims_per_node": [
  "6240",
  "6244",
  "6235",
  "6239"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.99",
  "1.00"
 ],
 "rejected": [
  "33 of 1872",
  "0 of 1311",
  "82 of 1541",
  "0 of 1528"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 5.2) via node 0 err 0.63",
  "P-002 worker-4 seen @(25.0, 19.2) via node 2 err 0.53",
  "P-003 worker-3 seen @(38.4, 1.4) via node 3 err 0.57",
  "P-004 worker-1 seen @(16.2, 7.5) via node 1 err 0.18",
  "P-014 worker-2 seen @(0.9, 14.5) via node 0 err 0.07"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5877 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

Measured values:

```json
{
  "valid_query": {
    "status": "answered",
    "verdict": "ANSWER",
    "reason": null,
    "confirmed": "Confirmed: last seen at (29.0, 1.5) m by node 3, 0s ago, confidence 0.89",
    "inferred": "Inferred: currently seen — no inference needed · last position is appearance-matched, not anchored — treat as a hypothesis",
    "unreachable": "Unreachable nodes: none · 4 of 4 nodes responded",
    "text": "Subject:          P-003\nLast confirmed:   (29.0, 1.5) m, t=263.2, confidence 0.89, node 3\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCompleteness:     4 of 4 nodes responded"
  },
  "unknown_worker": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: subject 'worker 9' was never enrolled — no claims found for this identity",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "subject 'worker 9' was never enrolled — no claims found for this identity"
  },
  "during_partition": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: 'P-003' was only observed by node 3, which is/are unreachable for the entire requested window — a partitioned wing, not an absence",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "'P-003' was only observed by node 3, which is/are unreachable for the entire requested window — a partitioned wing, not an absence"
  },
  "productivity_token": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])"
  },
  "worker_in_blind_block": {
    "status": "answered",
    "verdict": "ANSWER",
    "reason": null,
    "confirmed": "Confirmed: last seen at (14.0, 14.5) m by node 0, 11.2s ago, confidence 0.96",
    "inferred": "Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothesis",
    "unreachable": "Unreachable nodes: none · 4 of 4 nodes responded",
    "text": "Subject:          P-005\nLast confirmed:   (14.0, 14.5) m, t=45.0, confidence 0.96, node 0\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCandidate region: 69.0 m²\nCompleteness:     4 of 4 nodes responded"
  }
}
```

## Moment 6 — Robustness: PASS

**What it should demonstrate:** The dashboard survives a page reload; a node process that actually dies is shown as OFFLINE (and its camera zone as silent), and shown live again when restarted.

**Action taken:** Reloaded the browser page; hard-killed node 1's OS process (not via any dashboard control), watched its card and zone, restarted the process, and watched it return.

**Verdict reason:** reload recovered in 0.1s; killed node OFFLINE after 4.9s (its camera zone: silent); LIVE again 2.9s after restart; converged 4.8s after restart

### 6a_after_reload.jpg  (t = 286.6 s since launch)

Page reloaded mid-run; recovered in 0.1s with 4 nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "273.0",
 "convergence": "CONVERGED",
 "spread": "8",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.32",
 "claims_per_node": [
  "6264",
  "6268",
  "6260",
  "6263"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "33 of 1881",
  "0 of 1316",
  "82 of 1546",
  "0 of 1533"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 6.6) via node 0 err 0.49",
  "P-002 worker-4 seen @(24.9, 20.2) via node 2 err 0.50",
  "P-003 worker-3 seen @(39.0, 2.3) via node 3 err 0.33",
  "P-004 worker-1 seen @(16.1, 7.7) via node 1 err 0.17",
  "P-014 worker-2 seen @(1.1, 14.4) via node 0 err 0.09"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5901 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6b_node1_killed.jpg  (t = 291.8 s since launch)

Node 1's process killed; card reads OFFLINE after 4.9s, its camera zone is 'silent'; nodes live 3.

DOM values read at capture:

```json
{
 "nodes_live": "3",
 "sim_time_s": "278.0",
 "convergence": "CONVERGED",
 "spread": "8",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.19",
 "claims_per_node": [
  "6369",
  "6292",
  "6365",
  "6373"
 ],
 "live": [
  "LIVE",
  "OFFLINE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "33 of 1933",
  "0 of 1321",
  "82 of 1571",
  "0 of 1559"
 ],
 "regions": {
  "P-004": {
   "area_m2": 49.5,
   "reachable_m2": 92.3,
   "ratio": "54%",
   "in_blind_block_m2": 36.9,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 12.6
   },
   "silent": "1",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(11.9, 11.4) via node 0 err 0.10",
  "P-002 worker-4 seen @(23.2, 23.5) via node 2 err 0.37",
  "P-003 worker-3 seen @(39.1, 6.7) via node 3 err 0.20",
  "P-004 worker-1 unseen @(16.2, 7.5) via node 1 err –",
  "P-014 worker-2 seen @(1.0, 14.6) via node 0 err 0.10"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 6030 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6c_node1_restarted.jpg  (t = 295.0 s since launch)

Node 1 restarted; LIVE after 2.9s.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "281.0",
 "convergence": "CONVERGING",
 "spread": "139",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.21",
 "claims_per_node": [
  "6428",
  "6292",
  "6423",
  "6431"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "silent",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "33 of 1960",
  "0 of 1321",
  "82 of 1584",
  "0 of 1573"
 ],
 "regions": {
  "P-004": {
   "area_m2": 130.1,
   "reachable_m2": 273.3,
   "ratio": "48%",
   "in_blind_block_m2": 65.6,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 64.6
   },
   "silent": "1",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(12.0, 12.6) via node 0 err 0.03",
  "P-002 worker-4 seen @(22.2, 23.6) via node 2 err 0.19",
  "P-003 worker-3 seen @(39.1, 7.7) via node 3 err 0.49",
  "P-004 worker-1 unseen @(16.2, 7.5) via node 1 err –",
  "P-014 worker-2 seen @(0.9, 14.4) via node 0 err 0.12"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 6097 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6d_after_recovery.jpg  (t = 296.9 s since launch)

After recovery: CONVERGED, gaps 0, claims [6478.0, 6471.0, 6471.0, 6476.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "283.0",
 "convergence": "CONVERGED",
 "spread": "7",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.26",
 "claims_per_node": [
  "6478",
  "6471",
  "6471",
  "6476"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "33 of 1982",
  "0 of 1334",
  "82 of 1593",
  "0 of 1584"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 12.6) via node 0 err 0.27",
  "P-002 worker-4 seen @(20.4, 23.5) via node 2 err 0.45",
  "P-003 worker-3 seen @(39.1, 8.9) via node 3 err 0.13",
  "P-004 worker-1 seen @(15.0, 1.7) via node 1 err 0.24",
  "P-014 worker-2 seen @(1.2, 14.6) via node 0 err 0.19"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 6145 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "seconds_to_recover_after_reload": 0.1,
  "seconds_until_killed_node_shown_offline": 4.9,
  "killed_node_camera_zone_state": "silent",
  "other_nodes_stayed_live_while_node1_down": true,
  "seconds_until_restarted_node_live": 2.9,
  "seconds_from_restart_to_converged": 4.8
}
```

## Moment 7a — Conflict, resolvable: PASS

**What it should demonstrate:** Both halves of a split network face-anchor a look-alike as the SAME identity; one trajectory is physically impossible from the identity's last confirmed anchor. After the network heals the fork appears and is resolved by reachability, with the reason shown.

**Action taken:** Pressed 'Conflict - resolvable': the dashboard partitions the network, the simulator sends the two face-twins in (A anchored at the west gate twice, B at the east gate ~2 s after A's last anchor), then heals; the real resolver runs on the merged claims.

**Verdict reason:** no fork while partitioned (363 far-side claims held back); after healing the fork appeared and was resolved by reachability: Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s.

### 7a1_before.jpg  (t = 301.0 s since launch)

Clean start: healed network, no forks.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "286.8",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.39",
 "claims_per_node": [
  "6573",
  "6568",
  "6569",
  "6574"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 28",
  "0 of 14",
  "0 of 13",
  "0 of 14"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-3 seen @(39.1, 12.4) via node 3 err 0.58",
  "P-002 worker-2 seen @(0.9, 14.6) via node 0 err 0.14",
  "P-004 worker-0 seen @(12.0, 15.2) via node 0 err 0.05",
  "P-005 worker-1 seen @(18.6, 1.4) via node 1 err 0.63",
  "P-003 worker-4 seen @(16.5, 23.5) via node 2 err 0.53"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 6247 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 7a2_partitioned_twins.jpg  (t = 323.3 s since launch)

Partitioned: twin A on side {0,1}, twin B on side {2,3}; this variant's fork visible: 0 (conflict (resolvable): partitioned 20 s · 190 far-side claims held back).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "308.4",
 "convergence": "PARTITIONED",
 "spread": "198",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.12",
 "claims_per_node": [
  "6999",
  "6993",
  "6801",
  "6802"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 333",
  "0 of 120",
  "0 of 115",
  "0 of 117"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-3 seen @(29.0, 23.4) via node 3 err 0.10",
  "P-002 worker-2 seen @(1.0, 14.4) via node 0 err 0.10",
  "P-004 worker-0 seen @(2.0, 23.5) via node 0 err 0.05",
  "P-005 worker-1 seen @(19.0, 7.4) via node 1 err 0.22",
  "P-003 worker-4 seen @(24.9, 18.8) via node 2 err 0.11",
  "P-006 worker-5 seen @(6.8, 20.0) via node 0 err 0.15"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "4",
  "starling_now": "6",
  "truth": "6",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (469 observations never delivered)."
 },
 "conflict": "conflict (resolvable): partitioned 20 s · 190 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 7a3_after_heal_fork.jpg  (t = 340.7 s since launch)

After the network healed: 1 fork(s) shown, open=0.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "325.2",
 "convergence": "CONVERGING",
 "spread": "343",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "2.72",
 "claims_per_node": [
  "7331",
  "7326",
  "6988",
  "6989"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 589",
  "0 of 208",
  "0 of 201",
  "1 of 229"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-3 seen @(26.9, 13.9) via node 3 err 0.43",
  "P-002 worker-2 seen @(1.2, 14.4) via node 0 err 0.19",
  "P-004 worker-0 seen @(1.1, 5.1) via node 0 err 0.50",
  "P-005 worker-1 seen @(18.4, 1.6) via node 1 err 0.17",
  "P-003 worker-4 seen @(15.0, 22.9) via node 2 err 0.36",
  "P-006 worker-5 seen @(29.0, 12.4) via node 3 err 17.16",
  "P-007 worker-5 seen @(11.9, 10.1) via node 0 err 0.20"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "7",
  "truth": "7",
  "detail": "6 identities in the shared table; 7006 observations delivered."
 },
 "conflict": "conflict (resolvable): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 7a4_8s_later.jpg  (t = 348.9 s since launch)

8 s later: fork status unchanged (['RESOLVED_REACHABILITY']).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "333.0",
 "convergence": "CONVERGED",
 "spread": "12",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "3.72",
 "claims_per_node": [
  "7977",
  "7965",
  "7967",
  "7976"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "1 of 699",
  "0 of 246",
  "0 of 239",
  "1 of 302"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-3 seen @(27.1, 8.1) via node 3 err 0.38",
  "P-002 worker-2 seen @(0.8, 14.7) via node 0 err 0.26",
  "P-004 worker-0 seen @(6.7, 1.4) via node 0 err 0.59",
  "P-005 worker-1 seen @(21.8, 1.6) via node 1 err 0.20",
  "P-003 worker-4 seen @(15.8, 17.4) via node 2 err 0.11",
  "P-006 worker-5 seen @(29.1, 19.5) via node 3 err 24.08",
  "P-007 worker-5 seen @(10.2, 5.0) via node 0 err 0.39"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "7",
  "truth": "7",
  "detail": "6 identities in the shared table; 7279 observations delivered."
 },
 "conflict": "conflict (resolvable): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "other_forks_present": [],
  "variant": "resolvable",
  "forks_visible_while_partitioned": 0,
  "far_side_claims_held_back_max": 363,
  "seconds_to_fork_after_start": 39.5,
  "fork_status": "RESOLVED_REACHABILITY",
  "fork_status_8s_later": "RESOLVED_REACHABILITY",
  "fork_explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s.",
  "fork_branch_rows": [
    [
      "0",
      "9.82, 12.54",
      "156",
      "0",
      "KEPT"
    ],
    [
      "1",
      "33.35, 12.59",
      "1",
      "3",
      "rejected"
    ]
  ],
  "fork_markers_on_map": [
    {
      "id": "fork-branch-P_100_320s-0",
      "x": 9.82,
      "y": 12.54,
      "text": "kept A"
    },
    {
      "id": "fork-branch-P_100_320s-1",
      "x": 33.35,
      "y": 12.59,
      "text": "rejected B"
    }
  ],
  "forks_open_counter": "0",
  "event_log_head": [
    "336.6s FORK RESOLVED on P-006 by reachability: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s",
    "336.6s FORK OPENED on P-006 (face id P-100): 2 claim chains bind it to incompatible positions (9.82, 12.54) vs (33.35, 12.59)",
    "336.4s CONFLICT (resolvable): network healed; the two sides now merge their claims",
    "336.4s HEAL all links (ok={0: True, 1: True, 2: True, 3: True})",
    "333.6s new identity P-007",
    "299.8s new identity P-006",
    "298.2s SCRIPT conflict_resolvable: started",
    "298.2s PARTITION [0, 1] | [2, 3] (ok={0: True, 1: True, 2: True, 3: True})"
  ]
}
```

## Moment 7b — Conflict, ambiguous: PASS

**What it should demonstrate:** Same set-up, but both trajectories are physically possible. After the network heals the fork appears and STAYS OPEN, shown as an ambiguity for a human with both candidate positions drawn on the map; the system never picks a winner.

**Action taken:** Pressed 'Conflict - ambiguous' (twin A anchored at the west gate once, twin B anchored as the same identity at the east gate 25 s later), waited for the heal and the fork, and checked it 8 s later.

**Verdict reason:** no fork while partitioned; after healing one fork appeared and stayed OPEN 8 s later; 2 branch markers drawn at [(5.02, 21.49), (33.37, 12.58)]; explanation: Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is

### 7b1_before.jpg  (t = 353.0 s since launch)

Clean start: healed network, no forks.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "337.0",
 "convergence": "CONVERGED",
 "spread": "18",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "8114",
  "8099",
  "8104",
  "8117"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 43",
  "0 of 15",
  "0 of 15",
  "0 of 24"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.5, 1.4) via node 0 err 0.47",
  "P-005 worker-1 seen @(23.9, 1.6) via node 1 err 0.51",
  "P-002 worker-4 seen @(18.0, 17.5) via node 2 err 0.42",
  "P-003 worker-2 seen @(1.0, 14.6) via node 0 err 0.06",
  "P-004 worker-5 seen @(6.5, 5.1) via node 0 err 0.26",
  "P-006 – seen @(27.1, 3.7) via node 3 err –",
  "P-007 – seen @(32.2, 19.9) via node 3 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "7",
  "truth": "7",
  "detail": "6 identities in the shared table; 7416 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 7b2_partitioned_twins.jpg  (t = 375.3 s since launch)

Partitioned: twin A on side {0,1}, twin B on side {2,3}; this variant's fork visible: 0 (conflict (ambiguous): partitioned 20 s · 282 far-side claims held back).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "358.4",
 "convergence": "PARTITIONED",
 "spread": "192",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.20",
 "claims_per_node": [
  "8642",
  "8634",
  "8450",
  "8451"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "2 of 445",
  "0 of 116",
  "0 of 115",
  "25 of 230"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 21.9) via node 0 err 0.27",
  "P-005 worker-1 seen @(17.6, 7.4) via node 1 err 0.23",
  "P-002 worker-4 seen @(21.9, 23.5) via node 2 err 0.11",
  "P-003 worker-2 seen @(1.0, 14.6) via node 0 err 0.07",
  "P-004 worker-5 seen @(5.5, 22.0) via node 0 err 0.29",
  "P-006 worker-3 seen @(39.0, 10.8) via node 3 err 0.18",
  "P-007 worker-6 seen @(38.0, 6.7) via node 3 err 0.25",
  "P-008 worker-7 seen @(9.1, 22.0) via node 0 err 0.24"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "5",
  "starling_now": "8",
  "truth": "8",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (946 observations never delivered)."
 },
 "conflict": "conflict (ambiguous): partitioned 20 s · 282 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 7b3_after_heal_fork.jpg  (t = 394.1 s since launch)

After the network healed: 1 fork(s) shown, open=1.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "375.6",
 "convergence": "CONVERGING",
 "spread": "467",
 "gaps": "1666",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "4.08",
 "claims_per_node": [
  "9029",
  "9249",
  "8782",
  "8790"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "2 of 745",
  "0 of 210",
  "0 of 209",
  "55 of 481"
 ],
 "regions": {
  "P-004": {
   "area_m2": 69,
   "reachable_m2": 438.6,
   "ratio": "16%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 19.4) via node 0 err 1.32",
  "P-005 worker-1 seen @(21.9, 1.5) via node 1 err 1.25",
  "P-002 worker-4 seen @(15.0, 19.5) via node 2 err 0.38",
  "P-003 worker-2 seen @(0.9, 14.3) via node 0 err 0.18",
  "P-004 worker-5 unseen @(10.9, 22.0) via node 0 err –",
  "P-006 worker-3 seen @(32.9, 23.5) via node 3 err 1.35",
  "P-007 worker-6 seen @(29.8, 9.0) via node 3 err 1.15",
  "P-008 worker-7 seen @(28.9, 19.0) via node 3 err 25.75",
  "P-034 worker-7 seen @(5.0, 10.7) via node 0 err 1.26"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "7",
  "starling_now": "8",
  "truth": "8",
  "detail": "7 identities in the shared table; 8339 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

### 7b4_8s_later.jpg  (t = 402.7 s since launch)

8 s later: fork status unchanged (['OPEN']).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "383.2",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "4.74",
 "claims_per_node": [
  "9941",
  "9924",
  "9930",
  "9941"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "0.82"
 ],
 "rejected": [
  "2 of 857",
  "0 of 246",
  "0 of 247",
  "62 of 591"
 ],
 "regions": {
  "P-004": {
   "area_m2": 69,
   "reachable_m2": 839.8,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 12.6) via node 0 err 1.74",
  "P-005 worker-1 seen @(25.0, 3.7) via node 1 err 0.40",
  "P-002 worker-4 seen @(18.2, 17.5) via node 2 err 1.43",
  "P-003 worker-2 seen @(0.9, 14.5) via node 0 err 0.08",
  "P-004 worker-5 unseen @(10.9, 22.0) via node 0 err –",
  "P-006 worker-3 seen @(27.8, 23.7) via node 3 err 0.27",
  "P-007 worker-6 seen @(36.1, 8.9) via node 3 err 1.68",
  "P-008 worker-7 forked @(34.6, 20.1) via node 3 err 31.10",
  "P-034 worker-7 seen @(6.2, 5.0) via node 0 err 1.20"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "7",
  "starling_now": "7",
  "truth": "8",
  "detail": "7 identities in the shared table; 8627 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "other_forks_present": [],
  "variant": "ambiguous",
  "forks_visible_while_partitioned": 0,
  "far_side_claims_held_back_max": 538,
  "seconds_to_fork_after_start": 40.4,
  "fork_status": "OPEN",
  "fork_status_8s_later": "OPEN",
  "fork_explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58).",
  "fork_branch_rows": [
    [
      "0",
      "5.02, 21.49",
      "120",
      "0",
      "possible"
    ],
    [
      "1",
      "33.37, 12.58",
      "1",
      "3",
      "possible"
    ]
  ],
  "fork_markers_on_map": [
    {
      "id": "fork-branch-P_101_363s-0",
      "x": 5.02,
      "y": 21.49,
      "text": "? A"
    },
    {
      "id": "fork-branch-P_101_363s-1",
      "x": 33.37,
      "y": 12.58,
      "text": "? B"
    }
  ],
  "forks_open_counter": "1",
  "event_log_head": [
    "390.3s FORK OPENED on P-008 (face id P-101): 2 claim chains bind it to incompatible positions (5.02, 21.49) vs (33.37, 12.58)",
    "390.3s worker-6 RE-SEEN as the same identity after 6.2s (region peaked/ended at 34.5 m²)",
    "388.6s CONFLICT (ambiguous): network healed; the two sides now merge their claims",
    "388.6s HEAL all links (ok={0: True, 1: True, 2: True, 3: True})",
    "385.7s worker-6 went UNSEEN at (29.81, 4.96) — candidate region opened",
    "379.5s worker-5 went UNSEEN at (10.95, 22.02) — candidate region opened",
    "378.5s new identity P-034",
    "351.9s new identity P-008"
  ]
}
```

## Moment 8 — Centralized comparison: PASS

**What it should demonstrate:** A centralized single-server system (the original project's matcher; NOT Starling) runs beside Starling on the same input. Under a partition it must lose the cut-off cameras' workers while Starling keeps tracking all of them; with the server killed it must be DOWN while Starling is unaffected; restarted, it recovers (from empty state).

**Action taken:** Pressed Partition, read both panels, healed; pressed 'Kill central server' (the server process exits), read both panels and Starling's claim counter over 8 s; pressed 'Restart central server'.

**Verdict reason:** partition: centralized tracks 3 (PARTIAL) vs Starling 5 of 5; killed: centralized DOWN/0 while Starling kept 5 of 5 and 227 new claims in 8 s; restarted: HEALTHY

### 8a_healthy.jpg  (t = 448.9 s since launch)

Healthy: centralized tracks 6, Starling tracks 5, actually present 5.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "427.8",
 "convergence": "CONVERGED",
 "spread": "11",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.41",
 "claims_per_node": [
  "11380",
  "11369",
  "11375",
  "11380"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "0.72"
 ],
 "rejected": [
  "2 of 1433",
  "0 of 457",
  "0 of 458",
  "124 of 1023"
 ],
 "regions": {
  "P-064": {
   "area_m2": 8.1,
   "reachable_m2": 11.1,
   "ratio": "73%",
   "in_blind_block_m2": 8.1,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(12.0, 19.8) via node 0 err 0.69",
  "P-005 worker-1 seen @(24.5, 1.6) via node 1 err 0.46",
  "P-002 worker-4 seen @(22.4, 17.4) via node 2 err 0.09",
  "P-003 worker-2 seen @(1.1, 14.5) via node 0 err 0.13",
  "P-006 worker-3 seen @(32.4, 1.6) via node 3 err 0.68",
  "P-008 worker-7 forked @(5.1, 21.8) via node 0 err –",
  "P-064 worker-8 unseen @(36.5, 9.0) via node 3 err –"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "5",
  "truth": "5",
  "detail": "7 identities in the shared table; 10071 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

### 8b_partition_central_loses_side.jpg  (t = 457.7 s since launch)

Partitioned: centralized PARTIAL tracks 3; Starling tracks 5 of 5 present. Cameras 2, 3 cannot reach the server: their workers are lost (1330 observations never delivered).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "437.2",
 "convergence": "PARTITIONED",
 "spread": "47",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "1",
 "mean_error_m": "0.52",
 "claims_per_node": [
  "11534",
  "11545",
  "11498",
  "11499"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "0.83"
 ],
 "rejected": [
  "2 of 1523",
  "0 of 502",
  "0 of 501",
  "124 of 1068"
 ],
 "regions": {
  "P-064": {
   "area_m2": 69,
   "reachable_m2": 399.8,
   "ratio": "17%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(4.5, 23.5) via node 0 err 0.76",
  "P-005 worker-1 seen @(24.3, 7.6) via node 1 err 0.51",
  "P-002 worker-4 seen @(25.0, 21.5) via node 2 err 0.60",
  "P-003 worker-2 seen @(1.0, 14.5) via node 0 err 0.02",
  "P-006 worker-3 seen @(39.1, 5.2) via node 3 err 0.71",
  "P-008 worker-7 forked @(5.1, 21.8) via node 0 err –",
  "P-064 worker-8 unseen @(36.5, 9.0) via node 3 err –"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "3",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (1330 observations never delivered)."
 },
 "conflict": "conflict (ambiguous): healed 39 s · 78 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 8c_central_killed.jpg  (t = 464.9 s since launch)

Central server killed: status DOWN, tracks 0; Starling tracks 5 of 5 present, 4 nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "444.6",
 "convergence": "CONVERGED",
 "spread": "25",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.12",
 "claims_per_node": [
  "11766",
  "11786",
  "11761",
  "11765"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "0.99"
 ],
 "rejected": [
  "2 of 1592",
  "0 of 537",
  "0 of 537",
  "124 of 1102"
 ],
 "regions": {
  "P-064": {
   "area_m2": 69,
   "reachable_m2": 676.3,
   "ratio": "10%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(0.9, 19.1) via node 0 err 0.08",
  "P-005 worker-1 seen @(16.9, 7.5) via node 1 err 0.06",
  "P-002 worker-4 seen @(21.2, 23.5) via node 2 err 0.24",
  "P-003 worker-2 seen @(1.0, 14.5) via node 0 err 0.05",
  "P-006 worker-3 seen @(39.0, 10.6) via node 3 err 0.17",
  "P-008 worker-7 forked @(5.1, 21.8) via node 0 err –",
  "P-064 worker-8 unseen @(36.5, 9.0) via node 3 err –"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "DOWN",
  "tracked_now": "0",
  "starling_now": "5",
  "truth": "5",
  "detail": "The central server process is not running: nothing is tracked."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

### 8d_starling_unaffected.jpg  (t = 471.1 s since launch)

6 s later, central still DOWN; Starling claims 3901.0 (was 3674.0), convergence CONVERGED.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "449.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.50",
 "claims_per_node": [
  "11914",
  "11908",
  "11909",
  "11913"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "2 of 1645",
  "0 of 564",
  "0 of 564",
  "124 of 1128"
 ],
 "regions": {
  "P-064": {
   "area_m2": 69,
   "reachable_m2": 857.8,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 15.0) via node 0 err 0.80",
  "P-005 worker-1 seen @(15.0, 4.5) via node 1 err 0.64",
  "P-002 worker-4 seen @(16.2, 23.5) via node 2 err 0.23",
  "P-003 worker-2 seen @(1.1, 14.6) via node 0 err 0.15",
  "P-006 worker-3 seen @(39.1, 16.0) via node 3 err 0.66",
  "P-008 worker-7 forked @(5.1, 21.8) via node 0 err –",
  "P-064 worker-8 unseen @(36.5, 9.0) via node 3 err –"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "DOWN",
  "tracked_now": "0",
  "starling_now": "5",
  "truth": "5",
  "detail": "The central server process is not running: nothing is tracked."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

### 8e_central_restarted.jpg  (t = 473.8 s since launch)

Central server restarted: HEALTHY, tracks 5.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "452.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.41",
 "claims_per_node": [
  "11989",
  "11983",
  "11984",
  "11988"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "camera_zone_coverage": [
  "healthy",
  "healthy",
  "healthy",
  "healthy"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "2 of 1665",
  "0 of 574",
  "0 of 574",
  "124 of 1138"
 ],
 "regions": {
  "P-064": {
   "area_m2": 69,
   "reachable_m2": 920.1,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(0.9, 11.3) via node 0 err 0.67",
  "P-005 worker-1 seen @(15.0, 1.5) via node 1 err 0.64",
  "P-002 worker-4 seen @(15.1, 23.2) via node 2 err 0.54",
  "P-003 worker-2 seen @(1.1, 14.4) via node 0 err 0.08",
  "P-006 worker-3 seen @(38.9, 19.3) via node 3 err 0.10",
  "P-008 worker-7 forked @(5.1, 21.8) via node 0 err –",
  "P-064 worker-8 unseen @(36.5, 9.0) via node 3 err –"
 ],
 "forks": [
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (5.02, 21.49) OR branch 1 at (33.37, 12.58)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 10 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 39 s",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "healthy": {
    "status": "HEALTHY",
    "tracked_now": "6",
    "starling_now": "5",
    "truth": "5",
    "detail": "7 identities in the shared table; 10071 observations delivered."
  },
  "partitioned": {
    "status": "PARTIAL",
    "tracked_now": "3",
    "starling_now": "5",
    "truth": "5",
    "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (1330 observations never delivered)."
  },
  "killed": {
    "status": "DOWN",
    "tracked_now": "0",
    "starling_now": "5",
    "truth": "5",
    "detail": "The central server process is not running: nothing is tracked."
  },
  "restarted": {
    "status": "HEALTHY",
    "tracked_now": "5",
    "starling_now": "5",
    "truth": "5",
    "detail": "5 identities in the shared table; 10 observations delivered."
  },
  "starling_claims_before_kill": 3674.0,
  "starling_claims_6s_after_kill": 3901.0,
  "nodes_live_after_kill": "4",
  "convergence_after_kill": "CONVERGED"
}
```

## First-run findings

Verdicts of this session's first, unmodified run of the review:

| # | Moment | Verdict | Reason |
|---|---|---|---|
| 0 | Startup | PASS | all 4 nodes live and central server healthy 5.3s after launch; all camera zones healthy; demo-script panel lists 9 steps |
| 1 | Normal walk | PASS | 4 identities tracked, labels unchanged for 25 s, max displacement 21.3 m, mean error 0.35 m vs ground truth |
| 2a | Dead zone, healthy exits | PASS | region confined to the block for 24.9 s (0 m² in healthy zones, at most 0.5 m² outside the block), final 69 m² vs 932.5 m² reachable (ratio 0.074), same identity P-005 on re-emergence |
| 2b | Dead zone, occluded exit | PASS | region leaked into camera 1's zone (up to 105 m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in 30 of 30 samples; same identity on re-emergence |
| 3 | Partition and heal | PASS | partition shown on all nodes, spread grew to 51.0, converged 1.1s after heal with gaps=0 |
| 4 | Lying node | PASS | liar's reputation < 0.7 after 12.8s (72.0 claims rejected), honest nodes stayed >= 1.0 (their rejected counters grew by [7.0, 0, 0.0] during the test), recovered > 0.9 8.1s after stopping |
| 5 | Query and refusal | PASS | valid query answered (confirmed/inferred/unreachable); unknown worker and productivity purpose refused with reasons; partition edge case: refused; blind-block query reported: Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothes |
| 6 | Robustness | PASS | reload recovered in 0.1s; killed node OFFLINE after 4.9s (its camera zone: silent); LIVE again 4.1s after restart; converged 5.8s after restart |
| 7a | Conflict, resolvable | PASS | no fork while partitioned (389 far-side claims held back); after healing the fork appeared and was resolved by reachability: Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s. |
| 7b | Conflict, ambiguous | FAIL | no fork appeared after healing; no fork line in the event log |
| 8 | Centralized comparison | PARTIAL | under partition centralized tracked 3 vs Starling 5 of 5 present |

This session's first full run of the new review (commit `4036a2b`, before any change made in response to it) gave 9 PASS, 1 FAIL and 1 PARTIAL. Everything that failed or looked wrong on it, and what was changed:

1. **Moment 7b (ambiguous conflict) FAILED: no fork appeared after healing (real defect in my scenario design, not in the resolver).** The ambiguous scenario reused twin workers 5 and 6 from the resolvable scenario that had run two minutes earlier. When twin A walked in again, the OLD identity left behind by the previous twin A (same appearance, still reachable) competed with the new face-anchored identity for A's claims; the resolver, correctly, refused to guess between them and left A's claims unassigned. The anchored identity's "live tip" therefore went stale, and twin B's anchor 25 s later looked like a plain continuation of that stale tip, so no fork formed. Reproduced offline (simulator + resolver, no network): the same scenario alone gives an OPEN fork, but after the resolvable scenario it gives none. **Fix:** the ambiguous scenario now has its own twin pair (workers 7 and 8, own appearance, face id P-101), and the dashboard refuses to start the same conflict variant again within 100 s (its twins are still walking). Both orders now produce the expected fork.
2. **Moment 8 (centralized comparison) PARTIAL: harness criterion wrong.** The check waited for the centralized system to track at most 2 workers under a partition, but the stage actor (worker-2, waiting at the door in the server's own zone) is a third worker on the server's side, so it correctly tracked 3 of 5 (Starling 5 of 5). The measured behaviour was right; my threshold was not. **Fix:** the criterion is now "centralized tracks fewer workers than Starling while Starling tracks every worker present".
3. **Not a failure, but worth reading: moment 4 took 12.8 s to push the liar below 0.7 (about 4 s when measured in isolation).** In the review, worker-2 was walking a circuit through node 2's zone, so node 2 was also producing many honest claims, which dilutes the fabricated share of its stream (the reputation is an EWMA of pass/fail). Not a regression; the dashboard number is the median of the three peers' opinions. In the same run honest nodes' *rejected* counters grew by [7, 0, 0] during the test: these are the first claims of newly appearing tracks (a person entering, scripted actors spawning), which are graded against the node's established tracks and can fail once each (documented residual, Part D of this session).
4. **Found and fixed during development BEFORE this first run (so not visible in the first-run table, listed for completeness):** the `delay_s` key of a scenario step was read at the wrong level, so twin B spawned at the same instant as twin A and every 5 Hz face-anchor produced its own fork; the simulated gate re-anchored every tick (now one recognition event per pass, `cooldown_s`); a leftover twin from a previous run produced early forks (scripts now deactivate it first); the dead-zone region vanished after 12 s because of the old "hide stale fragments" rule (now 40 s); a phantom region appeared for a forked identity (identities with an open fork get none); honest nodes were being falsely rejected (uncorroborated/stale claims after a partition heals, corroborators that were other people, new tracks inside a catch-up burst). See `STATUS.md` Decisions.
5. **After fix #1 above, re-running still occasionally mis-reported moment 7b (a second, different bug — found AFTER this first run, while verifying fix #1, not itself part of the first-run table).** Giving the ambiguous scenario its own twin pair stopped the WRONG fork from forming, but a re-run of the full 11-moment sequence still showed 7b's fork as `RESOLVED_REACHABILITY` (the resolvable variant's own result) instead of `OPEN`. Cause: the resolvable scenario's twin worker still takes ~80 s to finish its route, longer than the demo's own `conflict_heal_after_s` (38 s) + the review's 8 s settle wait, so it is still walking — and briefly still producing claims — when the ambiguous scenario starts. The dashboard's fork panel remembers a fork for 150 s after it stops being freshly reported (`fork_memory_s`, so the panel does not flicker away while the resolver's 45 s window slides past it), and the review script picked `forks[0]` (list position) rather than the fork the variant it had just run actually created — so it sometimes grabbed the leftover resolvable-scenario fork instead of the new ambiguous one. This was a bug in the REVIEW SCRIPT (`scripts/review_demo.py`), not in the demo: the dashboard was always showing correct, real forks; the review was reading the wrong one. **Fix:** the review now matches a fork by the variant's own face identity (P-100 for resolvable, P-101 for ambiguous) instead of list position. Verified live, repeatedly, that running resolvable then ambiguous back-to-back now always shows the ambiguous variant's own OPEN fork regardless of what the resolvable variant's (still valid, still real) fork is doing at the same time.


## Browser console errors

None (no console errors/warnings, page errors or failed requests recorded).

## Process errors and exit status

No Python tracebacks, no crash lines and no `level: error` log records in any process log.

Warning-level events (counts): `{"node-0": {"PARTITION_HEALED": 7, "PARTITION_DETECTED": 6}, "node-1": {"PARTITION_HEALED": 7, "PARTITION_DETECTED": 5}, "node-2": {"PARTITION_HEALED": 7, "PARTITION_DETECTED": 6}, "node-3": {"PARTITION_HEALED": 6, "PARTITION_DETECTED": 5}}`

Claims rejected by nodes' plausibility check (logged per node; includes the deliberate liar and scripted actors): `{"dashboard": 243, "node-0": 152, "node-1": 5114, "node-2": 155, "node-3": 111}`

| process | exit code | note |
|---|---|---|
| dashboard | 1 | still running at shutdown; stopped by the launcher |
| central | 0 | had already exited before shutdown |
| node-0 | 1 | still running at shutdown; stopped by the launcher |
| node-1 | 1 | still running at shutdown; stopped by the launcher |
| node-2 | 1 | still running at shutdown; stopped by the launcher |
| node-3 | 1 | still running at shutdown; stopped by the launcher |
| simulator | 1 | still running at shutdown; stopped by the launcher |

On Windows the launcher stops a process with `TerminateProcess`, so a nonzero exit code for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted in moment 6; the central server was killed and restarted in moment 8.

## Timings

```json
{
  "startup_s": 6.6,
  "heal_convergence_s": 4.2,
  "reputation_drop_s": 13.3,
  "reputation_recovery_s": 8.3,
  "dead_zone_healthy_lifetime_s": 26.0,
  "dead_zone_healthy_ratio": 0.074,
  "conflict_seconds_to_fork": {
    "resolvable": 39.5,
    "ambiguous": 40.4
  }
}
```

## Environment

```json
{
  "os": "Windows 11 (10.0.26200)",
  "python": "3.12.1",
  "chromium": "153.0.8010.12",
  "commit": "61869f4",
  "working_tree_dirty_outside_review_dir": true,
  "packages": {
    "fastapi": "0.115.0",
    "uvicorn": "0.30.0",
    "playwright": "1.63.0",
    "pyzmq": "27.2.0",
    "numpy": "2.5.3",
    "scipy": "1.17.0",
    "protobuf": "5.29.6",
    "pynacl": "1.6.2",
    "pydantic": "2.13.5"
  }
}
```

## Known limitations and what is simulated

- Perception is SIMULATED. There are no cameras, video or detector: a simulator moves virtual workers on a 2D floor plan and hands each node the noisy detections (position noise 0.08 m, embedding noise, 3 % missed detections) its own camera zone would produce. Identity embeddings are synthetic 64-d vectors, so appearance matching is far easier than with real re-ID features. The 'ground truth' markers are the simulator's own state.
- The face-recognition gates (the source of forks) and the 'look-alike' twins are SIMULATED and SCRIPTED: two people share one face identity by construction. The resolver that turns that into a fork, resolves it by reachability or leaves it open is the project's real code, unmodified. The fork view is what node 0's side can see (far-side claims are held back while partitioned, released on heal); the map itself remains the global observer view.
- The dead-zone episodes are scripted: one actor (worker-2) walks a fixed path through the uncovered block, and 'occluded' means the simulator stops that camera from sending healthy coverage attestations (a scripted occlusion; the camera's detections are not suppressed). The dashboard learns everything else from gossiped claims and attestations; the simulator's ground truth is used only to LABEL a silent camera as 'occluded' and to draw the faint truth rings.
- Candidate regions grow at the conservative walking-speed bound (1.6 m/s) and are clipped only by (a) healthy attested zones and (b) obstacles. A camera zone with no healthy attestation (occluded, offline, partitioned away) is never subtracted, by design (silence is not evidence). The 'reachable without negative evidence' area is the same dilation with that clipping switched off.
- The network PARTITION is application-level: each node ignores inbound gossip from the other group (`POST /partition`), the centralized server is told which cameras are cut. It is not packet loss/latency (netem) and the sending side is not gated. The dashboard's own observer is deliberately not partitioned.
- THE CENTRALIZED SYSTEM IS A COMPARISON, NOT PART OF STARLING. It reuses the original project's identity matcher (`IdentityStore.match_or_create`, appearance-only cosine matching against one shared table) inside a new single-server process fed by the same simulated cameras; it has no geometry, so it also silently merges look-alikes. It is deliberately naive, and partitions/failure are simulated the same application-level way. It does not run the original video pipeline.
- The lying node is the project's own `AttackInjector` (fabricated claims at random free positions, 90 % intensity), not an adaptive adversary. Reputation is an EWMA over plausibility checks; roughly 0.5-0.6 is the floor with three reporting peers (median). The dashboard's 'rejected' counter is the DASHBOARD's own plausibility pass over what it overheard.
- The claim-count 'converged' badge tolerates a small in-flight spread (30 claims, about a second of production) plus gaps == 0. Byte-identical claim sets are asserted in unit tests, not readable from the page. The resolver runs over a sliding 45 s window; identity labels (P-001...) are kept stable across windows by claim overlap; fork results are remembered for 150 s of display time.
- '≈ worker-N' next to an identity and the translation of 'where is worker 2' use the nearest ground-truth worker as a display-only label; the network never sees worker names.
- Single machine, all processes on localhost; timings are for one Windows laptop and vary run to run. Nothing here exercises real cameras, the video/YOLO path or `apps/baseline.py` itself.
- Screenshots are JPEGs of the real running page (full page height, 1440 px wide); no image was edited. Verdicts are computed from the DOM values recorded at capture time by explicit criteria in `scripts/review_demo.py`.

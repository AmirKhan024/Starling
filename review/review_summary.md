# Starling demo — automated review summary (session 3)

Generated 2026-09-23 21:03:14 by `scripts/review_demo.py` (commit `cab1f4d`). Same content as `review.html`, without images (file names refer to `review/screenshots/`). The centralized system is a comparison, not part of Starling.

## Summary

| # | Moment | Verdict | Key measured numbers | Reason |
|---|---|---|---|---|
| 0 | Startup | **PASS** | all live after 5.1 s | all 4 nodes live and central server healthy 5.1s after launch; all camera zones healthy; demo-script panel lists 9 steps |
| 1 | Normal walk | **PASS** | 4 identities, mean error 0.41 m | 4 identities tracked, labels unchanged for 25 s, max displacement 21.1 m, mean error 0.41 m vs ground truth |
| 2a | Dead zone, healthy exits | **PASS** | region 69 m² vs 932.5 m² reachable (ratio 0.074); max in healthy zones 0 m²; lasted 25.5 s | region confined to the block for 25.5 s (0 m² in healthy zones, at most 0.5 m² outside the block), final 69 m² vs 932.5 m² reachable (ratio 0.074), same identity P-005 on re-emergence |
| 2b | Dead zone, occluded exit | **PASS** | leak into occluded zone 1: 105 m²; into other zones: 0.0 m² | region leaked into camera 1's zone (up to 105 m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in 26 of 26 samples; same identity on re-emergence |
| 3 | Partition and heal | **PASS** | heal→converged 3.5 s, max spread 64.0 | partition shown on all nodes, spread grew to 64.0, converged 3.5s after heal with gaps=0 |
| 4 | Lying node | **PASS** | liar <0.7 after 9.4 s; recovered >0.9 after 8.3 s | liar's reputation < 0.7 after 9.4s (73.0 claims rejected), honest nodes stayed >= 1.0 (their rejected counters grew by [0.0, 0, 0.0] during the test), recovered > 0.9 8.3s after stopping |
| 5 | Query and refusal | **PASS** | 5 queries (answer, unknown, partitioned, productivity, blind-block) | valid query answered (confirmed/inferred/unreachable); unknown worker and productivity purpose refused with reasons; partition edge case: refused; blind-block query reported: Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothes |
| 6 | Robustness | **PASS** | reload 0.1 s; offline 5.8 s; back 2.5 s | reload recovered in 0.1s; killed node OFFLINE after 5.8s (its camera zone: silent); LIVE again 2.5s after restart; converged 4.9s after restart |
| 7a | Conflict, resolvable | **PASS** | fork RESOLVED_REACHABILITY after heal | no fork while partitioned (370 far-side claims held back); after healing the fork appeared and was resolved by reachability: Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s. |
| 7b | Conflict, ambiguous | **PASS** | fork OPEN; still OPEN 8 s later | no fork while partitioned; after healing one fork appeared and stayed OPEN 8 s later; 4 branch markers drawn at [(7.02, 13.92), (33.36, 12.64), (4.98, 21.3), (33.3, 12.57)]; explanation: Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is |
| 8 | Centralized comparison | **PASS** | partition / kill / restart of the centralized system vs Starling | partition: centralized tracks 3 (PARTIAL) vs Starling 5 of 5; killed: centralized DOWN/0 while Starling kept 5 of 5 and 227 new claims in 8 s; restarted: HEALTHY |

## Moment 0 — Startup: PASS

**What it should demonstrate:** The dashboard loads and all four node processes, the simulator and the centralized comparison server are up.

**Action taken:** Launched the demo in presenter mode (`scripts/run_demo.py --presenter`, launched here via `DemoLauncher`) and opened the dashboard in headless Chromium.

**Verdict reason:** all 4 nodes live and central server healthy 5.1s after launch; all camera zones healthy; demo-script panel lists 9 steps

### 0a_startup_loaded.jpg  (t = 5.4 s since launch)

Dashboard loaded: 4 nodes live, all four camera zones outlined green (healthy), Demo script panel present.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.07",
 "claims_per_node": [
  "48",
  "48",
  "47",
  "48"
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
  "0 of 16",
  "0 of 15",
  "0 of 15",
  "0 of 16"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.8, 1.5) via node 0 err 0.03",
  "P-002 worker-1 seen @(17.6, 1.5) via node 1 err 0.02",
  "P-003 worker-4 seen @(19.1, 17.3) via node 2 err 0.18",
  "P-004 worker-3 seen @(27.9, 1.5) via node 3 err 0.06"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 46 observations delivered."
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
  "seconds_launch_to_all_nodes_live": 5.1,
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

**Verdict reason:** 4 identities tracked, labels unchanged for 25 s, max displacement 21.1 m, mean error 0.41 m vs ground truth

### 1a_walk_start.jpg  (t = 5.6 s since launch)

Four workers, four identities (P-00x) with ground-truth rings.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.07",
 "claims_per_node": [
  "48",
  "48",
  "47",
  "48"
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
  "0 of 16",
  "0 of 15",
  "0 of 15",
  "0 of 16"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.8, 1.5) via node 0 err 0.03",
  "P-002 worker-1 seen @(17.6, 1.5) via node 1 err 0.02",
  "P-003 worker-4 seen @(19.1, 17.3) via node 2 err 0.18",
  "P-004 worker-3 seen @(27.9, 1.5) via node 3 err 0.06"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 46 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 1b_walk_later.jpg  (t = 14.1 s since launch)

Same identities at new positions a few seconds later.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "13.0",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.11",
 "claims_per_node": [
  "224",
  "224",
  "224",
  "226"
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
  "0 of 61",
  "0 of 58",
  "0 of 60",
  "0 of 60"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 2.6) via node 0 err 0.12",
  "P-002 worker-1 seen @(22.1, 1.6) via node 1 err 0.11",
  "P-003 worker-4 seen @(25.1, 18.4) via node 2 err 0.10",
  "P-004 worker-3 seen @(34.6, 1.5) via node 3 err 0.10"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 231 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 1c_walk_25s.jpg  (t = 31.6 s since launch)

25 s in: identities unchanged.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "29.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "552",
  "552",
  "553",
  "553"
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
  "0 of 142",
  "0 of 138",
  "0 of 141",
  "0 of 138"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 21.7) via node 0 err 0.74",
  "P-002 worker-1 seen @(19.6, 7.5) via node 1 err 0.62",
  "P-003 worker-4 seen @(16.0, 23.5) via node 2 err 0.62",
  "P-004 worker-3 seen @(39.0, 10.1) via node 3 err 0.06"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 551 observations delivered."
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
  "max_displacement_m": 21.1,
  "mean_position_error_m_avg": 0.41,
  "mean_position_error_m_samples": [
    0.61,
    0.51,
    0.52,
    0.68,
    0.68,
    0.69,
    0.63,
    0.66
  ],
  "per_identity_error_m": [
    0.74,
    0.62,
    0.62,
    0.06
  ]
}
```

## Moment 2a — Dead zone, healthy exits: PASS

**What it should demonstrate:** A worker disappears into the 12x7 m uncovered block for ~27 s. Every exit is watched by a healthy camera that saw nobody leave, so the candidate region must stay inside the block, never include a healthy camera's zone, and be much smaller than plain reachability allows; the same identity is restored on re-emergence.

**Action taken:** Pressed 'Dead zone - healthy exits' (the simulator moves worker-2 from the west door through the block and out through the east zone), then sampled the page (region area, reachable-without-negative-evidence area, healthy-zone overlap, area outside the block) about every second.

**Verdict reason:** region confined to the block for 25.5 s (0 m² in healthy zones, at most 0.5 m² outside the block), final 69 m² vs 932.5 m² reachable (ratio 0.074), same identity P-005 on re-emergence

### 2a1_before.jpg  (t = 31.8 s since launch)

Before the episode: cameras all healthy (green); worker-2 is not in the building yet.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "29.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "552",
  "552",
  "553",
  "553"
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
  "0 of 142",
  "0 of 138",
  "0 of 141",
  "0 of 138"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 21.7) via node 0 err 0.74",
  "P-002 worker-1 seen @(19.6, 7.5) via node 1 err 0.62",
  "P-003 worker-4 seen @(16.0, 23.5) via node 2 err 0.62",
  "P-004 worker-3 seen @(39.0, 10.1) via node 3 err 0.06"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "4",
  "detail": "4 identities in the shared table; 551 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a2_hidden_0s.jpg  (t = 49.5 s since launch)

P-005 hidden 2 s: search area 12.2 m² vs 28.6 m² reachable without negative evidence (43%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "47.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.18",
 "claims_per_node": [
  "950",
  "949",
  "949",
  "949"
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
  "1 of 292",
  "0 of 223",
  "0 of 227",
  "0 of 226"
 ],
 "regions": {
  "P-005": {
   "area_m2": 12.2,
   "reachable_m2": 28.6,
   "ratio": "43%",
   "in_blind_block_m2": 12.2,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 17.3) via node 0 err 0.23",
  "P-002 worker-1 seen @(22.4, 1.4) via node 1 err 0.25",
  "P-003 worker-4 seen @(24.7, 17.6) via node 2 err 0.11",
  "P-004 worker-3 seen @(39.0, 23.4) via node 3 err 0.12",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 956 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a3_hidden_5s.jpg  (t = 55.4 s since launch)

P-005 hidden 8 s: search area 59.8 m² vs 389.8 m² reachable without negative evidence (15%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "53.0",
 "convergence": "CONVERGED",
 "spread": "0",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.29",
 "claims_per_node": [
  "1067",
  "1067",
  "1067",
  "1067"
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
  "1 of 318",
  "0 of 249",
  "0 of 253",
  "0 of 250"
 ],
 "regions": {
  "P-005": {
   "area_m2": 59.8,
   "reachable_m2": 389.8,
   "ratio": "15%",
   "in_blind_block_m2": 59.8,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 10.2) via node 0 err 0.33",
  "P-002 worker-1 seen @(25.0, 2.6) via node 1 err 0.05",
  "P-003 worker-4 seen @(25.0, 21.3) via node 2 err 0.22",
  "P-004 worker-3 seen @(32.9, 23.7) via node 3 err 0.57",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1078 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 2a4_hidden_10s.jpg  (t = 60.2 s since launch)

P-005 hidden 11 s: search area 69 m² vs 618.9 m² reachable without negative evidence (11%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "56.0",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "1123",
  "1123",
  "1123",
  "1124"
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
  "1 of 332",
  "0 of 263",
  "0 of 268",
  "0 of 263"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 618.9,
   "ratio": "11%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 8.7) via node 0 err 0.47",
  "P-002 worker-1 seen @(25.0, 4.9) via node 1 err 0.60",
  "P-003 worker-4 seen @(24.3, 23.6) via node 2 err 0.47",
  "P-004 worker-3 seen @(29.3, 23.5) via node 3 err 0.51",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1134 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a5_hidden_16s.jpg  (t = 66.1 s since launch)

P-005 hidden 17 s: search area 69 m² vs 853.3 m² reachable without negative evidence (8%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "62.0",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.36",
 "claims_per_node": [
  "1239",
  "1240",
  "1239",
  "1241"
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
  "1 of 367",
  "0 of 295",
  "0 of 302",
  "0 of 298"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 853.3,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 3.2) via node 0 err 0.46",
  "P-002 worker-1 seen @(21.5, 7.5) via node 1 err 0.53",
  "P-003 worker-4 seen @(20.0, 23.4) via node 2 err 0.44",
  "P-004 worker-3 seen @(27.0, 23.1) via node 3 err 0.03",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1254 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a6_hidden_22s.jpg  (t = 71.9 s since launch)

P-005 hidden 22.8 s: search area 69 m² vs 932.5 m² reachable without negative evidence (7%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "67.8",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.72",
 "claims_per_node": [
  "1358",
  "1358",
  "1359",
  "1359"
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
  "1 of 397",
  "0 of 325",
  "0 of 331",
  "0 of 328"
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
  "P-001 worker-0 seen @(4.0, 1.6) via node 0 err 0.81",
  "P-002 worker-1 seen @(15.7, 7.5) via node 1 err 0.68",
  "P-003 worker-4 seen @(15.1, 22.7) via node 2 err 0.60",
  "P-004 worker-3 seen @(27.1, 17.9) via node 3 err 0.77",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1377 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2a7_reemerged.jpg  (t = 76.0 s since launch)

worker-2 re-emerges from the block; identity now P-005 (before: P-005).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "71.8",
 "convergence": "CONVERGED",
 "spread": "0",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.40",
 "claims_per_node": [
  "1437",
  "1437",
  "1437",
  "1437"
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
  "1 of 417",
  "0 of 345",
  "0 of 350",
  "1 of 352"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(6.6, 1.6) via node 0 err 0.42",
  "P-002 worker-1 seen @(14.9, 6.5) via node 1 err 0.19",
  "P-003 worker-4 seen @(14.9, 18.7) via node 2 err 0.62",
  "P-004 worker-3 seen @(27.0, 15.3) via node 3 err 0.11",
  "P-005 worker-2 seen @(26.1, 12.0) via node 3 err 0.65"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 1459 observations delivered."
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
  "seconds_click_to_region_on_page": 17.0,
  "identity_measured": "P-005",
  "identity_after_reemerging": "P-005",
  "same_identity_after": true,
  "n_samples": 26,
  "region_lifetime_s": 25.5,
  "first_area_m2": 12.2,
  "max_area_m2": 69,
  "final_area_m2": 69,
  "reach_at_end_m2": 932.5,
  "final_ratio_area_over_reach": 0.074,
  "max_healthy_zone_overlap_m2": 0,
  "max_area_outside_blind_block_m2": 0.0,
  "samples": [
    {
      "t": 0.0,
      "area": 12.2,
      "reach": 28.6,
      "ratio_pct": "43%",
      "blind": 12.2,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 2,
      "explanation": "worker-2 unseen 2 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 12 m² instead of 29 m² reachable."
    },
    {
      "t": 1.2,
      "area": 20.1,
      "reach": 59.8,
      "ratio_pct": "34%",
      "blind": 20.1,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 3,
      "explanation": "worker-2 unseen 3 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 20 m² instead of 60 m² reachable."
    },
    {
      "t": 2.2,
      "area": 29.8,
      "reach": 103.4,
      "ratio_pct": "29%",
      "blind": 29.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 4,
      "explanation": "worker-2 unseen 4 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 30 m² instead of 103 m² reachable."
    },
    {
      "t": 3.1,
      "area": 35.6,
      "reach": 155.7,
      "ratio_pct": "23%",
      "blind": 35.6,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 5,
      "explanation": "worker-2 unseen 5 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 36 m² instead of 156 m² reachable."
    },
    {
      "t": 4.0,
      "area": 43.1,
      "reach": 221.8,
      "ratio_pct": "19%",
      "blind": 43.1,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 6,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 43 m² instead of 222 m² reachable."
    },
    {
      "t": 4.9,
      "area": 43.1,
      "reach": 221.8,
      "ratio_pct": "19%",
      "blind": 43.1,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 6,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 43 m² instead of 222 m² reachable."
    },
    {
      "t": 5.8,
      "area": 59.8,
      "reach": 389.8,
      "ratio_pct": "15%",
      "blind": 59.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 8,
      "explanation": "worker-2 unseen 8 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 60 m² instead of 390 m² reachable."
    },
    {
      "t": 7.1,
      "area": 59.8,
      "reach": 389.8,
      "ratio_pct": "15%",
      "blind": 59.8,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 8,
      "explanation": "worker-2 unseen 8 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 60 m² instead of 390 m² reachable."
    },
    {
      "t": 8.0,
      "area": 69,
      "reach": 551.4,
      "ratio_pct": "13%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 10,
      "explanation": "worker-2 unseen 10 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 551 m² reachable."
    },
    {
      "t": 9.8,
      "area": 69,
      "reach": 618.9,
      "ratio_pct": "11%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 11,
      "explanation": "worker-2 unseen 11 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 619 m² reachable."
    },
    {
      "t": 10.7,
      "area": 69,
      "reach": 618.9,
      "ratio_pct": "11%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 11,
      "explanation": "worker-2 unseen 11 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 619 m² reachable."
    },
    {
      "t": 11.9,
      "area": 69,
      "reach": 713,
      "ratio_pct": "10%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 13,
      "explanation": "worker-2 unseen 13 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 713 m² reachable."
    },
    {
      "t": 12.8,
      "area": 69,
      "reach": 749.3,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 14,
      "explanation": "worker-2 unseen 14 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 749 m² reachable."
    },
    {
      "t": 13.8,
      "area": 69,
      "reach": 749.3,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 14,
      "explanation": "worker-2 unseen 14 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 749 m² reachable."
    },
    {
      "t": 14.7,
      "area": 69,
      "reach": 787.2,
      "ratio_pct": "9%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 15,
      "explanation": "worker-2 unseen 15 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 787 m² reachable."
    },
    {
      "t": 15.6,
      "area": 69,
      "reach": 824.7,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 16,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 825 m² reachable."
    },
    {
      "t": 16.5,
      "area": 69,
      "reach": 853.3,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 17,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 853 m² reachable."
    },
    {
      "t": 17.8,
      "area": 69,
      "reach": 881.6,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 18,
      "explanation": "worker-2 unseen 18 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 882 m² reachable."
    },
    {
      "t": 18.7,
      "area": 69,
      "reach": 901.6,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 18.8,
      "explanation": "worker-2 unseen 19 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 902 m² reachable."
    },
    {
      "t": 19.6,
      "area": 69,
      "reach": 924.3,
      "ratio_pct": "8%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 20,
      "explanation": "worker-2 unseen 20 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 924 m² reachable."
    },
    {
      "t": 20.5,
      "area": 69,
      "reach": 931.9,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 21,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 21.5,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 22,
      "explanation": "worker-2 unseen 22 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 22.4,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 22.8,
      "explanation": "worker-2 unseen 23 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 23.6,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 23.8,
      "explanation": "worker-2 unseen 24 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 24.5,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 24.8,
      "explanation": "worker-2 unseen 25 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    },
    {
      "t": 25.5,
      "area": 69,
      "reach": 932.5,
      "ratio_pct": "7%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,1,2,3",
      "silent": "",
      "occluded": "",
      "hidden_s": 25.8,
      "explanation": "worker-2 unseen 26 s. Cameras 0, 1, 2, 3 are healthy and saw nobody, so their zones are ruled out. Search area 69 m² instead of 932 m² reachable."
    }
  ]
}
```

## Moment 2b — Dead zone, occluded exit: PASS

**What it should demonstrate:** Same walk, but the north exit camera (node 1) is occluded for the whole episode, so it sends no healthy attestation. Its silence must NOT be counted as evidence: the region should leak into that camera's zone, and only that one, and the dashboard should say why.

**Action taken:** Waited for worker-2 to be back at the door, then pressed 'Dead zone - occluded camera 1' (the simulator occludes camera 1 and repeats the walk); sampled the page about every second.

**Verdict reason:** region leaked into camera 1's zone (up to 105 m²) and into no other zone; page said 'camera 1 is silent (occluded...): its silence is not counted as evidence' in 26 of 26 samples; same identity on re-emergence

### 2b1_before.jpg  (t = 169.9 s since launch)

Before the episode: cameras all healthy (green); worker-2 waits at the door.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "163.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.33",
 "claims_per_node": [
  "3681",
  "3680",
  "3675",
  "3680"
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
  "17 of 1138",
  "0 of 782",
  "1 of 855",
  "1 of 897"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.6, 23.5) via node 0 err 0.45",
  "P-002 worker-1 seen @(18.8, 1.4) via node 1 err 0.37",
  "P-003 worker-4 seen @(25.2, 22.3) via node 2 err 0.41",
  "P-004 worker-3 seen @(27.0, 15.5) via node 3 err 0.29",
  "P-013 worker-2 seen @(0.9, 14.6) via node 0 err 0.11"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 3692 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b2_hidden_0s.jpg  (t = 188.5 s since launch)

P-013 hidden 2.4 s: search area 14.9 m² vs 40.7 m² reachable without negative evidence (37%); overlap with healthy cameras' zones 0 m²; zone overlap {}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "182.4",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.50",
 "claims_per_node": [
  "4124",
  "4123",
  "4124",
  "4126"
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
  "17 of 1318",
  "0 of 874",
  "1 of 951",
  "1 of 995"
 ],
 "regions": {
  "P-013": {
   "area_m2": 14.9,
   "reachable_m2": 40.7,
   "ratio": "37%",
   "in_blind_block_m2": 14.9,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 15.7) via node 0 err 0.75",
  "P-002 worker-1 seen @(25.1, 5.1) via node 1 err 0.62",
  "P-003 worker-4 seen @(14.9, 19.5) via node 2 err 0.59",
  "P-004 worker-3 seen @(30.3, 1.4) via node 3 err 0.05",
  "P-013 worker-2 unseen @(14.0, 14.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4130 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b3_hidden_5s.jpg  (t = 194.3 s since launch)

P-013 hidden 7.4 s: search area 89.3 m² vs 342.8 m² reachable without negative evidence (26%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 32.1}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "187.4",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.31",
 "claims_per_node": [
  "4222",
  "4223",
  "4222",
  "4223"
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
  "17 of 1340",
  "0 of 897",
  "1 of 974",
  "1 of 1018"
 ],
 "regions": {
  "P-013": {
   "area_m2": 89.3,
   "reachable_m2": 342.8,
   "ratio": "26%",
   "in_blind_block_m2": 57.1,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 32.1
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 12.6) via node 0 err 0.51",
  "P-002 worker-1 seen @(24.8, 6.7) via node 1 err 0.18",
  "P-003 worker-4 seen @(18.0, 17.4) via node 2 err 0.43",
  "P-004 worker-3 seen @(30.9, 1.6) via node 3 err 0.12",
  "P-013 worker-2 unseen @(14.0, 14.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4229 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b4_hidden_10s.jpg  (t = 199.3 s since launch)

P-013 hidden 12.4 s: search area 172.3 m² vs 686.7 m² reachable without negative evidence (25%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 103.2}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "192.4",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "4318",
  "4320",
  "4318",
  "4319"
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
  "17 of 1365",
  "0 of 922",
  "1 of 1000",
  "1 of 1042"
 ],
 "regions": {
  "P-013": {
   "area_m2": 172.3,
   "reachable_m2": 686.7,
   "ratio": "25%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 103.2
   },
   "silent": "1",
   "occluded": "1"
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 9.0) via node 0 err 0.13",
  "P-002 worker-1 seen @(21.7, 7.5) via node 1 err 0.53",
  "P-003 worker-4 seen @(23.0, 17.4) via node 2 err 0.58",
  "P-004 worker-3 seen @(33.0, 1.5) via node 3 err 0.11",
  "P-013 worker-2 unseen @(14.0, 14.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4325 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b5_hidden_16s.jpg  (t = 205.1 s since launch)

P-013 hidden 18.4 s: search area 174 m² vs 892.1 m² reachable without negative evidence (20%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 105}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "198.4",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.24",
 "claims_per_node": [
  "4432",
  "4432",
  "4431",
  "4430"
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
  "17 of 1388",
  "0 of 947",
  "1 of 1024",
  "1 of 1064"
 ],
 "regions": {
  "P-013": {
   "area_m2": 174,
   "reachable_m2": 892.1,
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
  "P-001 worker-0 seen @(1.0, 2.5) via node 0 err 0.52",
  "P-002 worker-1 seen @(16.8, 7.5) via node 1 err 0.05",
  "P-003 worker-4 seen @(25.0, 21.6) via node 2 err 0.34",
  "P-004 worker-3 seen @(36.0, 1.4) via node 3 err 0.06",
  "P-013 worker-2 unseen @(14.0, 14.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4441 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b6_hidden_22s.jpg  (t = 211.0 s since launch)

P-013 hidden 24.2 s: search area 174 m² vs 932.5 m² reachable without negative evidence (19%); overlap with healthy cameras' zones 0 m²; zone overlap {'1': 105}.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "204.2",
 "convergence": "CONVERGED",
 "spread": "1",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.36",
 "claims_per_node": [
  "4548",
  "4548",
  "4549",
  "4549"
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
  "17 of 1418",
  "0 of 976",
  "1 of 1053",
  "1 of 1092"
 ],
 "regions": {
  "P-013": {
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
  "P-001 worker-0 seen @(6.1, 1.5) via node 0 err 0.05",
  "P-002 worker-1 seen @(15.0, 4.6) via node 1 err 0.66",
  "P-003 worker-4 seen @(21.2, 23.5) via node 2 err 0.64",
  "P-004 worker-3 seen @(38.9, 2.4) via node 3 err 0.07",
  "P-013 worker-2 unseen @(14.0, 14.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 4543 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 2b7_reemerged.jpg  (t = 214.1 s since launch)

worker-2 re-emerges from the block; identity now P-013 (before: P-013).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "207.2",
 "convergence": "CONVERGED",
 "spread": "5",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.53",
 "claims_per_node": [
  "4610",
  "4607",
  "4610",
  "4612"
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
  "17 of 1438",
  "0 of 996",
  "1 of 1071",
  "1 of 1118"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(8.5, 1.5) via node 0 err 0.66",
  "P-002 worker-1 seen @(15.1, 3.0) via node 1 err 0.65",
  "P-003 worker-4 seen @(18.8, 23.5) via node 2 err 0.05",
  "P-004 worker-3 seen @(39.1, 3.5) via node 3 err 0.67",
  "P-013 worker-2 seen @(26.4, 11.9) via node 3 err 0.64"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4603 observations delivered."
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
  "seconds_click_to_region_on_page": 17.8,
  "identity_measured": "P-013",
  "identity_after_reemerging": "P-013",
  "same_identity_after": true,
  "n_samples": 26,
  "region_lifetime_s": 24.6,
  "first_area_m2": 14.9,
  "max_area_m2": 174,
  "final_area_m2": 174,
  "reach_at_end_m2": 932.5,
  "final_ratio_area_over_reach": 0.187,
  "max_healthy_zone_overlap_m2": 0,
  "max_area_outside_blind_block_m2": 105,
  "samples": [
    {
      "t": 0.0,
      "area": 14.9,
      "reach": 40.7,
      "ratio_pct": "37%",
      "blind": 14.9,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 2.4,
      "explanation": "worker-2 unseen 2 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. Search area 15 m² instead of 41 m² reachable."
    },
    {
      "t": 1.2,
      "area": 23.5,
      "reach": 77.1,
      "ratio_pct": "31%",
      "blind": 23.5,
      "healthy_overlap": 0,
      "zone_overlap": {},
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 3.4,
      "explanation": "worker-2 unseen 3 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. Search area 24 m² instead of 77 m² reachable."
    },
    {
      "t": 2.1,
      "area": 33.9,
      "reach": 124.3,
      "ratio_pct": "27%",
      "blind": 31.8,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 2.1
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 4.4,
      "explanation": "worker-2 unseen 4 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 34 m² instead of 124 m² reachable."
    },
    {
      "t": 3.1,
      "area": 46.5,
      "reach": 181.3,
      "ratio_pct": "26%",
      "blind": 37.9,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 8.6
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 5.4,
      "explanation": "worker-2 unseen 5 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 46 m² instead of 181 m² reachable."
    },
    {
      "t": 4.0,
      "area": 66.1,
      "reach": 255.8,
      "ratio_pct": "26%",
      "blind": 47.7,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 18.4
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 6.4,
      "explanation": "worker-2 unseen 6 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 66 m² instead of 256 m² reachable."
    },
    {
      "t": 4.9,
      "area": 89.3,
      "reach": 342.8,
      "ratio_pct": "26%",
      "blind": 57.1,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 32.1
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 7.4,
      "explanation": "worker-2 unseen 7 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 89 m² instead of 343 m² reachable."
    },
    {
      "t": 5.8,
      "area": 89.3,
      "reach": 342.8,
      "ratio_pct": "26%",
      "blind": 57.1,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 32.1
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 7.4,
      "explanation": "worker-2 unseen 7 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 89 m² instead of 343 m² reachable."
    },
    {
      "t": 7.1,
      "area": 135.1,
      "reach": 500.6,
      "ratio_pct": "27%",
      "blind": 68.6,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 66.6
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 9.4,
      "explanation": "worker-2 unseen 9 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 135 m² instead of 501 m² reachable."
    },
    {
      "t": 8.0,
      "area": 154.4,
      "reach": 578.4,
      "ratio_pct": "27%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 85.4
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 10.4,
      "explanation": "worker-2 unseen 10 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 154 m² instead of 578 m² reachable."
    },
    {
      "t": 8.9,
      "area": 166.4,
      "reach": 642.5,
      "ratio_pct": "26%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 97.4
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 11.4,
      "explanation": "worker-2 unseen 11 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 166 m² instead of 642 m² reachable."
    },
    {
      "t": 9.8,
      "area": 166.4,
      "reach": 642.5,
      "ratio_pct": "26%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 97.4
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 11.4,
      "explanation": "worker-2 unseen 11 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 166 m² instead of 642 m² reachable."
    },
    {
      "t": 10.8,
      "area": 172.3,
      "reach": 686.7,
      "ratio_pct": "25%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 103.2
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 12.4,
      "explanation": "worker-2 unseen 12 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 172 m² instead of 687 m² reachable."
    },
    {
      "t": 12.0,
      "area": 174,
      "reach": 765.3,
      "ratio_pct": "23%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 14.4,
      "explanation": "worker-2 unseen 14 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 765 m² reachable."
    },
    {
      "t": 13.0,
      "area": 174,
      "reach": 805.2,
      "ratio_pct": "22%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 15.4,
      "explanation": "worker-2 unseen 15 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 805 m² reachable."
    },
    {
      "t": 13.9,
      "area": 174,
      "reach": 837.9,
      "ratio_pct": "21%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 16.4,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 838 m² reachable."
    },
    {
      "t": 14.8,
      "area": 174,
      "reach": 837.9,
      "ratio_pct": "21%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 16.4,
      "explanation": "worker-2 unseen 16 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 838 m² reachable."
    },
    {
      "t": 15.7,
      "area": 174,
      "reach": 865.1,
      "ratio_pct": "20%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 17.4,
      "explanation": "worker-2 unseen 17 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 865 m² reachable."
    },
    {
      "t": 16.7,
      "area": 174,
      "reach": 892.1,
      "ratio_pct": "20%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 18.4,
      "explanation": "worker-2 unseen 18 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 892 m² reachable."
    },
    {
      "t": 17.9,
      "area": 174,
      "reach": 928.3,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 20.4,
      "explanation": "worker-2 unseen 20 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 928 m² reachable."
    },
    {
      "t": 18.8,
      "area": 174,
      "reach": 928.3,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 20.4,
      "explanation": "worker-2 unseen 20 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 928 m² reachable."
    },
    {
      "t": 19.7,
      "area": 174,
      "reach": 932.4,
      "ratio_pct": "19%",
      "blind": 69,
      "healthy_overlap": 0,
      "zone_overlap": {
        "1": 105
      },
      "healthy": "0,2,3",
      "silent": "1",
      "occluded": "1",
      "hidden_s": 21.4,
      "explanation": "worker-2 unseen 21 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 20.6,
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
      "hidden_s": 22.2,
      "explanation": "worker-2 unseen 22 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 21.6,
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
      "hidden_s": 23.2,
      "explanation": "worker-2 unseen 23 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 22.5,
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
      "hidden_s": 24.2,
      "explanation": "worker-2 unseen 24 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 23.7,
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
      "hidden_s": 25.2,
      "explanation": "worker-2 unseen 25 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 932 m² reachable."
    },
    {
      "t": 24.6,
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
  "samples_where_page_explains_the_silence": 26,
  "explanation_at_peak_leak": "worker-2 unseen 14 s. Cameras 0, 2, 3 are healthy and saw nobody, so their zones are ruled out. camera 1 is silent (occluded, no healthy attestation): its silence is not counted as evidence. The region therefore leaks into camera 1's zone. Search area 174 m² instead of 765 m² reachable."
}
```

## Moment 3 — Partition and heal: PASS

**What it should demonstrate:** Cut nodes {2,3} from {0,1}; both sides keep working; on heal the replicas reconverge (equal claim counts, no gaps).

**Action taken:** Pressed 'Partition {2,3} from {0,1}', waited, pressed 'Heal', and timed how long until the convergence badge read CONVERGED.

**Verdict reason:** partition shown on all nodes, spread grew to 64.0, converged 3.5s after heal with gaps=0

### 3a_before_partition.jpg  (t = 214.3 s since launch)

Before: all nodes hold (almost) the same number of claims.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "208.2",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.37",
 "claims_per_node": [
  "4632",
  "4630",
  "4634",
  "4636"
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
  "17 of 1438",
  "0 of 996",
  "1 of 1071",
  "1 of 1118"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(9.6, 1.4) via node 0 err 0.51",
  "P-002 worker-1 seen @(15.0, 1.9) via node 1 err 0.36",
  "P-003 worker-4 seen @(18.8, 23.5) via node 2 err 0.04",
  "P-004 worker-3 seen @(39.0, 4.5) via node 3 err 0.57",
  "P-013 worker-2 seen @(27.4, 11.9) via node 3 err 0.39"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4628 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 3b_partition_during.jpg  (t = 216.9 s since launch)

Partition applied: every node card reports 'partitioned: yes'.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "209.2",
 "convergence": "PARTITIONED",
 "spread": "6",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.85",
 "claims_per_node": [
  "4652",
  "4650",
  "4655",
  "4656"
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
  "17 of 1446",
  "0 of 1005",
  "1 of 1081",
  "1 of 1137"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(10.6, 1.6) via node 0 err 1.23",
  "P-002 worker-1 seen @(15.6, 1.5) via node 1 err 0.76",
  "P-003 worker-4 seen @(18.1, 23.6) via node 2 err 0.69",
  "P-004 worker-3 seen @(39.0, 5.7) via node 3 err 0.88",
  "P-013 worker-2 seen @(28.4, 12.0) via node 3 err 0.68"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (0 observations never delivered)."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 3c_partition_later.jpg  (t = 229.2 s since launch)

12 s into the partition: the two sides' claim counts have drifted apart.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "222.2",
 "convergence": "PARTITIONED",
 "spread": "73",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.62",
 "claims_per_node": [
  "4777",
  "4777",
  "4848",
  "4850"
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
  "17 of 1504",
  "0 of 1069",
  "1 of 1145",
  "1 of 1264"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 15.9) via node 0 err 0.79",
  "P-002 worker-1 seen @(25.0, 5.3) via node 1 err 0.40",
  "P-003 worker-4 seen @(18.7, 17.5) via node 2 err 0.71",
  "P-004 worker-3 seen @(39.0, 17.8) via node 3 err 0.66",
  "P-013 worker-2 seen @(31.5, 17.5) via node 3 err 0.55"
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

### 3d_after_heal.jpg  (t = 233.5 s since launch)

After heal: CONVERGED, spread 7, gaps 0 (3.5s after pressing Heal).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "226.4",
 "convergence": "CONVERGED",
 "spread": "7",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "5066",
  "5062",
  "5067",
  "5069"
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
  "17 of 1520",
  "0 of 1085",
  "1 of 1161",
  "1 of 1293"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 21.1) via node 0 err 0.65",
  "P-002 worker-1 seen @(23.3, 7.5) via node 1 err 0.68",
  "P-003 worker-4 seen @(23.0, 17.3) via node 2 err 0.66",
  "P-004 worker-3 seen @(38.9, 22.5) via node 3 err 0.67",
  "P-013 worker-2 seen @(27.6, 17.6) via node 3 err 0.51"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4863 observations delivered."
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
      4632.0,
      4630.0,
      4634.0,
      4636.0
    ],
    "spread": 6.0,
    "convergence": "CONVERGED"
  },
  "partition_state_shown_on_all_4_nodes": true,
  "spread_and_claims_during_partition": [
    [
      0.0,
      6.0,
      [
        4652.0,
        4650.0,
        4655.0,
        4656.0
      ]
    ],
    [
      1.5,
      16.0,
      [
        4673.0,
        4674.0,
        4687.0,
        4689.0
      ]
    ],
    [
      3.0,
      22.0,
      [
        4682.0,
        4682.0,
        4702.0,
        4704.0
      ]
    ],
    [
      4.5,
      34.0,
      [
        4700.0,
        4699.0,
        4731.0,
        4733.0
      ]
    ],
    [
      6.1,
      38.0,
      [
        4709.0,
        4709.0,
        4746.0,
        4747.0
      ]
    ],
    [
      7.6,
      48.0,
      [
        4728.0,
        4728.0,
        4774.0,
        4776.0
      ]
    ],
    [
      9.1,
      53.0,
      [
        4738.0,
        4738.0,
        4789.0,
        4791.0
      ]
    ],
    [
      10.6,
      64.0,
      [
        4758.0,
        4757.0,
        4819.0,
        4821.0
      ]
    ]
  ],
  "max_spread_during_partition": 64.0,
  "seconds_from_heal_to_converged": 3.5,
  "after_heal_claims": [
    5066.0,
    5062.0,
    5067.0,
    5069.0
  ],
  "after_heal_gaps": 0.0
}
```

## Moment 4 — Lying node: PASS

**What it should demonstrate:** A node fabricates sightings; peers reject implausible claims and its reputation, as seen by peers, drops; it recovers when it stops. Honest nodes must not lose reputation.

**Action taken:** Selected node 2, pressed 'Make node lie', sampled reputation and rejected-claim counters every ~2 s for up to 40 s, then pressed 'Stop lying' and sampled recovery for up to 60 s.

**Verdict reason:** liar's reputation < 0.7 after 9.4s (73.0 claims rejected), honest nodes stayed >= 1.0 (their rejected counters grew by [0.0, 0, 0.0] during the test), recovered > 0.9 8.3s after stopping

### 4a_before_lie.jpg  (t = 233.8 s since launch)

Before: reputation [1.0, 1.0, 1.0, 1.0], rejected [17.0, 0.0, 1.0, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "226.4",
 "convergence": "CONVERGED",
 "spread": "7",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "5066",
  "5062",
  "5067",
  "5069"
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
  "17 of 1520",
  "0 of 1085",
  "1 of 1161",
  "1 of 1293"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 21.1) via node 0 err 0.65",
  "P-002 worker-1 seen @(23.3, 7.5) via node 1 err 0.68",
  "P-003 worker-4 seen @(23.0, 17.3) via node 2 err 0.66",
  "P-004 worker-3 seen @(38.9, 22.5) via node 3 err 0.67",
  "P-013 worker-2 seen @(27.6, 17.6) via node 3 err 0.51"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 4863 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4b_lying_early.jpg  (t = 240.0 s since launch)

5.4s after 'Make node 2 lie': reputation [1.0, 1.0, 0.73, 1.0], rejected [17.0, 0.0, 18.0, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "232.4",
 "convergence": "CONVERGED",
 "spread": "10",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.56",
 "claims_per_node": [
  "5224",
  "5232",
  "5230",
  "5234"
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
  "0.73",
  "1.00"
 ],
 "rejected": [
  "17 of 1555",
  "0 of 1119",
  "18 of 1242",
  "1 of 1337"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(7.4, 23.6) via node 0 err 0.77",
  "P-002 worker-1 seen @(18.9, 7.5) via node 1 err 0.05",
  "P-003 worker-4 seen @(24.9, 21.4) via node 2 err 0.72",
  "P-004 worker-3 seen @(33.4, 23.6) via node 3 err 0.63",
  "P-013 worker-2 seen @(22.3, 17.4) via node 2 err 0.61"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5014 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4c_lying_dropped.jpg  (t = 252.9 s since launch)

Node 2's reputation has dropped: [1.0, 1.0, 0.54, 1.0], rejected [17.0, 0.0, 73.0, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "245.4",
 "convergence": "CONVERGED",
 "spread": "8",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.15",
 "claims_per_node": [
  "5610",
  "5613",
  "5605",
  "5611"
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
  "0.54",
  "1.00"
 ],
 "rejected": [
  "17 of 1630",
  "0 of 1178",
  "73 of 1396",
  "1 of 1394"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(1.0, 16.6) via node 0 err 0.22",
  "P-002 worker-1 seen @(16.3, 1.5) via node 1 err 0.09",
  "P-003 worker-4 seen @(15.6, 23.5) via node 2 err 0.24",
  "P-004 worker-3 seen @(27.1, 18.2) via node 3 err 0.09",
  "P-013 worker-2 seen @(10.5, 17.6) via node 0 err 0.12"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5311 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4d_recovering.jpg  (t = 259.7 s since launch)

6.0s after 'Stop lying': reputation [1.0, 1.0, 0.88, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "251.4",
 "convergence": "CONVERGED",
 "spread": "5",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.43",
 "claims_per_node": [
  "5765",
  "5765",
  "5760",
  "5765"
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
  "0.88",
  "1.00"
 ],
 "rejected": [
  "17 of 1697",
  "0 of 1213",
  "77 of 1439",
  "1 of 1427"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(1.0, 9.4) via node 0 err 0.45",
  "P-002 worker-1 seen @(20.9, 1.6) via node 1 err 0.36",
  "P-003 worker-4 seen @(15.1, 20.3) via node 2 err 0.43",
  "P-004 worker-3 seen @(27.1, 12.6) via node 3 err 0.43",
  "P-013 worker-2 seen @(5.3, 17.5) via node 0 err 0.46"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5468 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 4e_after_stop.jpg  (t = 262.0 s since launch)

End of recovery window: reputation [0.91, 1.0, 0.92, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "253.4",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "5815",
  "5812",
  "5809",
  "5812"
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
  "0.91",
  "1.00",
  "0.92",
  "1.00"
 ],
 "rejected": [
  "17 of 1709",
  "0 of 1219",
  "77 of 1444",
  "1 of 1433"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(1.1, 8.4) via node 0 err 0.16",
  "P-002 worker-1 seen @(22.6, 1.5) via node 1 err 0.77",
  "P-003 worker-4 seen @(15.2, 18.3) via node 2 err 0.65",
  "P-004 worker-3 seen @(27.0, 10.4) via node 3 err 0.74",
  "P-013 worker-2 seen @(3.7, 17.6) via node 0 err 0.85"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5515 observations delivered."
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
    1.0
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
        1.0
      ]
    },
    {
      "t": 1.8,
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
        1.0
      ]
    },
    {
      "t": 3.6,
      "reputation": [
        1.0,
        1.0,
        0.8,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        8.0,
        1.0
      ]
    },
    {
      "t": 5.4,
      "reputation": [
        1.0,
        1.0,
        0.73,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        18.0,
        1.0
      ]
    },
    {
      "t": 7.5,
      "reputation": [
        1.0,
        1.0,
        0.73,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        24.0,
        1.0
      ]
    },
    {
      "t": 9.4,
      "reputation": [
        1.0,
        1.0,
        0.67,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        36.0,
        1.0
      ]
    },
    {
      "t": 11.2,
      "reputation": [
        1.0,
        1.0,
        0.67,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        41.0,
        1.0
      ]
    },
    {
      "t": 13.0,
      "reputation": [
        1.0,
        1.0,
        0.66,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        56.0,
        1.0
      ]
    },
    {
      "t": 14.8,
      "reputation": [
        1.0,
        1.0,
        0.6,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        61.0,
        1.0
      ]
    },
    {
      "t": 16.6,
      "reputation": [
        1.0,
        1.0,
        0.55,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        68.0,
        1.0
      ]
    },
    {
      "t": 18.5,
      "reputation": [
        1.0,
        1.0,
        0.54,
        1.0
      ],
      "rejected": [
        17.0,
        0.0,
        73.0,
        1.0
      ]
    }
  ],
  "seconds_until_liar_reputation_below_0.7": 9.4,
  "liar_rejected_claims_at_end_of_lying": 73.0,
  "lowest_honest_reputation_while_lying": 1.0,
  "honest_nodes_rejected_claims_added_during_test": [
    0.0,
    0,
    0.0
  ],
  "recovery_samples": [
    {
      "t": 0.0,
      "reputation": [
        1.0,
        1.0,
        0.59,
        1.0
      ]
    },
    {
      "t": 2.0,
      "reputation": [
        1.0,
        1.0,
        0.75,
        1.0
      ]
    },
    {
      "t": 4.0,
      "reputation": [
        1.0,
        1.0,
        0.81,
        1.0
      ]
    },
    {
      "t": 6.0,
      "reputation": [
        1.0,
        1.0,
        0.88,
        1.0
      ]
    },
    {
      "t": 8.3,
      "reputation": [
        0.91,
        1.0,
        0.92,
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

### 5e_query_worker_in_blind_block.jpg  (t = 58.0 s since launch)

Query 'where is worker 2' while worker-2 is hidden in the uncovered block: the answer reports the last confirmed position and the candidate region, not a made-up position.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "55.0",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.15",
 "claims_per_node": [
  "1105",
  "1105",
  "1106",
  "1104"
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
  "1 of 327",
  "0 of 259",
  "0 of 263",
  "0 of 259"
 ],
 "regions": {
  "P-005": {
   "area_m2": 69,
   "reachable_m2": 551.4,
   "ratio": "13%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 9.4) via node 0 err 0.04",
  "P-002 worker-1 seen @(25.0, 4.2) via node 1 err 0.08",
  "P-003 worker-4 seen @(25.0, 23.3) via node 2 err 0.21",
  "P-004 worker-3 seen @(30.3, 23.6) via node 3 err 0.26",
  "P-005 worker-2 unseen @(14.0, 14.4) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "4",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 1114 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 5a_answer_worker3.jpg  (t = 263.1 s since launch)

Valid query 'where is worker 3' (purpose safety).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "255.8",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.95",
 "claims_per_node": [
  "5886",
  "5885",
  "5880",
  "5884"
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
  "0.63",
  "1.00",
  "0.96",
  "1.00"
 ],
 "rejected": [
  "31 of 1737",
  "0 of 1234",
  "77 of 1459",
  "1 of 1447"
 ],
 "regions": {
  "P-013": {
   "area_m2": 18.1,
   "reachable_m2": 31.1,
   "ratio": "58%",
   "in_blind_block_m2": 18.1,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(0.8, 6.5) via node 0 err 1.37",
  "P-002 worker-1 seen @(24.9, 1.8) via node 1 err 0.74",
  "P-003 worker-4 seen @(16.7, 17.5) via node 2 err 0.71",
  "P-004 worker-3 seen @(26.9, 7.8) via node 3 err 0.99",
  "P-013 worker-2 unseen @(3.7, 17.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 5587 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 5b_refusal_unknown.jpg  (t = 264.2 s since launch)

Unanswerable query 'where is worker 9': refused with its reason.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "255.8",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.95",
 "claims_per_node": [
  "5886",
  "5885",
  "5880",
  "5884"
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
  "0.63",
  "1.00",
  "0.96",
  "1.00"
 ],
 "rejected": [
  "31 of 1737",
  "0 of 1234",
  "77 of 1459",
  "1 of 1447"
 ],
 "regions": {
  "P-013": {
   "area_m2": 18.1,
   "reachable_m2": 31.1,
   "ratio": "58%",
   "in_blind_block_m2": 18.1,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(0.8, 6.5) via node 0 err 1.37",
  "P-002 worker-1 seen @(24.9, 1.8) via node 1 err 0.74",
  "P-003 worker-4 seen @(16.7, 17.5) via node 2 err 0.71",
  "P-004 worker-3 seen @(26.9, 7.8) via node 3 err 0.99",
  "P-013 worker-2 unseen @(3.7, 17.6) via node 0 err –"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 5587 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5c_query_while_partitioned.jpg  (t = 272.2 s since launch)

Edge case: 'where is worker 3' while {2,3} is cut off from the querying side.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "263.0",
 "convergence": "PARTITIONED",
 "spread": "32",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "1.67",
 "claims_per_node": [
  "6020",
  "6019",
  "5989",
  "5988"
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
  "0.81",
  "1.00",
  "0.98",
  "1.00"
 ],
 "rejected": [
  "32 of 1826",
  "0 of 1278",
  "77 of 1505",
  "1 of 1490"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(5.2, 1.4) via node 0 err 2.56",
  "P-002 worker-1 seen @(23.6, 7.5) via node 1 err 2.17",
  "P-003 worker-4 seen @(20.7, 17.5) via node 2 err 0.92",
  "P-004 worker-3 seen @(28.5, 1.6) via node 3 err 2.60",
  "P-013 worker-2 seen @(1.1, 14.5) via node 0 err 0.12"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "3",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (276 observations never delivered)."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5d_refusal_productivity.jpg  (t = 277.1 s since launch)

Same query under a `productivity` token: refused (purpose limitation).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "268.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.89",
 "claims_per_node": [
  "6197",
  "6198",
  "6192",
  "6197"
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
  "32 of 1870",
  "0 of 1299",
  "77 of 1528",
  "1 of 1511"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.8, 1.4) via node 0 err 1.32",
  "P-002 worker-1 seen @(19.5, 7.5) via node 1 err 1.08",
  "P-003 worker-4 seen @(24.0, 17.6) via node 2 err 0.65",
  "P-004 worker-3 seen @(34.9, 1.5) via node 3 err 1.24",
  "P-013 worker-2 seen @(1.1, 14.6) via node 0 err 0.16"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5835 observations delivered."
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
    "confirmed": "Confirmed: last seen at (26.9, 7.8) m by node 3, 0s ago, confidence 0.90",
    "inferred": "Inferred: currently seen — no inference needed · last position is appearance-matched, not anchored — treat as a hypothesis",
    "unreachable": "Unreachable nodes: none · 4 of 4 nodes responded",
    "text": "Subject:          P-004\nLast confirmed:   (26.9, 7.8) m, t=255.8, confidence 0.90, node 3\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCompleteness:     4 of 4 nodes responded"
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
    "reason": "Reason: 'P-004' was only observed by node 3, which is/are unreachable for the entire requested window — a partitioned wing, not an absence",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "'P-004' was only observed by node 3, which is/are unreachable for the entire requested window — a partitioned wing, not an absence"
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
    "confirmed": "Confirmed: last seen at (14.0, 14.4) m by node 0, 10s ago, confidence 0.95",
    "inferred": "Inferred: currently unseen — could be anywhere in a 69.0 m² candidate region · last position is appearance-matched, not anchored — treat as a hypothesis",
    "unreachable": "Unreachable nodes: none · 4 of 4 nodes responded",
    "text": "Subject:          P-005\nLast confirmed:   (14.0, 14.4) m, t=45.0, confidence 0.95, node 0\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCandidate region: 69.0 m²\nCompleteness:     4 of 4 nodes responded"
  }
}
```

## Moment 6 — Robustness: PASS

**What it should demonstrate:** The dashboard survives a page reload; a node process that actually dies is shown as OFFLINE (and its camera zone as silent), and shown live again when restarted.

**Action taken:** Reloaded the browser page; hard-killed node 1's OS process (not via any dashboard control), watched its card and zone, restarted the process, and watched it return.

**Verdict reason:** reload recovered in 0.1s; killed node OFFLINE after 5.8s (its camera zone: silent); LIVE again 2.5s after restart; converged 4.9s after restart

### 6a_after_reload.jpg  (t = 277.4 s since launch)

Page reloaded mid-run; recovered in 0.1s with 4 nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "268.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.89",
 "claims_per_node": [
  "6197",
  "6198",
  "6192",
  "6197"
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
  "32 of 1870",
  "0 of 1299",
  "77 of 1528",
  "1 of 1511"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.8, 1.4) via node 0 err 1.32",
  "P-002 worker-1 seen @(19.5, 7.5) via node 1 err 1.08",
  "P-003 worker-4 seen @(24.0, 17.6) via node 2 err 0.65",
  "P-004 worker-3 seen @(34.9, 1.5) via node 3 err 1.24",
  "P-013 worker-2 seen @(1.1, 14.6) via node 0 err 0.16"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 5835 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6b_node1_killed.jpg  (t = 283.5 s since launch)

Node 1's process killed; card reads OFFLINE after 5.8s, its camera zone is 'silent'; nodes live 3.

DOM values read at capture:

```json
{
 "nodes_live": "3",
 "sim_time_s": "274.8",
 "convergence": "CONVERGED",
 "spread": "8",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.86",
 "claims_per_node": [
  "6319",
  "6220",
  "6315",
  "6323"
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
  "32 of 1923",
  "0 of 1304",
  "77 of 1556",
  "1 of 1538"
 ],
 "regions": {
  "P-002": {
   "area_m2": 61.3,
   "reachable_m2": 103.6,
   "ratio": "59%",
   "in_blind_block_m2": 43.8,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {
    "1": 17.5
   },
   "silent": "1",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(12.1, 8.3) via node 0 err 1.43",
  "P-002 worker-1 unseen @(17.4, 7.2) via node 1 err –",
  "P-003 worker-4 seen @(25.2, 21.9) via node 2 err 0.96",
  "P-004 worker-3 seen @(39.2, 4.1) via node 3 err 1.01",
  "P-013 worker-2 seen @(1.0, 14.5) via node 0 err 0.04"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "4",
  "truth": "5",
  "detail": "5 identities in the shared table; 5975 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6c_node1_restarted.jpg  (t = 286.4 s since launch)

Node 1 restarted; LIVE after 2.5s.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "278.4",
 "convergence": "CONVERGING",
 "spread": "130",
 "gaps": "101",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.24",
 "claims_per_node": [
  "6378",
  "6251",
  "6373",
  "6381"
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
  "32 of 1957",
  "0 of 1309",
  "77 of 1574",
  "1 of 1555"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 11.4) via node 0 err 0.03",
  "P-002 worker-1 seen @(15.0, 5.6) via node 1 err 0.14",
  "P-003 worker-4 seen @(22.9, 23.6) via node 2 err 0.70",
  "P-004 worker-3 seen @(38.9, 6.7) via node 3 err 0.14",
  "P-013 worker-2 seen @(1.1, 14.7) via node 0 err 0.20"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 6057 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 6d_after_recovery.jpg  (t = 288.8 s since launch)

After recovery: CONVERGED, gaps 0, claims [6404.0, 6411.0, 6398.0, 6402.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "279.6",
 "convergence": "CONVERGED",
 "spread": "13",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "6404",
  "6411",
  "6398",
  "6402"
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
  "32 of 1971",
  "0 of 1315",
  "77 of 1581",
  "1 of 1562"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.8, 11.4) via node 0 err 0.96",
  "P-002 worker-1 seen @(15.0, 5.2) via node 1 err 0.90",
  "P-003 worker-4 seen @(22.3, 23.4) via node 2 err 0.11",
  "P-004 worker-3 seen @(38.9, 6.5) via node 3 err 0.51",
  "P-013 worker-2 seen @(1.0, 14.6) via node 0 err 0.08"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 6081 observations delivered."
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
  "seconds_until_killed_node_shown_offline": 5.8,
  "killed_node_camera_zone_state": "silent",
  "other_nodes_stayed_live_while_node1_down": true,
  "seconds_until_restarted_node_live": 2.5,
  "seconds_from_restart_to_converged": 4.9
}
```

## Moment 7a — Conflict, resolvable: PASS

**What it should demonstrate:** Both halves of a split network face-anchor a look-alike as the SAME identity; one trajectory is physically impossible from the identity's last confirmed anchor. After the network heals the fork appears and is resolved by reachability, with the reason shown.

**Action taken:** Pressed 'Conflict - resolvable': the dashboard partitions the network, the simulator sends the two face-twins in (A anchored at the west gate twice, B at the east gate ~2 s after A's last anchor), then heals; the real resolver runs on the merged claims.

**Verdict reason:** no fork while partitioned (370 far-side claims held back); after healing the fork appeared and was resolved by reachability: Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s.

### 7a1_before.jpg  (t = 293.0 s since launch)

Clean start: healed network, no forks.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "285.0",
 "convergence": "CONVERGED",
 "spread": "12",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.09",
 "claims_per_node": [
  "6524",
  "6531",
  "6519",
  "6522"
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
  "0 of 33",
  "0 of 16",
  "0 of 16",
  "0 of 15"
 ],
 "regions": {},
 "identities": [
  "P-003 worker-0 seen @(11.9, 14.7) via node 0 err 0.06",
  "P-005 worker-1 seen @(16.6, 1.5) via node 1 err 0.19",
  "P-004 worker-2 seen @(1.0, 14.6) via node 0 err 0.06",
  "P-001 worker-4 seen @(18.4, 23.6) via node 2 err 0.13",
  "P-033 worker-3 seen @(39.0, 10.3) via node 3 err 0.01"
 ],
 "forks": [],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 6182 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 7a2_partitioned_twins.jpg  (t = 315.6 s since launch)

Partitioned: twin A on side {0,1}, twin B on side {2,3}; this variant's fork visible: 0 (conflict (resolvable): partitioned 21 s · 201 far-side claims held back).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "307.0",
 "convergence": "PARTITIONED",
 "spread": "213",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.28",
 "claims_per_node": [
  "6970",
  "6975",
  "6762",
  "6762"
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
  "1 of 356",
  "0 of 128",
  "0 of 122",
  "0 of 124"
 ],
 "regions": {},
 "identities": [
  "P-003 worker-0 seen @(2.7, 23.5) via node 0 err 0.45",
  "P-005 worker-1 seen @(19.5, 7.6) via node 1 err 0.11",
  "P-004 worker-2 seen @(1.1, 14.4) via node 0 err 0.12",
  "P-001 worker-4 seen @(24.9, 17.4) via node 2 err 0.33",
  "P-033 worker-3 seen @(29.9, 23.4) via node 3 err 0.45",
  "P-034 worker-5 seen @(6.2, 20.0) via node 0 err 0.24"
 ],
 "forks": [],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "4",
  "starling_now": "6",
  "truth": "6",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (481 observations never delivered)."
 },
 "conflict": "conflict (resolvable): partitioned 21 s · 201 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 7a3_after_heal_fork.jpg  (t = 333.8 s since launch)

After the network healed: 1 fork(s) shown, open=0.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "324.6",
 "convergence": "CONVERGING",
 "spread": "567",
 "gaps": "1138",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "2.87",
 "claims_per_node": [
  "7336",
  "7541",
  "6974",
  "6984"
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
  "1 of 618",
  "0 of 215",
  "0 of 209",
  "1 of 243"
 ],
 "regions": {},
 "identities": [
  "P-003 worker-0 seen @(1.1, 5.9) via node 0 err 0.53",
  "P-005 worker-1 seen @(18.6, 1.6) via node 1 err 0.10",
  "P-004 worker-2 seen @(1.0, 14.4) via node 0 err 0.12",
  "P-001 worker-4 seen @(15.0, 23.6) via node 2 err 0.52",
  "P-033 worker-3 seen @(27.0, 14.7) via node 3 err 0.53",
  "P-034 worker-5 seen @(29.1, 13.8) via node 3 err 17.85",
  "P-035 worker-5 seen @(12.0, 9.0) via node 0 err 0.42"
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
  "detail": "6 identities in the shared table; 6997 observations delivered."
 },
 "conflict": "conflict (resolvable): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 7a4_8s_later.jpg  (t = 342.0 s since launch)

8 s later: fork status unchanged (['RESOLVED_REACHABILITY']).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "332.4",
 "convergence": "CONVERGED",
 "spread": "18",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.43",
 "claims_per_node": [
  "7993",
  "8000",
  "7982",
  "7991"
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
  "1 of 733",
  "0 of 253",
  "0 of 249",
  "1 of 319"
 ],
 "regions": {},
 "identities": [
  "P-003 worker-0 seen @(6.0, 1.4) via node 0 err 0.75",
  "P-005 worker-1 seen @(21.3, 1.5) via node 1 err 0.29",
  "P-004 worker-2 seen @(1.0, 14.6) via node 0 err 0.09",
  "P-001 worker-4 seen @(15.5, 17.4) via node 2 err 0.33",
  "P-033 worker-3 seen @(27.0, 8.6) via node 3 err 0.44",
  "P-034 worker-5 seen @(9.1, 5.1) via node 0 err 0.66",
  "P-036 – seen @(29.7, 19.9) via node 3 err –"
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
  "detail": "6 identities in the shared table; 7272 observations delivered."
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
  "far_side_claims_held_back_max": 370,
  "seconds_to_fork_after_start": 40.5,
  "fork_status": "RESOLVED_REACHABILITY",
  "fork_status_8s_later": "RESOLVED_REACHABILITY",
  "fork_explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s.",
  "fork_branch_rows": [
    [
      "0",
      "9.71, 12.53",
      "156",
      "0",
      "KEPT"
    ],
    [
      "1",
      "33.36, 12.64",
      "1",
      "3",
      "rejected"
    ]
  ],
  "fork_markers_on_map": [
    {
      "id": "fork-branch-P_100_318s-0",
      "x": 9.71,
      "y": 12.53,
      "text": "kept A"
    },
    {
      "id": "fork-branch-P_100_318s-1",
      "x": 33.36,
      "y": 12.64,
      "text": "rejected B"
    }
  ],
  "forks_open_counter": "0",
  "event_log_head": [
    "331.1s FORK RESOLVED on P-034 by reachability: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s",
    "331.1s FORK OPENED on P-034 (face id P-100): 2 claim chains bind it to incompatible positions (9.71, 12.53) vs (33.36, 12.64)",
    "329.9s CONFLICT (resolvable): network healed; the two sides now merge their claims",
    "329.9s HEAL all links (ok={0: True, 1: True, 2: True, 3: True})",
    "326.8s new identity P-035",
    "293.5s new identity P-034",
    "291.5s SCRIPT conflict_resolvable: started",
    "291.5s PARTITION [0, 1] | [2, 3] (ok={0: True, 1: True, 2: True, 3: True})"
  ]
}
```

## Moment 7b — Conflict, ambiguous: PASS

**What it should demonstrate:** Same set-up, but both trajectories are physically possible. After the network heals the fork appears and STAYS OPEN, shown as an ambiguity for a human with both candidate positions drawn on the map; the system never picks a winner.

**Action taken:** Pressed 'Conflict - ambiguous' (twin A anchored at the west gate once, twin B anchored as the same identity at the east gate 25 s later), waited for the heal and the fork, and checked it 8 s later.

**Verdict reason:** no fork while partitioned; after healing one fork appeared and stayed OPEN 8 s later; 4 branch markers drawn at [(7.02, 13.92), (33.36, 12.64), (4.98, 21.3), (33.3, 12.57)]; explanation: Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is

### 7b1_before.jpg  (t = 346.2 s since launch)

Clean start: healed network, no forks.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "337.4",
 "convergence": "CONVERGED",
 "spread": "27",
 "gaps": "0",
 "partition": "none",
 "forks_open": "0",
 "mean_error_m": "0.50",
 "claims_per_node": [
  "8164",
  "8137",
  "8155",
  "8164"
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
  "0 of 48",
  "0 of 16",
  "0 of 17",
  "0 of 32"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.9, 1.5) via node 0 err 0.76",
  "P-002 worker-1 seen @(24.4, 1.5) via node 1 err 0.57",
  "P-004 worker-4 seen @(18.6, 17.4) via node 2 err 0.43",
  "P-005 worker-3 seen @(27.0, 3.4) via node 3 err 0.67",
  "P-003 worker-2 seen @(1.1, 14.4) via node 0 err 0.08",
  "P-006 worker-5 seen @(4.9, 5.6) via node 0 err 0.51",
  "P-007 worker-6 seen @(34.3, 20.0) via node 3 err 0.50"
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
  "detail": "6 identities in the shared table; 7451 observations delivered."
 },
 "conflict": "no conflict running",
 "query": {
  "status": "none"
 }
}
```

### 7b2_partitioned_twins.jpg  (t = 368.7 s since launch)

Partitioned: twin A on side {0,1}, twin B on side {2,3}; this variant's fork visible: 0 (conflict (ambiguous): partitioned 21 s · 292 far-side claims held back).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "358.4",
 "convergence": "PARTITIONED",
 "spread": "206",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "0",
 "mean_error_m": "0.57",
 "claims_per_node": [
  "8684",
  "8690",
  "8484",
  "8486"
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
  "1 of 470",
  "0 of 120",
  "0 of 123",
  "22 of 245"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(12.0, 22.0) via node 0 err 0.68",
  "P-002 worker-1 seen @(17.5, 7.5) via node 1 err 0.46",
  "P-004 worker-4 seen @(22.2, 23.5) via node 2 err 0.76",
  "P-005 worker-3 seen @(39.0, 10.8) via node 3 err 0.65",
  "P-003 worker-2 seen @(1.1, 14.4) via node 0 err 0.11",
  "P-006 worker-5 seen @(7.4, 21.9) via node 0 err 0.56",
  "P-007 worker-6 seen @(38.0, 5.2) via node 3 err 0.71",
  "P-008 worker-7 seen @(8.9, 22.1) via node 0 err 0.60"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  }
 ],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "5",
  "starling_now": "8",
  "truth": "8",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (968 observations never delivered)."
 },
 "conflict": "conflict (ambiguous): partitioned 21 s · 292 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 7b3_after_heal_fork.jpg  (t = 386.9 s since launch)

After the network healed: 2 fork(s) shown, open=1.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "376.0",
 "convergence": "CONVERGING",
 "spread": "257",
 "gaps": "1276",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "9068",
  "9042",
  "8811",
  "8823"
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
  "2 of 738",
  "0 of 204",
  "0 of 205",
  "47 of 469"
 ],
 "regions": {
  "P-006": {
   "area_m2": 69,
   "reachable_m2": 587.8,
   "ratio": "12%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 18.9) via node 0 err 0.89",
  "P-002 worker-1 seen @(22.5, 1.5) via node 1 err 0.74",
  "P-004 worker-4 seen @(14.8, 19.4) via node 2 err 0.38",
  "P-005 worker-3 seen @(32.4, 23.6) via node 3 err 0.92",
  "P-003 worker-2 seen @(1.1, 14.6) via node 0 err 0.14",
  "P-006 worker-5 unseen @(10.8, 21.9) via node 0 err –",
  "P-007 worker-6 seen @(32.0, 9.0) via node 3 err 0.77",
  "P-008 worker-7 forked @(5.0, 10.0) via node 0 err 0.76",
  "P-031 worker-8 seen @(29.0, 19.6) via node 3 err 0.47"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "7",
  "truth": "8",
  "detail": "7 identities in the shared table; 8320 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 7b4_8s_later.jpg  (t = 395.2 s since launch)

8 s later: fork status unchanged (['RESOLVED_REACHABILITY', 'OPEN']).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "383.2",
 "convergence": "CONVERGED",
 "spread": "18",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.60",
 "claims_per_node": [
  "9943",
  "9950",
  "9932",
  "9943"
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
  "0.83"
 ],
 "rejected": [
  "2 of 853",
  "0 of 243",
  "0 of 245",
  "56 of 581"
 ],
 "regions": {
  "P-006": {
   "area_m2": 69,
   "reachable_m2": 886.8,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  },
  "P-007": {
   "area_m2": 12.4,
   "reachable_m2": 27.7,
   "ratio": "45%",
   "in_blind_block_m2": 12.4,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 12.3) via node 0 err 0.97",
  "P-002 worker-1 seen @(25.0, 3.6) via node 1 err 0.48",
  "P-004 worker-4 seen @(18.3, 17.5) via node 2 err 0.86",
  "P-005 worker-3 seen @(27.5, 23.7) via node 3 err 0.17",
  "P-003 worker-2 seen @(1.0, 14.4) via node 0 err 0.07",
  "P-006 worker-5 unseen @(10.8, 21.9) via node 0 err –",
  "P-007 worker-6 unseen @(36.4, 9.1) via node 3 err –",
  "P-008 worker-7 forked @(6.3, 5.0) via node 0 err 0.87",
  "P-031 worker-8 seen @(34.9, 20.1) via node 3 err 0.80"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "7",
  "starling_now": "6",
  "truth": "7",
  "detail": "7 identities in the shared table; 8598 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "other_forks_present": [
    {
      "status": "RESOLVED_REACHABILITY",
      "text": "RESOLVED (reachability) identity P-007 (face id P-100) · opened at sim t = 318.4 s · (older; no longer in the resolver window)Resolved by reachability: branch 0"
    }
  ],
  "variant": "ambiguous",
  "forks_visible_while_partitioned": 0,
  "far_side_claims_held_back_max": 561,
  "seconds_to_fork_after_start": 40.4,
  "fork_status": "OPEN",
  "fork_status_8s_later": "OPEN",
  "fork_explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57).",
  "fork_branch_rows": [
    [
      "0",
      "4.98, 21.3",
      "124",
      "0",
      "possible"
    ],
    [
      "1",
      "33.3, 12.57",
      "1",
      "3",
      "possible"
    ]
  ],
  "fork_markers_on_map": [
    {
      "id": "fork-branch-P_100_318s-0",
      "x": 7.02,
      "y": 13.92,
      "text": "kept A"
    },
    {
      "id": "fork-branch-P_100_318s-1",
      "x": 33.36,
      "y": 12.64,
      "text": "rejected B"
    },
    {
      "id": "fork-branch-P_101_363s-0",
      "x": 4.98,
      "y": 21.3,
      "text": "? A"
    },
    {
      "id": "fork-branch-P_101_363s-1",
      "x": 33.3,
      "y": 12.57,
      "text": "? B"
    }
  ],
  "forks_open_counter": "1",
  "event_log_head": [
    "384.2s FORK OPENED on P-008 (face id P-101): 2 claim chains bind it to incompatible positions (4.98, 21.3) vs (33.3, 12.57)",
    "383.1s CONFLICT (ambiguous): network healed; the two sides now merge their claims",
    "383.1s HEAL all links (ok={0: True, 1: True, 2: True, 3: True})",
    "381.9s worker-6 RE-SEEN as the same identity after 6.0s (region peaked/ended at 34.6 m²)",
    "377.6s worker-6 went UNSEEN at (29.62, 4.94) — candidate region opened",
    "373.8s new identity P-031",
    "372.6s worker-5 went UNSEEN at (10.83, 21.95) — candidate region opened",
    "347.2s new identity P-008"
  ]
}
```

## Moment 8 — Centralized comparison: PASS

**What it should demonstrate:** A centralized single-server system (the original project's matcher; NOT Starling) runs beside Starling on the same input. Under a partition it must lose the cut-off cameras' workers while Starling keeps tracking all of them; with the server killed it must be DOWN while Starling is unaffected; restarted, it recovers (from empty state).

**Action taken:** Pressed Partition, read both panels, healed; pressed 'Kill central server' (the server process exits), read both panels and Starling's claim counter over 8 s; pressed 'Restart central server'.

**Verdict reason:** partition: centralized tracks 3 (PARTIAL) vs Starling 5 of 5; killed: centralized DOWN/0 while Starling kept 5 of 5 and 227 new claims in 8 s; restarted: HEALTHY

### 8a_healthy.jpg  (t = 439.5 s since launch)

Healthy: centralized tracks 6, Starling tracks 6, actually present 5.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "427.0",
 "convergence": "CONVERGED",
 "spread": "22",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.39",
 "claims_per_node": [
  "11366",
  "11344",
  "11361",
  "11365"
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
  "0.73"
 ],
 "rejected": [
  "2 of 1425",
  "0 of 454",
  "0 of 451",
  "110 of 1008"
 ],
 "regions": {},
 "identities": [
  "P-001 worker-0 seen @(11.8, 18.8) via node 0 err 0.97",
  "P-002 worker-1 seen @(24.6, 1.5) via node 1 err 0.05",
  "P-004 worker-4 seen @(22.4, 17.5) via node 2 err 0.03",
  "P-005 worker-3 seen @(31.6, 1.5) via node 3 err 0.84",
  "P-003 worker-2 seen @(1.0, 14.4) via node 0 err 0.06",
  "P-008 worker-7 forked @(5.2, 21.9) via node 0 err –",
  "P-031 worker-8 seen @(36.4, 9.1) via node 3 err –"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "6",
  "starling_now": "6",
  "truth": "5",
  "detail": "7 identities in the shared table; 10031 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 8b_partition_central_loses_side.jpg  (t = 448.4 s since launch)

Partitioned: centralized PARTIAL tracks 3; Starling tracks 5 of 5 present. Cameras 2, 3 cannot reach the server: their workers are lost (1351 observations never delivered).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "436.2",
 "convergence": "PARTITIONED",
 "spread": "42",
 "gaps": "0",
 "partition": "CUT",
 "forks_open": "1",
 "mean_error_m": "1.04",
 "claims_per_node": [
  "11522",
  "11527",
  "11485",
  "11485"
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
  "0.80"
 ],
 "rejected": [
  "2 of 1523",
  "0 of 501",
  "0 of 500",
  "110 of 1057"
 ],
 "regions": {
  "P-031": {
   "area_m2": 69,
   "reachable_m2": 354.6,
   "ratio": "20%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(5.7, 23.3) via node 0 err 1.49",
  "P-002 worker-1 seen @(25.1, 7.1) via node 1 err 0.93",
  "P-004 worker-4 seen @(25.0, 20.5) via node 2 err 1.23",
  "P-005 worker-3 seen @(39.0, 4.1) via node 3 err 1.40",
  "P-003 worker-2 seen @(1.1, 14.6) via node 0 err 0.14",
  "P-008 worker-7 forked @(5.2, 21.9) via node 0 err –",
  "P-031 worker-8 unseen @(36.4, 9.1) via node 3 err –"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "PARTIAL",
  "tracked_now": "3",
  "starling_now": "5",
  "truth": "5",
  "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (1351 observations never delivered)."
 },
 "conflict": "conflict (ambiguous): healed 38 s · 80 far-side claims held back",
 "query": {
  "status": "none"
 }
}
```

### 8c_central_killed.jpg  (t = 454.5 s since launch)

Central server killed: status DOWN, tracks 0; Starling tracks 5 of 5 present, 4 nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "442.8",
 "convergence": "CONVERGED",
 "spread": "13",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.28",
 "claims_per_node": [
  "11738",
  "11746",
  "11733",
  "11736"
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
  "2 of 1570",
  "0 of 525",
  "0 of 523",
  "110 of 1081"
 ],
 "regions": {
  "P-031": {
   "area_m2": 69,
   "reachable_m2": 616.3,
   "ratio": "11%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.0, 20.1) via node 0 err 0.40",
  "P-002 worker-1 seen @(18.7, 7.6) via node 1 err 0.34",
  "P-004 worker-4 seen @(23.0, 23.4) via node 2 err 0.45",
  "P-005 worker-3 seen @(38.9, 9.0) via node 3 err 0.13",
  "P-003 worker-2 seen @(1.0, 14.6) via node 0 err 0.08",
  "P-008 worker-7 forked @(5.2, 21.9) via node 0 err –",
  "P-031 worker-8 unseen @(36.4, 9.1) via node 3 err –"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "DOWN",
  "tracked_now": "0",
  "starling_now": "5",
  "truth": "5",
  "detail": "The central server process is not running: nothing is tracked."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 8d_starling_unaffected.jpg  (t = 460.8 s since launch)

6 s later, central still DOWN; Starling claims 3852.0 (was 3625.0), convergence CONVERGED.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "448.2",
 "convergence": "CONVERGED",
 "spread": "15",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.42",
 "claims_per_node": [
  "11881",
  "11866",
  "11876",
  "11879"
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
  "2 of 1633",
  "0 of 557",
  "0 of 553",
  "110 of 1109"
 ],
 "regions": {
  "P-031": {
   "area_m2": 69,
   "reachable_m2": 823.4,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(0.9, 16.8) via node 0 err 0.67",
  "P-002 worker-1 seen @(14.9, 6.0) via node 1 err 0.50",
  "P-004 worker-4 seen @(17.6, 23.3) via node 2 err 0.49",
  "P-005 worker-3 seen @(39.0, 14.5) via node 3 err 0.40",
  "P-003 worker-2 seen @(1.0, 14.5) via node 0 err 0.05",
  "P-008 worker-7 forked @(5.2, 21.9) via node 0 err –",
  "P-031 worker-8 unseen @(36.4, 9.1) via node 3 err –"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "DOWN",
  "tracked_now": "0",
  "starling_now": "5",
  "truth": "5",
  "detail": "The central server process is not running: nothing is tracked."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
 "query": {
  "status": "none"
 }
}
```

### 8e_central_restarted.jpg  (t = 463.6 s since launch)

Central server restarted: HEALTHY, tracks 5.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "451.2",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "forks_open": "1",
 "mean_error_m": "0.52",
 "claims_per_node": [
  "11952",
  "11935",
  "11947",
  "11950"
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
  "2 of 1659",
  "0 of 572",
  "0 of 568",
  "110 of 1124"
 ],
 "regions": {
  "P-031": {
   "area_m2": 69,
   "reachable_m2": 899,
   "ratio": "8%",
   "in_blind_block_m2": 69,
   "in_healthy_zones_m2": 0,
   "zone_overlap_m2": {},
   "silent": "",
   "occluded": ""
  }
 },
 "identities": [
  "P-001 worker-0 seen @(1.1, 12.8) via node 0 err 0.53",
  "P-002 worker-1 seen @(14.9, 2.8) via node 1 err 0.54",
  "P-004 worker-4 seen @(16.1, 23.4) via node 2 err 0.53",
  "P-005 worker-3 seen @(39.0, 17.6) via node 3 err 0.89",
  "P-003 worker-2 seen @(1.1, 14.6) via node 0 err 0.11",
  "P-008 worker-7 forked @(5.2, 21.9) via node 0 err –",
  "P-031 worker-8 unseen @(36.4, 9.1) via node 3 err –"
 ],
 "forks": [
  {
   "status": "RESOLVED_REACHABILITY",
   "explanation": "Resolved by reachability: branch 0 kept. Rejected: branch 1 requires 6.7 m/s over 4.2 s, exceeds v_max 1.6 m/s."
  },
  {
   "status": "OPEN",
   "explanation": "Both trajectories are physically possible from the identity's last confirmed anchor, so the system does NOT pick one (never by score). It is an ambiguity for a human: branch 0 at (4.98, 21.3) OR branch 1 at (33.3, 12.57)."
  }
 ],
 "centralized": {
  "status": "HEALTHY",
  "tracked_now": "5",
  "starling_now": "5",
  "truth": "5",
  "detail": "5 identities in the shared table; 9 observations delivered."
 },
 "conflict": "conflict (ambiguous): healed 38 s",
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
    "starling_now": "6",
    "truth": "5",
    "detail": "7 identities in the shared table; 10031 observations delivered."
  },
  "partitioned": {
    "status": "PARTIAL",
    "tracked_now": "3",
    "starling_now": "5",
    "truth": "5",
    "detail": "Cameras 2, 3 cannot reach the server: their workers are lost (1351 observations never delivered)."
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
    "detail": "5 identities in the shared table; 9 observations delivered."
  },
  "starling_claims_before_kill": 3625.0,
  "starling_claims_6s_after_kill": 3852.0,
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

Claims rejected by nodes' plausibility check (logged per node; includes the deliberate liar and scripted actors): `{"dashboard": 224, "node-0": 144, "node-1": 5074, "node-2": 147, "node-3": 113}`

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
  "startup_s": 5.1,
  "heal_convergence_s": 3.5,
  "reputation_drop_s": 9.4,
  "reputation_recovery_s": 8.3,
  "dead_zone_healthy_lifetime_s": 25.5,
  "dead_zone_healthy_ratio": 0.074,
  "conflict_seconds_to_fork": {
    "resolvable": 40.5,
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
  "commit": "cab1f4d",
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

# Starling demo — automated review summary

Generated 2026-09-21 22:04:25 by `scripts/review_demo.py` (commit `c8c7850`). Same content as `review.html`, without images (file names refer to `review/screenshots/`).

## Summary

| # | Moment | Verdict | Key measured numbers | Reason |
|---|---|---|---|---|
| 0 | Startup | **PASS** | all 4 nodes live after 4.1 s | all 4 nodes live 4.1s after launch (page loaded, claims flowing) |
| 1 | Normal walk | **PASS** | mean error 0.32 m; worker-2 label ['P-003', 'P-003'] | 5 identities tracked, worker-2 kept P-003 across nodes [0, 1], mean error 0.32 m vs ground truth |
| 2 | Dead zone | **PARTIAL** | ep1: peak 84.56 m², final 84.56 m², shrank=True, same id=True; ep2: peak 116.5 m², final 116.5 m², shrank=False, same id=True; ep3: peak 86.56 m², final 86.56 m², shrank=False, same id=True | the region shrank in only 1 of 3 dark episodes (a majority is required for PASS; in the others it only grew until the worker re-emerged). ep1 (sim t=45.2 s): 9 samples, peak 84.56 m², final 84.56 m², shrank, same identity after; ep2 (sim t=63.2 s): 9 samples, peak 116.5 m², final 116.5 m², no shrink, same identity after; ep3 (sim t=81.4 s): 11 samples, peak 86.56 m², final 86.56 m², no shrink, same identity after |
| 3 | Partition and heal | **PASS** | max spread 51.0, heal→converged 2.4 s, gaps 0.0 | partition shown on all nodes, spread grew to 51.0, converged 2.4s after heal with gaps=0; open forks: 0 |
| 4 | Lying node | **PASS** | liar <0.7 after 3.6 s, rejected 48.0, recovered >0.9 after 8.1 s | liar's reputation < 0.7 after 3.6s (48.0 claims rejected), honest nodes stayed >= 1.0, recovered > 0.9 8.1s after stopping |
| 5 | Query and refusal | **PASS** | answer + 3 refusal/edge cases (see section) | valid query answered with confirmed/inferred/unreachable; unknown worker and productivity purpose refused with reasons; partition edge case gave: refused — Reason: 'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence |
| 6 | Robustness | **PASS** | reload 0.0 s; offline 5.3 s; back 2.5 s | reload recovered in 0.0s; killed node OFFLINE after 5.3s; LIVE again 2.5s after restart; converged 3.8s after restart |

## Moment 0 — Startup: PASS

**What it should demonstrate:** The dashboard loads and all four node processes are live.

**Action taken:** Launched `scripts/run_demo.py --headless` (simulator + 4 nodes + dashboard), opened the dashboard in headless Chromium.

**Verdict reason:** all 4 nodes live 4.1s after launch (page loaded, claims flowing)

### 0a_startup_loaded.jpg  (t = 5.0 s since launch)

Dashboard fully loaded with all four nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.0",
 "convergence": "CONVERGED",
 "spread": "11",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.07",
 "claims_per_node": [
  "67",
  "64",
  "59",
  "70"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 27",
  "0 of 14",
  "0 of 13",
  "0 of 13"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(3.9, 2.0) via node 0 err 0.01",
  "P-001 worker-1 seen @(16.2, 2.0) via node 1 err 0.06",
  "P-002 worker-3 seen @(28.4, 1.9) via node 2 err 0.10",
  "P-003 worker-2 seen @(6.3, 11.9) via node 0 err 0.11",
  "P-005 worker-4 seen @(38.9, 4.0) via node 3 err 0.07"
 ],
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "seconds_launch_to_all_nodes_live": 4.1
}
```

## Moment 1 — Normal walk: PASS

**What it should demonstrate:** Believed worker positions (one colour per resolved identity) move across the floor plan and keep their identity across camera zones; faint ground-truth markers give the comparison.

**Action taken:** Observed only (no controls): sampled the DOM for ~30 s and followed worker-2, which walks from node 0's zone through the blind aisle into node 1's zone.

**Verdict reason:** 5 identities tracked, worker-2 kept P-003 across nodes [0, 1], mean error 0.32 m vs ground truth

### 1a_walk_start.jpg  (t = 5.1 s since launch)

Five workers, five identities; solid dots = believed, dashed rings = ground truth.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "4.0",
 "convergence": "CONVERGED",
 "spread": "11",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.07",
 "claims_per_node": [
  "67",
  "64",
  "59",
  "70"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 27",
  "0 of 14",
  "0 of 13",
  "0 of 13"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(3.9, 2.0) via node 0 err 0.01",
  "P-001 worker-1 seen @(16.2, 2.0) via node 1 err 0.06",
  "P-002 worker-3 seen @(28.4, 1.9) via node 2 err 0.10",
  "P-003 worker-2 seen @(6.3, 11.9) via node 0 err 0.11",
  "P-005 worker-4 seen @(38.9, 4.0) via node 3 err 0.07"
 ],
 "query": {
  "status": "none"
 }
}
```

### 1b_walk_6s_later.jpg  (t = 11.2 s since launch)

Six seconds later: the same identities at new positions.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "10.0",
 "convergence": "CONVERGED",
 "spread": "5",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.18",
 "claims_per_node": [
  "196",
  "197",
  "196",
  "201"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 74",
  "0 of 47",
  "0 of 46",
  "0 of 44"
 ],
 "candidate_regions_m2": {
  "P-003": 82.94
 },
 "identities": [
  "P-004 worker-0 seen @(6.9, 3.8) via node 0 err 0.16",
  "P-001 worker-1 seen @(18.0, 5.0) via node 1 err 0.26",
  "P-002 worker-3 seen @(31.1, 3.6) via node 2 err 0.09",
  "P-003 worker-2 unseen @(7.9, 12.1) via node 0 err –",
  "P-005 worker-4 seen @(35.9, 4.8) via node 3 err 0.22"
 ],
 "query": {
  "status": "none"
 }
}
```

### 1c_zone_boundary_crossed.jpg  (t = 33.4 s since launch)

worker-2 is now seen by a different node's camera and still carries identity P-003 (was P-003).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "31.0",
 "convergence": "CONVERGED",
 "spread": "22",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.57",
 "claims_per_node": [
  "697",
  "695",
  "690",
  "675"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 178",
  "2 of 211",
  "0 of 145",
  "0 of 144"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(6.6, 23.9) via node 0 err 0.68",
  "P-001 worker-1 seen @(17.9, 21.5) via node 1 err 0.70",
  "P-002 worker-3 seen @(31.0, 19.2) via node 2 err 0.59",
  "P-003 worker-2 seen @(7.4, 12.0) via node 0 err 0.38",
  "P-005 worker-4 seen @(35.9, 3.4) via node 3 err 0.50"
 ],
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "identities_named_at_start": 5,
  "max_identity_displacement_in_6s_m": 3.5,
  "mean_position_error_m_samples": [
    0.57,
    0.48,
    0.48,
    0.63,
    0.63,
    0.49,
    0.49,
    0.58,
    0.58,
    0.57
  ],
  "mean_position_error_m_avg": 0.32,
  "worker2_label_before_after_zone_change": [
    "P-003",
    "P-003"
  ],
  "worker2_nodes_seen_by": [
    0,
    1
  ],
  "final_per_identity_error_m": [
    0.68,
    0.7,
    0.59,
    0.38,
    0.5
  ],
  "named_workers_at_end": [
    "worker-0",
    "worker-1",
    "worker-2",
    "worker-3",
    "worker-4"
  ],
  "identities_listed_at_end": 5,
  "identity_statuses_at_end": {
    "P-004": "seen",
    "P-001": "seen",
    "P-002": "seen",
    "P-003": "seen",
    "P-005": "seen"
  }
}
```

## Moment 2 — Dead zone: PARTIAL

**What it should demonstrate:** A worker walks into the blind aisle; instead of the track vanishing, a shaded 'could be here' region appears and (with attested absence) shrinks; on re-emergence the same identity is restored.

**Action taken:** Observed only: followed worker-2 through up to 3 dark episodes in the 3 m blind aisle, sampled its OWN candidate-region area from the DOM every ~0.5 s, and checked which identity it had when it reappeared. Node 1 has scripted occlusion windows (sim 20-45 s and 80-105 s) in which it sends no attestation, so episodes inside a window are expected NOT to shrink (silence is not evidence).

**Verdict reason:** the region shrank in only 1 of 3 dark episodes (a majority is required for PASS; in the others it only grew until the worker re-emerged). ep1 (sim t=45.2 s): 9 samples, peak 84.56 m², final 84.56 m², shrank, same identity after; ep2 (sim t=63.2 s): 9 samples, peak 116.5 m², final 116.5 m², no shrink, same identity after; ep3 (sim t=81.4 s): 11 samples, peak 86.56 m², final 86.56 m², no shrink, same identity after

### 2a_approaching_aisle.jpg  (t = 33.4 s since launch)

worker-2 (P-003) approaches the blind aisle and is still seen.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "31.0",
 "convergence": "CONVERGED",
 "spread": "22",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.57",
 "claims_per_node": [
  "697",
  "695",
  "690",
  "675"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 178",
  "2 of 211",
  "0 of 145",
  "0 of 144"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(6.6, 23.9) via node 0 err 0.68",
  "P-001 worker-1 seen @(17.9, 21.5) via node 1 err 0.70",
  "P-002 worker-3 seen @(31.0, 19.2) via node 2 err 0.59",
  "P-003 worker-2 seen @(7.4, 12.0) via node 0 err 0.38",
  "P-005 worker-4 seen @(35.9, 3.4) via node 3 err 0.50"
 ],
 "query": {
  "status": "none"
 }
}
```

### 2b_region_appears.jpg  (t = 47.0 s since launch)

worker-2 (P-003) is unseen: its candidate region appears with its area in m².

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "45.2",
 "convergence": "CONVERGED",
 "spread": "17",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.42",
 "claims_per_node": [
  "1024",
  "1024",
  "1025",
  "1008"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 312",
  "2 of 281",
  "0 of 213",
  "0 of 217"
 ],
 "candidate_regions_m2": {
  "P-003": 28.81
 },
 "identities": [
  "P-004 worker-0 seen @(0.9, 15.4) via node 0 err 0.62",
  "P-001 worker-1 seen @(11.8, 16.8) via node 1 err 0.39",
  "P-002 worker-3 seen @(25.9, 24.1) via node 2 err 0.33",
  "P-003 worker-2 unseen @(7.9, 12.0) via node 0 err –",
  "P-005 worker-4 seen @(36.5, 2.9) via node 3 err 0.32"
 ],
 "query": {
  "status": "none"
 }
}
```

### 2c_region_mid.jpg  (t = 49.4 s since launch)

Region P-003 after 2.4 s unseen: 35.94 m².

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "47.2",
 "convergence": "CONVERGED",
 "spread": "15",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.38",
 "claims_per_node": [
  "1064",
  "1064",
  "1064",
  "1049"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 322",
  "2 of 291",
  "0 of 223",
  "0 of 227"
 ],
 "candidate_regions_m2": {
  "P-003": 35.94
 },
 "identities": [
  "P-004 worker-0 seen @(1.0, 12.9) via node 0 err 0.52",
  "P-001 worker-1 seen @(12.1, 14.7) via node 1 err 0.47",
  "P-002 worker-3 seen @(25.0, 23.2) via node 2 err 0.18",
  "P-003 worker-2 unseen @(7.9, 12.0) via node 0 err –",
  "P-005 worker-4 seen @(38.5, 3.0) via node 3 err 0.33"
 ],
 "query": {
  "status": "none"
 }
}
```

### 2e_region_shrinks.jpg  (t = 49.5 s since launch)

Region P-003 SHRANK from 63.31 to 35.94 m² after 2.4 s unseen (sim t = 47.2 s).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "47.2",
 "convergence": "CONVERGED",
 "spread": "15",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.38",
 "claims_per_node": [
  "1064",
  "1064",
  "1064",
  "1049"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 322",
  "2 of 291",
  "0 of 223",
  "0 of 227"
 ],
 "candidate_regions_m2": {
  "P-003": 35.94
 },
 "identities": [
  "P-004 worker-0 seen @(1.0, 12.9) via node 0 err 0.52",
  "P-001 worker-1 seen @(12.1, 14.7) via node 1 err 0.47",
  "P-002 worker-3 seen @(25.0, 23.2) via node 2 err 0.18",
  "P-003 worker-2 unseen @(7.9, 12.0) via node 0 err –",
  "P-005 worker-4 seen @(38.5, 3.0) via node 3 err 0.33"
 ],
 "query": {
  "status": "none"
 }
}
```

### 2d_reemerged.jpg  (t = 51.4 s since launch)

worker-2 re-emerges; identity now P-003 (before: P-003).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "49.2",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.61",
 "claims_per_node": [
  "1110",
  "1112",
  "1111",
  "1109"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 332",
  "2 of 306",
  "0 of 233",
  "0 of 237"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(1.2, 10.5) via node 0 err 0.81",
  "P-001 worker-1 seen @(11.9, 12.4) via node 1 err 0.61",
  "P-002 worker-3 seen @(25.0, 22.6) via node 2 err 0.64",
  "P-003 worker-2 seen @(11.5, 12.0) via node 1 err 0.39",
  "P-005 worker-4 seen @(39.0, 4.4) via node 3 err 0.59"
 ],
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "episodes": [
    {
      "identity": "P-003",
      "sim_time_at_start_s": 45.2,
      "samples": [
        [
          0.1,
          28.81
        ],
        [
          0.5,
          28.81
        ],
        [
          1.0,
          63.31
        ],
        [
          1.5,
          63.31
        ],
        [
          1.9,
          63.31
        ],
        [
          2.4,
          35.94
        ],
        [
          3.0,
          84.56
        ],
        [
          3.4,
          84.56
        ],
        [
          3.9,
          84.56
        ]
      ],
      "identity_after_reemerging": "P-003",
      "same_identity_after": true,
      "n_samples": 9,
      "peak_area_m2": 84.56,
      "final_area_m2": 84.56,
      "area_ever_decreased": true
    },
    {
      "identity": "P-003",
      "sim_time_at_start_s": 63.2,
      "samples": [
        [
          0.0,
          18.31
        ],
        [
          0.5,
          18.31
        ],
        [
          0.9,
          45.94
        ],
        [
          1.4,
          45.94
        ],
        [
          1.8,
          69.06
        ],
        [
          2.3,
          69.06
        ],
        [
          2.8,
          69.06
        ],
        [
          3.2,
          116.5
        ],
        [
          3.7,
          116.5
        ]
      ],
      "identity_after_reemerging": "P-003",
      "same_identity_after": true,
      "n_samples": 9,
      "peak_area_m2": 116.5,
      "final_area_m2": 116.5,
      "area_ever_decreased": false
    },
    {
      "identity": "P-003",
      "sim_time_at_start_s": 81.4,
      "samples": [
        [
          0.0,
          18.31
        ],
        [
          0.5,
          18.31
        ],
        [
          0.9,
          47.31
        ],
        [
          1.4,
          47.31
        ],
        [
          1.9,
          47.31
        ],
        [
          2.3,
          47.31
        ],
        [
          2.8,
          47.31
        ],
        [
          3.2,
          86.56
        ],
        [
          3.7,
          86.56
        ],
        [
          4.2,
          86.56
        ],
        [
          4.7,
          86.56
        ]
      ],
      "identity_after_reemerging": "P-003",
      "same_identity_after": true,
      "n_samples": 11,
      "peak_area_m2": 86.56,
      "final_area_m2": 86.56,
      "area_ever_decreased": false
    }
  ],
  "n_episodes": 3,
  "other_identities_with_regions_at_end": []
}
```

## Moment 3 — Partition and heal: PASS

**What it should demonstrate:** Cut nodes {2,3} from {0,1}; both sides keep working; on heal the replicas reconverge (equal claim counts, no gaps); any genuine conflict shows as an open fork.

**Action taken:** Pressed 'Partition {2,3} from {0,1}', waited, pressed 'Heal', and timed how long until the convergence badge read CONVERGED.

**Verdict reason:** partition shown on all nodes, spread grew to 51.0, converged 2.4s after heal with gaps=0; open forks: 0

### 3a_before_partition.jpg  (t = 89.7 s since launch)

Before: all nodes hold (almost) the same number of claims.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "86.4",
 "convergence": "CONVERGED",
 "spread": "3",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.33",
 "claims_per_node": [
  "1956",
  "1959",
  "1956",
  "1957"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 579",
  "2 of 557",
  "0 of 406",
  "0 of 417"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.1, 23.6) via node 0 err 0.38",
  "P-001 worker-1 seen @(17.9, 19.2) via node 1 err 0.06",
  "P-002 worker-3 seen @(31.0, 4.8) via node 2 err 0.39",
  "P-003 worker-2 seen @(11.8, 12.0) via node 1 err 0.29",
  "P-005 worker-4 seen @(37.9, 2.9) via node 3 err 0.55"
 ],
 "query": {
  "status": "none"
 }
}
```

### 3b_partition_during.jpg  (t = 91.0 s since launch)

Partition applied: every node card reports 'partitioned: yes'.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "88.4",
 "convergence": "PARTITIONED",
 "spread": "4",
 "gaps": "0",
 "partition": "CUT",
 "open_forks": "0",
 "mean_error_m": "0.20",
 "claims_per_node": [
  "2003",
  "2005",
  "2003",
  "2001"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 588",
  "2 of 577",
  "0 of 416",
  "0 of 426"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(5.1, 24.0) via node 0 err 0.50",
  "P-001 worker-1 seen @(18.0, 19.9) via node 1 err 0.02",
  "P-002 worker-3 seen @(31.1, 5.2) via node 2 err 0.07",
  "P-003 worker-2 seen @(13.2, 11.9) via node 1 err 0.15",
  "P-005 worker-4 seen @(39.2, 3.1) via node 3 err 0.26"
 ],
 "query": {
  "status": "none"
 }
}
```

### 3c_partition_later.jpg  (t = 103.2 s since launch)

12 s into the partition: the two sides' claim counts have drifted apart.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "100.4",
 "convergence": "PARTITIONED",
 "spread": "50",
 "gaps": "0",
 "partition": "CUT",
 "open_forks": "0",
 "mean_error_m": "0.23",
 "claims_per_node": [
  "2168",
  "2169",
  "2119",
  "2120"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 646",
  "2 of 683",
  "0 of 473",
  "0 of 484"
 ],
 "candidate_regions_m2": {
  "P-003": 34.44
 },
 "identities": [
  "P-004 worker-0 seen @(0.9, 15.8) via node 0 err 0.11",
  "P-001 worker-1 seen @(12.0, 22.1) via node 1 err 0.68",
  "P-002 worker-3 seen @(30.9, 13.7) via node 2 err 0.08",
  "P-003 worker-2 unseen @(11.1, 11.9) via node 1 err –",
  "P-005 worker-4 seen @(37.6, 3.0) via node 3 err 0.03"
 ],
 "query": {
  "status": "none"
 }
}
```

### 3d_after_heal.jpg  (t = 106.1 s since launch)

After heal: convergence badge CONVERGED, spread 6, gaps 0 (2.4s after pressing Heal).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "103.4",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "2340",
  "2339",
  "2338",
  "2344"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 667",
  "2 of 700",
  "0 of 489",
  "0 of 501"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(1.0, 13.9) via node 0 err 0.66",
  "P-001 worker-1 seen @(12.0, 18.5) via node 1 err 0.04",
  "P-002 worker-3 seen @(31.0, 15.8) via node 2 err 0.65",
  "P-003 worker-2 seen @(7.9, 12.0) via node 0 err 0.33",
  "P-005 worker-4 seen @(39.0, 3.0) via node 3 err 0.04"
 ],
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "before": {
    "claims": [
      1956.0,
      1959.0,
      1956.0,
      1957.0
    ],
    "spread": 3.0,
    "convergence": "CONVERGED"
  },
  "partition_state_shown_on_all_4_nodes": true,
  "spread_and_claims_during_partition": [
    [
      0.0,
      4.0,
      [
        2003.0,
        2005.0,
        2003.0,
        2001.0
      ]
    ],
    [
      1.5,
      8.0,
      [
        2021.0,
        2023.0,
        2015.0,
        2017.0
      ]
    ],
    [
      3.0,
      17.0,
      [
        2051.0,
        2051.0,
        2034.0,
        2036.0
      ]
    ],
    [
      4.5,
      22.0,
      [
        2064.0,
        2066.0,
        2044.0,
        2046.0
      ]
    ],
    [
      6.1,
      34.0,
      [
        2094.0,
        2096.0,
        2062.0,
        2064.0
      ]
    ],
    [
      7.6,
      40.0,
      [
        2107.0,
        2109.0,
        2069.0,
        2071.0
      ]
    ],
    [
      9.1,
      49.0,
      [
        2136.0,
        2138.0,
        2089.0,
        2091.0
      ]
    ],
    [
      10.6,
      51.0,
      [
        2149.0,
        2150.0,
        2099.0,
        2101.0
      ]
    ]
  ],
  "max_spread_during_partition": 51.0,
  "seconds_from_heal_to_converged": 2.4,
  "after_heal_claims": [
    2340.0,
    2339.0,
    2338.0,
    2344.0
  ],
  "after_heal_gaps": 0.0,
  "open_forks_during": 0.0,
  "open_forks_after": 0,
  "claims_on_sides_pre_heal": [
    2168.0,
    2169.0,
    2119.0,
    2120.0
  ]
}
```

## Moment 4 — Lying node: PASS

**What it should demonstrate:** A node fabricates sightings; peers reject implausible claims and its reputation, as seen by peers, drops; it recovers when it stops.

**Action taken:** Selected node 2, pressed 'Make node lie', sampled reputation and rejected-claim counters every ~2 s for up to 40 s, then pressed 'Stop lying' and sampled recovery for up to 60 s.

**Verdict reason:** liar's reputation < 0.7 after 3.6s (48.0 claims rejected), honest nodes stayed >= 1.0, recovered > 0.9 8.1s after stopping

### 4a_before_lie.jpg  (t = 106.2 s since launch)

Before: reputation of all nodes = [1.0, 1.0, 1.0, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "103.4",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.34",
 "claims_per_node": [
  "2340",
  "2339",
  "2338",
  "2344"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 667",
  "2 of 700",
  "0 of 489",
  "0 of 501"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(1.0, 13.9) via node 0 err 0.66",
  "P-001 worker-1 seen @(12.0, 18.5) via node 1 err 0.04",
  "P-002 worker-3 seen @(31.0, 15.8) via node 2 err 0.65",
  "P-003 worker-2 seen @(7.9, 12.0) via node 0 err 0.33",
  "P-005 worker-4 seen @(39.0, 3.0) via node 3 err 0.04"
 ],
 "query": {
  "status": "none"
 }
}
```

### 4b_lying_early.jpg  (t = 112.1 s since launch)

5.4s after 'Make node 2 lie': reputation [1.0, 1.0, 0.6, 1.0], rejected [0.0, 2.0, 23.0, 0.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "109.4",
 "convergence": "CONVERGED",
 "spread": "12",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "2503",
  "2504",
  "2498",
  "2510"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "LYING",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.60",
  "1.00"
 ],
 "rejected": [
  "0 of 724",
  "2 of 730",
  "23 of 543",
  "0 of 527"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(1.2, 6.8) via node 0 err 0.79",
  "P-001 worker-1 seen @(12.0, 15.1) via node 1 err 0.78",
  "P-003 worker-2 seen @(4.3, 12.0) via node 0 err 0.30",
  "P-005 worker-4 seen @(36.9, 6.0) via node 3 err 0.65"
 ],
 "query": {
  "status": "none"
 }
}
```

### 4c_lying_dropped.jpg  (t = 119.4 s since launch)

Node 2's reputation has dropped: [1.0, 1.0, 0.57, 1.0], rejected [0.0, 2.0, 48.0, 0.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "116.6",
 "convergence": "CONVERGED",
 "spread": "10",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.51",
 "claims_per_node": [
  "2700",
  "2700",
  "2696",
  "2706"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "LYING",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.57",
  "1.00"
 ],
 "rejected": [
  "0 of 786",
  "2 of 761",
  "48 of 601",
  "0 of 560"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(4.8, 1.9) via node 0 err 0.64",
  "P-001 worker-1 seen @(12.1, 7.1) via node 1 err 0.52",
  "P-003 worker-2 seen @(7.9, 12.0) via node 0 err 0.30",
  "P-005 worker-4 seen @(38.9, 3.3) via node 3 err 0.56"
 ],
 "query": {
  "status": "none"
 }
}
```

### 4d_recovering.jpg  (t = 125.9 s since launch)

6.0s after 'Stop lying': reputation [1.0, 1.0, 0.83, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "122.6",
 "convergence": "CONVERGED",
 "spread": "22",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.12",
 "claims_per_node": [
  "2823",
  "2828",
  "2823",
  "2806"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.83",
  "1.00"
 ],
 "rejected": [
  "0 of 815",
  "2 of 794",
  "53 of 635",
  "0 of 587"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.0, 6.2) via node 0 err 0.04",
  "P-001 worker-1 seen @(13.5, 2.1) via node 1 err 0.13",
  "P-002 worker-3 seen @(25.1, 22.8) via node 2 err 0.40",
  "P-003 worker-2 seen @(11.6, 12.0) via node 1 err 0.03",
  "P-005 worker-4 seen @(36.0, 5.6) via node 3 err 0.02"
 ],
 "query": {
  "status": "none"
 }
}
```

### 4e_after_stop.jpg  (t = 128.0 s since launch)

End of recovery window: reputation [1.0, 1.0, 0.93, 1.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "125.6",
 "convergence": "CONVERGED",
 "spread": "24",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.10",
 "claims_per_node": [
  "2897",
  "2898",
  "2898",
  "2874"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.93",
  "1.00"
 ],
 "rejected": [
  "0 of 828",
  "2 of 824",
  "53 of 650",
  "0 of 602"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.1, 8.1) via node 0 err 0.10",
  "P-001 worker-1 seen @(16.9, 2.0) via node 1 err 0.07",
  "P-002 worker-3 seen @(24.9, 22.2) via node 2 err 0.09",
  "P-003 worker-2 seen @(13.3, 12.0) via node 1 err 0.12",
  "P-005 worker-4 seen @(36.5, 3.1) via node 3 err 0.11"
 ],
 "query": {
  "status": "none"
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
  "reputation_and_rejected_samples_while_lying": [
    {
      "t": 0.0,
      "reputation": [
        1.0,
        1.0,
        1.0,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        0.0,
        0.0
      ]
    },
    {
      "t": 1.8,
      "reputation": [
        1.0,
        1.0,
        0.88,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        3.0,
        0.0
      ]
    },
    {
      "t": 3.6,
      "reputation": [
        1.0,
        1.0,
        0.69,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        12.0,
        0.0
      ]
    },
    {
      "t": 5.4,
      "reputation": [
        1.0,
        1.0,
        0.6,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        23.0,
        0.0
      ]
    },
    {
      "t": 7.3,
      "reputation": [
        1.0,
        1.0,
        0.58,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        31.0,
        0.0
      ]
    },
    {
      "t": 9.1,
      "reputation": [
        1.0,
        1.0,
        0.59,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        35.0,
        0.0
      ]
    },
    {
      "t": 10.9,
      "reputation": [
        1.0,
        1.0,
        0.58,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        39.0,
        0.0
      ]
    },
    {
      "t": 12.7,
      "reputation": [
        1.0,
        1.0,
        0.57,
        1.0
      ],
      "rejected": [
        0.0,
        2.0,
        48.0,
        0.0
      ]
    }
  ],
  "seconds_until_liar_reputation_below_0.7": 3.6,
  "liar_rejected_claims_at_end": 48.0,
  "lowest_honest_node_reputation_while_lying": 1.0,
  "recovery_samples_after_stop": [
    {
      "t": 0.0,
      "reputation": [
        1.0,
        1.0,
        0.57,
        1.0
      ]
    },
    {
      "t": 2.0,
      "reputation": [
        1.0,
        1.0,
        0.66,
        1.0
      ]
    },
    {
      "t": 4.0,
      "reputation": [
        1.0,
        1.0,
        0.74,
        1.0
      ]
    },
    {
      "t": 6.0,
      "reputation": [
        1.0,
        1.0,
        0.83,
        1.0
      ]
    },
    {
      "t": 8.1,
      "reputation": [
        1.0,
        1.0,
        0.93,
        1.0
      ]
    }
  ],
  "seconds_until_liar_reputation_above_0.9_after_stop": 8.1
}
```

## Moment 5 — Query and refusal: PASS

**What it should demonstrate:** A text query (with a `safety` capability token) returns a structured answer that separates confirmed from inferred and names unreachable nodes; unanswerable queries are refused with a reason.

**Action taken:** Typed queries into the query box and read the rendered result from the DOM: a valid one, an unknown worker, a query during a partition, and one under a `productivity` token.

**Verdict reason:** valid query answered with confirmed/inferred/unreachable; unknown worker and productivity purpose refused with reasons; partition edge case gave: refused — Reason: 'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence

### 5a_answer_worker2.jpg  (t = 128.5 s since launch)

Valid query 'where is worker 2' (purpose safety).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "125.6",
 "convergence": "CONVERGED",
 "spread": "24",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.10",
 "claims_per_node": [
  "2897",
  "2898",
  "2898",
  "2874"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.93",
  "1.00"
 ],
 "rejected": [
  "0 of 828",
  "2 of 824",
  "53 of 650",
  "0 of 602"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.1, 8.1) via node 0 err 0.10",
  "P-001 worker-1 seen @(16.9, 2.0) via node 1 err 0.07",
  "P-002 worker-3 seen @(24.9, 22.2) via node 2 err 0.09",
  "P-003 worker-2 seen @(13.3, 12.0) via node 1 err 0.12",
  "P-005 worker-4 seen @(36.5, 3.1) via node 3 err 0.11"
 ],
 "query": {
  "status": "answered",
  "verdict": "ANSWER"
 }
}
```

### 5b_refusal_unknown.jpg  (t = 129.0 s since launch)

Unanswerable query 'where is worker 9': refused with its reason.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "126.6",
 "convergence": "CONVERGED",
 "spread": "2",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.19",
 "claims_per_node": [
  "2921",
  "2921",
  "2919",
  "2920"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.95",
  "1.00"
 ],
 "rejected": [
  "0 of 834",
  "2 of 834",
  "53 of 654",
  "0 of 608"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.0, 9.3) via node 0 err 0.27",
  "P-001 worker-1 seen @(17.8, 1.9) via node 1 err 0.28",
  "P-002 worker-3 seen @(25.1, 22.3) via node 2 err 0.15",
  "P-003 worker-2 seen @(14.1, 12.0) via node 1 err 0.04",
  "P-005 worker-4 seen @(37.5, 2.9) via node 3 err 0.19"
 ],
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5c_query_while_partitioned.jpg  (t = 133.8 s since launch)

Edge case: 'where is worker 3' while {2,3} is cut off from the querying side.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "130.2",
 "convergence": "PARTITIONED",
 "spread": "23",
 "gaps": "0",
 "partition": "CUT",
 "open_forks": "0",
 "mean_error_m": "0.33",
 "claims_per_node": [
  "2985",
  "2987",
  "2971",
  "2964"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "yes",
  "yes",
  "yes",
  "yes"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.96",
  "1.00"
 ],
 "rejected": [
  "0 of 849",
  "2 of 866",
  "53 of 671",
  "0 of 625"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.0, 13.6) via node 0 err 0.44",
  "P-001 worker-1 seen @(17.9, 4.0) via node 1 err 0.16",
  "P-002 worker-3 seen @(25.0, 20.0) via node 2 err 0.37",
  "P-003 worker-2 seen @(14.1, 12.1) via node 1 err 0.45",
  "P-005 worker-4 seen @(39.1, 5.2) via node 3 err 0.22"
 ],
 "query": {
  "status": "refused",
  "verdict": "REFUSED"
 }
}
```

### 5d_refusal_productivity.jpg  (t = 137.7 s since launch)

Same query under a `productivity` token: refused (purpose limitation).

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "134.2",
 "convergence": "CONVERGED",
 "spread": "26",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.38",
 "claims_per_node": [
  "3111",
  "3113",
  "3110",
  "3087"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.99",
  "1.00"
 ],
 "rejected": [
  "0 of 869",
  "2 of 905",
  "53 of 689",
  "0 of 645"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(6.9, 18.6) via node 0 err 0.31",
  "P-001 worker-1 seen @(18.0, 7.9) via node 1 err 0.43",
  "P-002 worker-3 seen @(25.1, 15.9) via node 2 err 0.28",
  "P-003 worker-2 seen @(11.7, 11.8) via node 1 err 0.50",
  "P-005 worker-4 seen @(38.0, 5.9) via node 3 err 0.40"
 ],
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
    "confirmed": "Confirmed: last seen at (13.3, 12.0) m by node 1, 0s ago, confidence 0.97",
    "inferred": "Inferred: currently seen — no inference needed · last position is appearance-matched, not anchored — treat as a hypothesis",
    "unreachable": "Unreachable nodes: none · 4 of 4 nodes responded",
    "text": "Subject:          P-003\nLast confirmed:   (13.3, 12.0) m, t=125.6, confidence 0.97, node 1\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCompleteness:     4 of 4 nodes responded",
    "note": "ANSWER — where is worker 2 [safety]'worker 2' → resolved identity P-003 (display mapping from the simulator's ground truth)Confirmed: last seen at (13.3, 12.0) m by node 1, 0s ago, confidence 0.97Inferred: currently seen — no inference needed · last position is appearance-matched, not anchored — treat as a hypothesisUnreachable nodes: none · 4 of 4 nodes respondedSubject:          P-003\nLast confirmed:   (13.3, 12.0) m, t=125.6, confidence 0.97, node 1\nAnchor:           none recorded\nInferred:         last position is appearance-matched, not anchored — treat as a hypothesis\nCompleteness:     4"
  },
  "unknown_worker": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: subject 'worker 9' was never enrolled — no claims found for this identity",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "subject 'worker 9' was never enrolled — no claims found for this identity",
    "note": "REFUSED — where is worker 9 [safety]Reason: subject 'worker 9' was never enrolled — no claims found for this identitysubject 'worker 9' was never enrolled — no claims found for this identity"
  },
  "during_partition": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: 'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence",
    "note": "REFUSED — where is worker 3 [safety]'worker 3' → resolved identity P-002 (display mapping from the simulator's ground truth)Reason: 'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence"
  },
  "productivity_token": {
    "status": "refused",
    "verdict": "REFUSED",
    "reason": "Reason: purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])",
    "confirmed": null,
    "inferred": null,
    "unreachable": null,
    "text": "purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])",
    "note": "REFUSED — where is worker 2 [productivity]'worker 2' → resolved identity P-003 (display mapping from the simulator's ground truth)Reason: purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])purpose 'productivity' is not authorised for querying (allowed: ['audit', 'incident', 'safety'])"
  }
}
```

## Moment 6 — Robustness: PASS

**What it should demonstrate:** The dashboard survives a page reload; a node process that actually dies is shown as OFFLINE, and shown live again when restarted.

**Action taken:** Reloaded the browser page; then hard-killed node 1's OS process (not via any dashboard control), watched the card, restarted the process, and watched it return.

**Verdict reason:** reload recovered in 0.0s; killed node OFFLINE after 5.3s; LIVE again 2.5s after restart; converged 3.8s after restart

### 6a_after_reload.jpg  (t = 137.8 s since launch)

Page reloaded mid-run; dashboard recovered in 0.0s with 4 nodes live.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "135.2",
 "convergence": "CONVERGED",
 "spread": "22",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.37",
 "claims_per_node": [
  "3133",
  "3134",
  "3133",
  "3112"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "0.99",
  "1.00"
 ],
 "rejected": [
  "0 of 874",
  "2 of 914",
  "53 of 694",
  "0 of 650"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(7.0, 19.6) via node 0 err 0.53",
  "P-001 worker-1 seen @(17.9, 8.8) via node 1 err 0.17",
  "P-002 worker-3 seen @(24.9, 14.9) via node 2 err 0.34",
  "P-003 worker-2 seen @(11.1, 12.0) via node 1 err 0.45",
  "P-005 worker-4 seen @(37.0, 6.0) via node 3 err 0.37"
 ],
 "query": {
  "status": "none"
 }
}
```

### 6b_node1_killed.jpg  (t = 143.2 s since launch)

Node 1's process was killed; its card reads OFFLINE after 5.3s; nodes live: 3.

DOM values read at capture:

```json
{
 "nodes_live": "3",
 "sim_time_s": "139.6",
 "convergence": "CONVERGED",
 "spread": "6",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.38",
 "claims_per_node": [
  "3196",
  "3134",
  "3195",
  "3201"
 ],
 "live": [
  "LIVE",
  "OFFLINE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 897",
  "2 of 917",
  "53 of 716",
  "0 of 673"
 ],
 "candidate_regions_m2": {
  "P-001": 92.19,
  "P-003": 128.5
 },
 "identities": [
  "P-004 worker-0 seen @(6.3, 24.0) via node 0 err 0.09",
  "P-001 worker-1 unseen @(18.1, 9.0) via node 1 err –",
  "P-002 worker-3 seen @(25.1, 13.1) via node 2 err 0.53",
  "P-003 worker-2 unseen @(11.1, 12.0) via node 1 err –",
  "P-005 worker-4 seen @(36.1, 3.9) via node 3 err 0.51"
 ],
 "query": {
  "status": "none"
 }
}
```

### 6c_node1_restarted.jpg  (t = 145.8 s since launch)

Node 1 restarted; card reads LIVE after 2.5s.

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "142.6",
 "convergence": "CONVERGING",
 "spread": "97",
 "gaps": "74",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.60",
 "claims_per_node": [
  "3251",
  "3160",
  "3245",
  "3257"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 925",
  "2 of 920",
  "53 of 731",
  "0 of 687"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(4.5, 23.9) via node 0 err 0.75",
  "P-001 worker-1 seen @(18.1, 13.0) via node 1 err 0.78",
  "P-002 worker-3 seen @(24.9, 10.2) via node 2 err 0.57",
  "P-003 worker-2 seen @(6.4, 11.9) via node 0 err 0.33",
  "P-005 worker-4 seen @(38.0, 3.0) via node 3 err 0.57"
 ],
 "query": {
  "status": "none"
 }
}
```

### 6d_after_recovery.jpg  (t = 147.1 s since launch)

After recovery: CONVERGED, gaps 0, claims [3277.0, 3290.0, 3270.0, 3279.0].

DOM values read at capture:

```json
{
 "nodes_live": "4",
 "sim_time_s": "143.6",
 "convergence": "CONVERGED",
 "spread": "20",
 "gaps": "0",
 "partition": "none",
 "open_forks": "0",
 "mean_error_m": "0.63",
 "claims_per_node": [
  "3277",
  "3290",
  "3270",
  "3279"
 ],
 "live": [
  "LIVE",
  "LIVE",
  "LIVE",
  "LIVE"
 ],
 "partitioned": [
  "no",
  "no",
  "no",
  "no"
 ],
 "behaviour": [
  "hones",
  "hones",
  "hones",
  "hones"
 ],
 "reputation": [
  "1.00",
  "1.00",
  "1.00",
  "1.00"
 ],
 "rejected": [
  "0 of 935",
  "2 of 925",
  "53 of 736",
  "0 of 691"
 ],
 "candidate_regions_m2": {},
 "identities": [
  "P-004 worker-0 seen @(3.3, 24.1) via node 0 err 0.76",
  "P-001 worker-1 seen @(18.0, 14.1) via node 1 err 0.80",
  "P-002 worker-3 seen @(24.9, 9.3) via node 2 err 0.70",
  "P-003 worker-2 seen @(5.8, 12.1) via node 0 err 0.31",
  "P-005 worker-4 seen @(39.0, 3.0) via node 3 err 0.57"
 ],
 "query": {
  "status": "none"
 }
}
```

Measured values:

```json
{
  "seconds_to_recover_after_reload": 0.0,
  "seconds_until_killed_node_shown_offline": 5.3,
  "other_nodes_stayed_live_while_node1_down": true,
  "seconds_until_restarted_node_live": 2.5,
  "seconds_from_restart_to_converged": 3.8
}
```

## First-run findings

Verdicts of the first, unmodified run:

| # | Moment | Verdict | Reason |
|---|---|---|---|
| 0 | Startup | PASS | all 4 nodes live 5.3s after launch (page loaded, claims flowing) |
| 1 | Normal walk | PASS | 5 identities tracked, worker-2 kept P-004 across nodes [0, 1], mean error 0.18 m vs ground truth |
| 2 | Dead zone | PARTIAL | the region never shrank (it only grew/plateaued before the worker re-emerged). Areas over time: [(0.1, 41.75), (0.8, 41.75), (1.5, 67.75), (2.2, 106.06), (3.0, 149), (3.8, 149), (4.5, 195.5), (5.2, 249.88), (5.9, 249.88), (6.6, 311.25), (7.3, 383.12), (8.1, 461.75), (8.8, 461.75), (9.5, 542.56)] |
| 3 | Partition and heal | PASS | partition shown on all nodes, spread grew to 30.0, converged 2.1s after heal with gaps=0; open forks: 0 |
| 4 | Lying node | PASS | liar's reputation < 0.7 after 3.6s (51.0 claims rejected), honest nodes stayed >= 1.0, recovered > 0.9 8.1s after stopping |
| 5 | Query and refusal | PASS | valid query answered with confirmed/inferred/unreachable; unknown worker and productivity purpose refused with reasons; partition edge case gave: refused — Reason: 'P-002' was only observed by node 2, which is/are unreachable for the entire requested window — a partitioned wing, not an absence |
| 6 | Robustness | PASS | reload recovered in 0.1s; killed node OFFLINE after 5.0s; LIVE again 2.1s after restart; converged 5.0s after restart |

The first run (commit `c141707`, before any change made in response to the review) reported six PASS and one PARTIAL. Reading its screenshots and recorded values critically, that headline was too rosy. Everything below failed or looked wrong on that run, and what was changed about it.

1. **A worker's identity was lost mid-run (real system defect, missed by my own criteria).** From about 31 s of simulated time only 4 identities were listed for 5 workers: worker-1 (`P-001`) went "unseen" at (18.0, 19.2), inside node 1's own camera zone, stayed unseen and dropped off the table (screenshots `2b`–`2d`; the identity count in the recorded DOM values is 5 at `2c` and 4 from `2d` onwards, and 3 by `4b` during the lying test). The first-run criteria for moments 1 and 3–6 did not require all five workers to still be tracked, so they were marked PASS anyway. **Cause** (found with a debug harness): the resolver's reachability gate allows `v_max*dt + 2*pos_sigma + one grid cell` = 0.73 m between claims 0.2 s apart; two noisy detections 0.53 m apart landed 3 grid cells (0.75 m) apart after 0.25 m cell quantisation, the gate failed, a 1-claim duplicate identity was spawned, and the resolver (by design) never breaks a tie on a thin margin, so every later claim of that worker was left unassigned. **Fix:** new `MatchConfig.gate_extra_slack_m` (default 0 = original behaviour, so existing experiments are unchanged; the demo sets 0.5), with a regression test that first proves the duplicate occurs without it. **Review criteria tightened:** moment 1 now requires exactly the 5 workers as 5 identities at the end.
2. **Moment 2 measured the wrong identity (harness bug).** The script sampled the first candidate region on the page, which belonged to `P-001` (worker-1, the lost identity above), not worker-2 (`P-004`). The recorded series (41.75 → 542.56 m² over 9.5 s, "never shrank") therefore says nothing about the dead-zone worker; worker-2 was still in node 0's zone on screen at that time. The PARTIAL verdict was right for the wrong reason. **Fix:** the script now selects the region belonging to worker-2's own identity label and records the label it measured.
3. **A node process could crash (real defect, not visible in the first run's exit codes).** While reproducing item 1, a node died with `Assertion failed: check () ... msg.cpp:387` (libzmq). `GossipNode.publish` sent on a single shared PUB socket from both the node's main thread and its gossip-receive thread (anti-entropy replies) without a lock; ZeroMQ sockets are not thread-safe. Node 1 died at 30 s of simulated time in one debug run and stayed alive in the first review run (it was LIVE in every screenshot), so this is an intermittent crash (very likely easier to hit since the Part A signature fix made anti-entropy digests and replies far more frequent). **Fix:** a send lock, with a regression test hammering `publish` from four threads. **Review changed:** the log scan now reports `Assertion failed` / crash lines as process errors, and any process found not running after a moment downgrades that moment's verdict.
4. **Smaller observations from the first run.** (a) The convergence badge tolerates a 30-claim spread (about one second of production), so "CONVERGED 2.1 s after heal" means gap-free and within that tolerance, not byte-identical (byte-identical sets are asserted in unit tests only). (b) Reputation of the lying node settled near 0.57 rather than approaching the floor, because it is the median of only three reporters. (c) Console-encoding artefacts (`�`) in the run log for `²`/`—` come from the Windows console, not the report; the HTML is UTF-8.

5. **Later runs (2 and 3, after the fixes above): the dead-zone region still never shrank (real defect in the dashboard's use of negative evidence).** With the right identity now measured, three consecutive dark episodes of worker-2 all grew monotonically (for example 28.7 → 59.7 → 94.7 m²). Dumping the attestations the dashboard received showed why: when the worker walks in, the nearer node attests a boundary *crossing*, and my own bookkeeping then ignored every later "nobody crossed" attestation for that boundary (to avoid ruling out the worker's true position), so nothing ever cut the region. **Fix:** after an attested crossing the identity is treated as being on the far side of that boundary, so later "nobody crossed since" attestations rule out the *origin* side instead (`CandidateBelief.apply_attestation` gained an optional `reference_xy`; unit test added). After this, shrink events appear in the samples (for instance 42.6 → 32.2 m², screenshot `2e`), but growth still dominates in most episodes because the blind aisle is 25 m long and the belief uses a conservative `v_max` of 1.6 m/s against a 0.6 m/s worker, and an occluded node (silent, correctly) cannot shrink anything. The final moment-2 verdict is therefore based on shrinking in 1 of 3 episodes, stated as such.


## Browser console errors

None (no console errors/warnings, page errors or failed requests recorded).

## Process errors and exit status

No Python tracebacks and no `level: error` log records in any process log.

Warning-level events (counts): `{"node-0": {"PARTITION_HEALED": 4, "PARTITION_DETECTED": 3}, "node-1": {"PARTITION_HEALED": 4, "PARTITION_DETECTED": 2}, "node-2": {"node_attestation_disabled": 1, "PARTITION_HEALED": 4, "PARTITION_DETECTED": 3}, "node-3": {"node_attestation_disabled": 1, "PARTITION_HEALED": 3, "PARTITION_DETECTED": 2}}`

| process | exit code | note |
|---|---|---|
| dashboard | 1 | still running at shutdown; stopped by the launcher |
| node-0 | 1 | still running at shutdown; stopped by the launcher |
| node-1 | 1 | still running at shutdown; stopped by the launcher |
| node-2 | 1 | still running at shutdown; stopped by the launcher |
| node-3 | 1 | still running at shutdown; stopped by the launcher |
| simulator | 1 | still running at shutdown; stopped by the launcher |

On Windows the launcher stops a process with `TerminateProcess`, so a nonzero exit code for a process that was running is the launcher's stop, not a crash. Node 1 was deliberately killed and restarted during moment 6.

## Timings

```json
{
  "startup_s_launch_to_all_nodes_live": 4.1,
  "heal_convergence_s": 2.4,
  "reputation_drop_s_to_below_0.7": 3.6,
  "reputation_recovery_s_to_above_0.9": 8.1,
  "region_area_samples_m2_per_episode": [
    [
      [
        0.1,
        28.81
      ],
      [
        0.5,
        28.81
      ],
      [
        1.0,
        63.31
      ],
      [
        1.5,
        63.31
      ],
      [
        1.9,
        63.31
      ],
      [
        2.4,
        35.94
      ],
      [
        3.0,
        84.56
      ],
      [
        3.4,
        84.56
      ],
      [
        3.9,
        84.56
      ]
    ],
    [
      [
        0.0,
        18.31
      ],
      [
        0.5,
        18.31
      ],
      [
        0.9,
        45.94
      ],
      [
        1.4,
        45.94
      ],
      [
        1.8,
        69.06
      ],
      [
        2.3,
        69.06
      ],
      [
        2.8,
        69.06
      ],
      [
        3.2,
        116.5
      ],
      [
        3.7,
        116.5
      ]
    ],
    [
      [
        0.0,
        18.31
      ],
      [
        0.5,
        18.31
      ],
      [
        0.9,
        47.31
      ],
      [
        1.4,
        47.31
      ],
      [
        1.9,
        47.31
      ],
      [
        2.3,
        47.31
      ],
      [
        2.8,
        47.31
      ],
      [
        3.2,
        86.56
      ],
      [
        3.7,
        86.56
      ],
      [
        4.2,
        86.56
      ],
      [
        4.7,
        86.56
      ]
    ]
  ]
}
```

## Environment

```json
{
  "os": "Windows 11 (10.0.26200)",
  "python": "3.12.1",
  "chromium": "153.0.8010.12",
  "commit": "c8c7850",
  "working_tree_dirty_outside_review_dir": false,
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

- Perception is SIMULATED. There are no cameras, no video and no detector: a simulator process moves five virtual workers on a 2D floor plan and hands each node the noisy detections (position noise 0.08 m, embedding noise, 3 % missed detections) its own camera zone would produce. The 'ground truth' markers are the simulator's own state. Identity embeddings are synthetic 64-d unit vectors, so appearance matching is far easier than with real re-ID features. Nothing here says anything about real-camera accuracy.
- The network PARTITION is application-level: the partition button tells each node to ignore inbound gossip from the other group (`POST /partition`). It is not packet loss/latency (netem) and the sending side is not gated. The dashboard's own observer is deliberately not partitioned, so it keeps hearing every node.
- The 'lying node' is the project's own `AttackInjector` (fabricated claims at random free positions, 90 % intensity), not an adaptive adversary. Reputation is an EWMA over plausibility checks; a reputation of about 0.5 is the floor reached with three reporting peers (median).
- The dashboard's 'rejected claims' counter is the DASHBOARD's own plausibility pass over what it overheard, not a count reported by each node. The label '≈ worker-N' next to an identity is display-only, matched to the nearest ground-truth worker; the network never sees worker names. 'where is worker 2' is translated through that mapping.
- The resolver is run over a sliding 45 s window (it is O(claims x identities)); identity labels (P-001...) are kept stable across windows by claim overlap. Within a window the resolution is a pure function of the merged claim set.
- The claim-count 'convergence' badge tolerates a small in-flight spread (30 claims, about a second of production) because the simulator keeps producing ~25 claims/s and digests are up to 1 s old; 'gaps' (holes in a node's own digest) must be exactly 0. Byte-identical claim sets are asserted in the unit tests, not readable from the page.
- Candidate regions only shrink through gossiped attestations of boundaries (a boundary attested 'not crossed'); the blind aisle here is short, so the dark interval is a few seconds and the region can be dominated by growth. Silence (an occluded node sends no attestation) correctly does NOT shrink it.
- Single machine, all processes on localhost; timings are for one Windows laptop and vary run to run. The video/YOLO path was not exercised at all. The baseline `apps/baseline.py` was not exercised by this review.
- Screenshots are JPEGs of the real running page (full page height, 1440 px wide); no image was edited. Verdicts are computed from the DOM values recorded at capture time by explicit criteria in `scripts/review_demo.py`.

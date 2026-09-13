# V1 Baseline Record

This document records the exact state of `multicam-reid-master` (V1) that is
preserved as the experimental control condition for every measurement in the
Starling project (see `STARLING_BUILD_STATE.md` §9).

## Tag and commit

| Field | Value |
|---|---|
| Git tag | `v1-baseline` (annotated) |
| Commit SHA | `be421d219dabee11b06cb670ad4af9008de310ea` |
| Tag message | "V1 centralized multi-camera ReID. Preserved as the experimental control condition for Starling." |

## File inventory (Python, at tag `v1-baseline`)

| Path | LOC |
|---|---:|
| `dashboard/app.py` | 684 |
| `database/identity_store.py` | 445 |
| `tracker/global_tracker.py` | 393 |
| `pipeline.py` | 157 |
| `reid/feature_extractor.py` | 104 |
| `database/__init__.py` | 1 |
| `dashboard/__init__.py` | 0 |
| `eval/__init__.py` | 0 |
| `reid/__init__.py` | 0 |
| `tracker/__init__.py` | 0 |
| `utils/__init__.py` | 0 |
| **Total** | **1,784** |

## Command that reproduces V1 behaviour today

```bash
pip install -r requirements.txt
python pipeline.py --videos cam0.mp4 cam1.mp4 --output results/
streamlit run dashboard/app.py
```

(At tag `be421d2`, before the Part 3 restructure. After the restructure, the
equivalent invocation is `python apps/baseline.py --videos cam0.mp4 cam1.mp4
--output results/`, preserving the same algorithm and CLI surface.)

## Why this exists

This is the centralized control condition referenced by
`STARLING_BUILD_STATE.md` §9 ("Things V1 does that you must consciously
keep") and used throughout §8's headline three-way experiment
(centralized baseline / Starling healthy / Starling partitioned+Byzantine).
`apps/baseline.py` must preserve this behaviour exactly — no algorithm
changes are permitted there beyond the one explicit resource fix (D-14,
crop-writing volume) called out in `STARLING_BUILD_STATE.md` WP-00 task 6.

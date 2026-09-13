# Perception baseline — Market-1501

Results of `python -m starling_eval.reid_benchmark --data <market1501_root> --backend <name>`
for each selectable `starling_perception.embedder.FeatureExtractor` backend.
Populate this table by running the benchmark against a downloaded
Market-1501 dataset (`bounding_box_test/` + `query/`) — dataset acquisition
and running the benchmark itself is outside the scope of the WP-01 session
that produced this file; only the harness is delivered here.

| Backend    | Rank-1 | Rank-5 | mAP | Dim | Notes |
|------------|--------|--------|-----|-----|-------|
| `v1_broken`| TBD    | TBD    | TBD | 512 | Original untrained head (D-01): random `Linear(576→512)+BatchNorm1d` over ImageNet features. Present only to quantify the cost of D-01. |
| `pooled`   | TBD    | TBD    | TBD | 576 | ImageNet MobileNetV3-Small features, globally pooled, L2-normalised, no trainable head. Correct but not ReID-trained. |
| `osnet`    | TBD    | TBD    | TBD | 512 | OSNet trained on Market-1501. The intended production backend. |

## Why `v1_broken` is in this table at all

Every other row in this table represents a real, if imperfect, appearance
embedding. `v1_broken` does not: its `Linear`/`BatchNorm1d` head is randomly
initialised and never trained (D-01, `STARLING_BUILD_STATE.md` §2), so its
output is a random linear projection of ImageNet features. It is included
here for exactly one reason — to turn "the embedder was broken" from an
assertion into a measured number. The `v1_broken` vs. `osnet` delta on this
table is the quantified cost of D-01, and it is the number
`apps/baseline.py` (the frozen V1 control condition, which intentionally
still uses `v1_broken`) should be compared against once real numbers exist.

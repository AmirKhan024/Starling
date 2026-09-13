# Contributing

## `apps/baseline.py` is frozen

`apps/baseline.py` is the original V1 centralized multi-camera tracking and
re-identification pipeline, preserved verbatim as the experimental control
condition for every measurement in the Starling project (see
`docs/V1_BASELINE.md`, `STARLING_BUILD_STATE.md` §9, and CLAUDE.md's
"Preserved baseline" rule). `tests/test_baseline_frozen.py` runs it twice
against a fixed synthetic input in CI and asserts both runs produce the
same result counts.

**Any change to its behaviour must be justified in the commit body.** This
means:

- You may update its imports (e.g. to use a refactored module it depends
  on) as long as the algorithm it runs is unchanged.
- You may not swap its ReID backend, change its detection/tracking
  parameters, or otherwise alter what it computes, without an explicit,
  reasoned justification in the commit message explaining why the control
  condition itself needed to change — not just "cleaned up" or
  "refactored."
- If you're unsure whether a change affects its behaviour, run
  `pytest tests/test_baseline_frozen.py -q` before and after.

## General

- Read `CLAUDE.md` and the relevant section of `STARLING_BUILD_STATE.md`
  before starting work; don't start work that isn't tracked in a work
  package there.
- `ruff check .` and `pytest -q -m "not integration"` must pass before
  committing.
- Tests requiring model weights or datasets that CI doesn't have are
  marked `@pytest.mark.integration` and must skip cleanly when the
  dependency is absent.

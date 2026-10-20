"""C2 x C4: a claim contradicted by another camera's attested absence
(starling_consensus.contradiction)."""

from __future__ import annotations

from shapely.geometry import box
from shapely.prepared import prep
from starling_consensus.contradiction import ZONE_REGION_BASE, AttestedAbsenceCheck
from starling_proto.generated import starling_pb2

ZONES = {0: prep(box(0, 0, 10, 10)), 1: prep(box(10, 0, 20, 10))}


def _att(node: int, t0: float, t1: float, conf: float) -> starling_pb2.CoverageAttestation:
    a = starling_pb2.CoverageAttestation(
        node_id=node, region_ids=[ZONE_REGION_BASE + node], attest_confidence=conf
    )
    a.t_start.physical_ms = int(t0 * 1000)
    a.t_end.physical_ms = int(t1 * 1000)
    return a


def _claim(node: int, x: float, y: float, t: float) -> dict:
    return {"claim_id": f"{node}-{t}", "node_id": node, "world_x": x, "world_y": y, "t_media": t}


def _check(atts) -> AttestedAbsenceCheck:
    return AttestedAbsenceCheck(ZONES, lambda: atts, tau_attest=0.7, radius_m=4.0, window_s=4.0)


def test_claim_in_a_neighbours_confidently_empty_zone_is_contradicted():
    c = _check([_att(1, 9.0, 11.0, 0.9)]).check(_claim(0, 15, 5, 10.0), [])
    assert c is not None and c.by_node == 1


def test_the_neighbour_seeing_the_person_too_is_no_contradiction():
    seen = [_claim(1, 15.5, 5.2, 10.5)]
    assert _check([_att(1, 9.0, 11.0, 0.9)]).check(_claim(0, 15, 5, 10.0), seen) is None


def test_silence_is_never_evidence():
    # the neighbour attested below tau (occluded), or not at all for that moment
    assert _check([_att(1, 9.0, 11.0, 0.4)]).check(_claim(0, 15, 5, 10.0), []) is None
    assert _check([_att(1, 20.0, 22.0, 0.9)]).check(_claim(0, 15, 5, 10.0), []) is None
    assert _check([]).check(_claim(0, 15, 5, 10.0), []) is None


def test_a_claim_in_the_claimants_own_zone_is_never_contradicted_by_this_check():
    assert _check([_att(0, 9.0, 11.0, 0.9)]).check(_claim(0, 5, 5, 10.0), []) is None


def test_tolerance_grows_with_stated_position_uncertainty():
    chk = AttestedAbsenceCheck(
        ZONES, lambda: [_att(1, 9.0, 11.0, 0.9)], 0.7, radius_m=2.0, window_s=4.0, sigma_k=2.0
    )
    claim = {**_claim(0, 15, 5, 10.0), "pos_sigma": 0.5}
    other = {**_claim(1, 17.8, 5.0, 10.2), "pos_sigma": 0.3}  # 2.8 m away: within 2 + 2*(0.5+0.3)
    assert chk.check(claim, [other]) is None
    assert chk.check({**claim, "pos_sigma": 0.0}, [{**other, "pos_sigma": 0.0}]) is not None


def _remote(node: int, seq: int, track: int, x: float, y: float, t: float) -> dict:
    return {
        "claim_id": f"C-{node}-{seq}",
        "node_id": node,
        "seq": seq,
        "hlc_physical_ms": int(t * 1000),
        "hlc_logical": 0,
        "local_track_id": track,
        "t_media": t,
        "embedding": b"\x00" * 16,
        "embed_scale": 1.0,
        "world_x": x,
        "world_y": y,
        "pos_sigma": 0.1,
        "anchor_type": "UNANCHORED",
        "identity_ref": None,
        "last_anchor_t": None,
        "confidence": 0.9,
        "quality": 0.9,
        "signature": None,
    }


def _loop(claims: list[dict]):
    from starling_consensus.reputation import ReputationTable
    from starling_node.config import PlausibilityConfig, ReputationConfig
    from starling_store.identity_store import LocalStore

    from apps.node import _ReputationLoop

    store = LocalStore(db_path=":memory:", node_id=9)
    store.append_remote_claims(claims)
    cfg = PlausibilityConfig(attested_absence_check=True, contradiction_settle_s=0.0)
    table = ReputationTable(node_id=9, cfg=ReputationConfig())
    atts = [_att(1, t, t + 2.0, 0.9) for t in range(0, 40, 2)]
    loop = _ReputationLoop(
        9,
        store,
        None,
        cfg,
        table,
        contradiction=AttestedAbsenceCheck(ZONES, lambda: atts, 0.7, radius_m=2.0, window_s=4.0),
    )
    loop.run_pass(100.0)
    return loop, table


def test_one_tracks_repeated_contradictions_count_once_against_reputation():
    # node 0 keeps reporting ONE person (one track) in node 1's attested-empty zone
    claims = [_remote(0, k, 7, 15.0, 5.0, 1.0 + k * 0.5) for k in range(8)]
    loop, table = _loop(claims)
    assert loop.rejected_by_node[0] == 8  # every claim is still contradicted...
    assert table.local_opinion(0) > 0.9  # ...but it is one disagreement for reputation


def test_fabricated_claims_with_fresh_tracks_each_count():
    claims = [_remote(0, k, 900_000 + k, 15.0, 5.0, 1.0 + k * 0.5) for k in range(8)]
    _, table = _loop(claims)
    assert table.local_opinion(0) < 0.7

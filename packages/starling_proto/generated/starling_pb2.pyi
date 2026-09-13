from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AnchorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UNANCHORED: _ClassVar[AnchorType]
    FACE_ANCHOR: _ClassVar[AnchorType]
    PROPAGATED: _ClassVar[AnchorType]
UNANCHORED: AnchorType
FACE_ANCHOR: AnchorType
PROPAGATED: AnchorType

class HLC(_message.Message):
    __slots__ = ("physical_ms", "logical", "node_id")
    PHYSICAL_MS_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    physical_ms: int
    logical: int
    node_id: int
    def __init__(self, physical_ms: _Optional[int] = ..., logical: _Optional[int] = ..., node_id: _Optional[int] = ...) -> None: ...

class Point2D(_message.Message):
    __slots__ = ("x", "y")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ...) -> None: ...

class IdentityClaim(_message.Message):
    __slots__ = ("claim_id", "node_id", "seq", "t_start", "t_end", "local_track_id", "embedding", "embed_scale", "world_pos", "pos_sigma", "anchor", "identity_ref", "last_anchor_t", "confidence", "quality", "signature")
    CLAIM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    T_START_FIELD_NUMBER: _ClassVar[int]
    T_END_FIELD_NUMBER: _ClassVar[int]
    LOCAL_TRACK_ID_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_FIELD_NUMBER: _ClassVar[int]
    EMBED_SCALE_FIELD_NUMBER: _ClassVar[int]
    WORLD_POS_FIELD_NUMBER: _ClassVar[int]
    POS_SIGMA_FIELD_NUMBER: _ClassVar[int]
    ANCHOR_FIELD_NUMBER: _ClassVar[int]
    IDENTITY_REF_FIELD_NUMBER: _ClassVar[int]
    LAST_ANCHOR_T_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    QUALITY_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    claim_id: bytes
    node_id: int
    seq: int
    t_start: HLC
    t_end: HLC
    local_track_id: int
    embedding: bytes
    embed_scale: float
    world_pos: Point2D
    pos_sigma: float
    anchor: AnchorType
    identity_ref: str
    last_anchor_t: HLC
    confidence: float
    quality: float
    signature: bytes
    def __init__(self, claim_id: _Optional[bytes] = ..., node_id: _Optional[int] = ..., seq: _Optional[int] = ..., t_start: _Optional[_Union[HLC, _Mapping]] = ..., t_end: _Optional[_Union[HLC, _Mapping]] = ..., local_track_id: _Optional[int] = ..., embedding: _Optional[bytes] = ..., embed_scale: _Optional[float] = ..., world_pos: _Optional[_Union[Point2D, _Mapping]] = ..., pos_sigma: _Optional[float] = ..., anchor: _Optional[_Union[AnchorType, str]] = ..., identity_ref: _Optional[str] = ..., last_anchor_t: _Optional[_Union[HLC, _Mapping]] = ..., confidence: _Optional[float] = ..., quality: _Optional[float] = ..., signature: _Optional[bytes] = ...) -> None: ...

class CoverageAttestation(_message.Message):
    __slots__ = ("node_id", "t_start", "t_end", "region_ids", "occlusion_ratio", "illumination_score", "detector_health", "crossing_observed", "attest_confidence", "signature")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    T_START_FIELD_NUMBER: _ClassVar[int]
    T_END_FIELD_NUMBER: _ClassVar[int]
    REGION_IDS_FIELD_NUMBER: _ClassVar[int]
    OCCLUSION_RATIO_FIELD_NUMBER: _ClassVar[int]
    ILLUMINATION_SCORE_FIELD_NUMBER: _ClassVar[int]
    DETECTOR_HEALTH_FIELD_NUMBER: _ClassVar[int]
    CROSSING_OBSERVED_FIELD_NUMBER: _ClassVar[int]
    ATTEST_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    node_id: int
    t_start: HLC
    t_end: HLC
    region_ids: _containers.RepeatedScalarFieldContainer[int]
    occlusion_ratio: float
    illumination_score: float
    detector_health: float
    crossing_observed: bool
    attest_confidence: float
    signature: bytes
    def __init__(self, node_id: _Optional[int] = ..., t_start: _Optional[_Union[HLC, _Mapping]] = ..., t_end: _Optional[_Union[HLC, _Mapping]] = ..., region_ids: _Optional[_Iterable[int]] = ..., occlusion_ratio: _Optional[float] = ..., illumination_score: _Optional[float] = ..., detector_health: _Optional[float] = ..., crossing_observed: bool = ..., attest_confidence: _Optional[float] = ..., signature: _Optional[bytes] = ...) -> None: ...

class ReputationUpdate(_message.Message):
    __slots__ = ("from_node", "about_node", "window_start", "window_end", "score", "evidence_claim_ids", "signature")
    FROM_NODE_FIELD_NUMBER: _ClassVar[int]
    ABOUT_NODE_FIELD_NUMBER: _ClassVar[int]
    WINDOW_START_FIELD_NUMBER: _ClassVar[int]
    WINDOW_END_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_CLAIM_IDS_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    from_node: int
    about_node: int
    window_start: HLC
    window_end: HLC
    score: float
    evidence_claim_ids: _containers.RepeatedScalarFieldContainer[bytes]
    signature: bytes
    def __init__(self, from_node: _Optional[int] = ..., about_node: _Optional[int] = ..., window_start: _Optional[_Union[HLC, _Mapping]] = ..., window_end: _Optional[_Union[HLC, _Mapping]] = ..., score: _Optional[float] = ..., evidence_claim_ids: _Optional[_Iterable[bytes]] = ..., signature: _Optional[bytes] = ...) -> None: ...

class TopologyObservation(_message.Message):
    __slots__ = ("node_a", "node_b", "transit_secs", "handoff_confidence", "signature")
    NODE_A_FIELD_NUMBER: _ClassVar[int]
    NODE_B_FIELD_NUMBER: _ClassVar[int]
    TRANSIT_SECS_FIELD_NUMBER: _ClassVar[int]
    HANDOFF_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    node_a: int
    node_b: int
    transit_secs: float
    handoff_confidence: float
    signature: bytes
    def __init__(self, node_a: _Optional[int] = ..., node_b: _Optional[int] = ..., transit_secs: _Optional[float] = ..., handoff_confidence: _Optional[float] = ..., signature: _Optional[bytes] = ...) -> None: ...

class Envelope(_message.Message):
    __slots__ = ("msg_id", "sender_node_id", "sent_hlc", "claim", "attestation", "reputation", "topology")
    MSG_ID_FIELD_NUMBER: _ClassVar[int]
    SENDER_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SENT_HLC_FIELD_NUMBER: _ClassVar[int]
    CLAIM_FIELD_NUMBER: _ClassVar[int]
    ATTESTATION_FIELD_NUMBER: _ClassVar[int]
    REPUTATION_FIELD_NUMBER: _ClassVar[int]
    TOPOLOGY_FIELD_NUMBER: _ClassVar[int]
    msg_id: bytes
    sender_node_id: int
    sent_hlc: HLC
    claim: IdentityClaim
    attestation: CoverageAttestation
    reputation: ReputationUpdate
    topology: TopologyObservation
    def __init__(self, msg_id: _Optional[bytes] = ..., sender_node_id: _Optional[int] = ..., sent_hlc: _Optional[_Union[HLC, _Mapping]] = ..., claim: _Optional[_Union[IdentityClaim, _Mapping]] = ..., attestation: _Optional[_Union[CoverageAttestation, _Mapping]] = ..., reputation: _Optional[_Union[ReputationUpdate, _Mapping]] = ..., topology: _Optional[_Union[TopologyObservation, _Mapping]] = ...) -> None: ...

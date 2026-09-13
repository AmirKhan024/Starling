"""
database/identity_store.py
--------------------------
SQLite-backed per-node identity store.

This module now serves two roles from one class (`LocalStore`, renamed
from `IdentityStore` — WP-03):

1. The V1-compatible `persons` / `sightings` / `events` API
   (`match_or_create`, `promote_lost`, `search_by_time`, `get_person`,
   `resolve`, `reactivate`, `add_note`, ...), used ONLY by the frozen
   `apps/baseline.py` control condition and its companion
   `apps/dashboard/app.py`, via the `IdentityStore` alias at the bottom of
   this file. This is genuinely centralized cross-camera matching against
   one shared database — that's correct for baseline, since it IS the
   centralized control condition (CLAUDE.md: never change its behaviour).

2. The new node-local `claims` API (`append_local_observation`,
   `local_observations`, `recent_tracks`) used by the decentralized
   `apps/node.py` path. This does NO cross-camera matching at all — it
   just appends the raw claim this node observed. Cross-node identity
   resolution lives in `starling_crdt` (a later work package), operating
   over the *merged* claim sets from every node's replica, never inside a
   single node's own store. `apps/node.py` never calls `match_or_create`.

Ambiguous-choice note (CLAUDE.md: take the first option, comment, continue):
the WP-03 prompt describes `LocalStore` as if it were a strictly reduced
API, but also says "keep IdentityStore as a thin alias" — those two
instructions are in tension once you note `apps/baseline.py` needs the full
V1 method set. Resolved here by keeping ONE class with both APIs, and
enforcing the *behavioural* separation (no cross-node matching on the node
path) by construction: `apps/node.py` simply never calls the persons-table
methods. `tests/test_no_coordinator.py` guards this from regressing.

All embedding comparisons use cosine similarity.

D-03 fix (STARLING_BUILD_STATE.md §2 / CLAUDE.md: "No wall-clock reads
(time.time()) anywhere in the identity path"): every method that writes or
evaluates a *sighting/claim* timestamp now takes that time as an explicit
parameter from the caller instead of reading `time.time()` internally. The
node path (Prompt 3 / apps/node.py) passes real media time; the frozen
`apps/baseline.py` control condition passes `time.time()` explicitly at its
own call sites, which is behaviourally identical to the old internal call.
The one deliberate exception is operator actions (`resolve`, `reactivate`,
`add_note`) — those log a human decision made *now*, not an observation of
the world, so they keep `time.time()`. Do not "fix" that; it's correct.

D-07 fix: global/claim identifiers are ULIDs generated locally (via
`python-ulid`), never derived from `SELECT COUNT(*)` — that collides the
moment two processes insert concurrently, which decentralization makes the
normal case.
"""

from __future__ import annotations

import json
import sqlite3
import time
import threading
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from ulid import ULID

from starling_net.hlc import HLCClock


# ── helpers ────────────────────────────────────────────────────────────────────

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]; returns 0.0 on zero-norm vectors."""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _emb_to_blob(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def _blob_to_emb(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _next_global_id() -> str:
    """D-07: a locally-generated ULID, never a COUNT(*)-derived counter —
    the latter collides the instant two processes insert concurrently.
    """
    return f"GID-{ULID()}"


# ── schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS persons (
    global_id       TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'active',   -- active | lost | resolved
    embedding       BLOB NOT NULL,                    -- mean embedding (float32)
    first_seen_at   REAL NOT NULL,
    last_seen_at    REAL NOT NULL,
    last_camera_id  INTEGER,
    best_crop_path  TEXT,
    notes           TEXT,
    resolved_at     REAL
);

CREATE TABLE IF NOT EXISTS sightings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    global_id   TEXT NOT NULL REFERENCES persons(global_id),
    camera_id   INTEGER NOT NULL,
    frame_idx   INTEGER NOT NULL,
    seen_at     REAL NOT NULL,
    bbox        TEXT,           -- JSON [x1,y1,x2,y2]
    conf        REAL,
    crop_path   TEXT,
    embedding   BLOB
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    global_id   TEXT NOT NULL REFERENCES persons(global_id),
    event_type  TEXT NOT NULL,  -- first_seen | lost | reappeared | resolved | reactivated | note
    occurred_at REAL NOT NULL,
    camera_id   INTEGER,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sightings_gid  ON sightings(global_id);
CREATE INDEX IF NOT EXISTS idx_sightings_time ON sightings(seen_at);
CREATE INDEX IF NOT EXISTS idx_events_gid     ON events(global_id);
CREATE INDEX IF NOT EXISTS idx_events_time    ON events(occurred_at);

-- ── Node-local claims (WP-03 / STARLING_BUILD_STATE.md §5.1 IdentityClaim) ──
-- One row per observation this node made. Never cross-camera-matched here —
-- that is starling_crdt's job, over the union of every node's claims.
CREATE TABLE IF NOT EXISTS claims (
    claim_id        TEXT PRIMARY KEY,             -- ULID, generated locally
    node_id         INTEGER NOT NULL,
    seq             INTEGER NOT NULL,              -- per-node monotonic, persisted
    hlc_physical_ms INTEGER NOT NULL,
    hlc_logical     INTEGER NOT NULL,
    local_track_id  INTEGER NOT NULL,              -- NODE-SCOPED ONLY (CLAUDE.md rule 5):
                                                    -- never interpreted by another node
    t_media         REAL NOT NULL,                 -- seconds; kept alongside hlc_physical_ms
                                                    -- for convenient time-range queries
    embedding       BLOB NOT NULL,
    embed_scale     REAL NOT NULL DEFAULT 1.0,      -- placeholder: no int8 wire quantization yet
    world_x         REAL,                           -- nullable: filled by geometry (WP-05)
    world_y         REAL,
    pos_sigma       REAL,
    anchor_type     TEXT NOT NULL DEFAULT 'UNANCHORED',  -- FACE_ANCHOR | PROPAGATED | UNANCHORED
    identity_ref    TEXT,                           -- set only when anchor_type=FACE_ANCHOR
    last_anchor_t   REAL,
    confidence      REAL NOT NULL,
    quality         REAL NOT NULL,
    signature       BLOB                            -- placeholder: no signing until gossip (Prompt 4)
);

CREATE INDEX IF NOT EXISTS idx_claims_seq     ON claims(node_id, seq);
CREATE INDEX IF NOT EXISTS idx_claims_t_media ON claims(t_media);

CREATE TABLE IF NOT EXISTS node_meta (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


# ── LocalStore ─────────────────────────────────────────────────────────────────

class LocalStore:
    """
    Thread-safe, per-process SQLite store. See the module docstring for the
    two APIs this one class serves (V1-compatible persons/sightings/events
    for `apps/baseline.py` via the `IdentityStore` alias; node-local claims
    for `apps/node.py`).

    Parameters
    ----------
    db_path             : path to the SQLite file (created if absent)
    lost_threshold_secs : seconds of absence before marking a person LOST
                          (persons-table API only)
    similarity_threshold: cosine-similarity cutoff for matching (0–1)
                          (persons-table API only)
    ema_alpha           : blend weight for the running embedding average,
                           `emb = (1 - ema_alpha) * old + ema_alpha * new`
                           (D-06 fix: was hardcoded 0.9/0.1 in code while the
                           README claimed 0.7/0.3; now a single documented
                           config value, default 0.10, matching MatchConfig)
                           (persons-table API only)
    node_id             : this node's id (claims API only; default 0 so the
                           persons-table API's callers, which don't care
                           about node identity, need not pass it)
    """

    def __init__(
        self,
        db_path: str = "database/identities.db",
        lost_threshold_secs: float = 120.0,
        similarity_threshold: float = 0.60,
        ema_alpha: float = 0.10,
        node_id: int = 0,
    ) -> None:
        self.db_path = db_path
        self.lost_threshold = lost_threshold_secs
        self.sim_threshold = similarity_threshold
        self.ema_alpha = ema_alpha
        self.node_id = node_id
        self._lock = threading.Lock()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        self._hlc_clock = HLCClock(node_id=node_id)
        self._next_seq = self._recover_seq()

    def _recover_seq(self) -> int:
        """D-07: the per-node claim sequence counter is persisted in the DB
        (`node_meta`), so it survives a process restart instead of risking
        reuse/collision.
        """
        row = self._conn.execute(
            "SELECT value FROM node_meta WHERE key='next_seq'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO node_meta (key, value) VALUES ('next_seq', 0)"
            )
            self._conn.commit()
            return 0
        return row["value"]

    def _allocate_seq(self) -> int:
        """Caller must hold self._lock."""
        seq = self._next_seq
        self._next_seq += 1
        self._conn.execute(
            "UPDATE node_meta SET value=? WHERE key='next_seq'", (self._next_seq,)
        )
        return seq

    def close(self) -> None:
        """Flush and close the underlying SQLite connection."""
        with self._lock:
            self._conn.commit()
            self._conn.close()

    # ── Core matching (persons-table API — apps/baseline.py only) ──────────────

    def match_or_create(
        self,
        embedding: np.ndarray,
        camera_id: int,
        frame_idx: int,
        bbox: list,
        conf: float,
        t: float,
        crop_path: Optional[str] = None,
    ) -> Tuple[str, bool, bool]:
        """
        Find the best matching identity or create a new one.

        Parameters
        ----------
        t : the time this sighting depicts (D-03: media time for the node
            path; `apps/baseline.py` passes `time.time()` explicitly at its
            call site, preserving its original wall-clock behaviour).

        Returns
        -------
        (global_id, is_new, was_lost)
        """
        emb = np.array(embedding, dtype=np.float32)
        now = t

        with self._lock:
            # D-02 fix: 'resolved' persons are excluded from matching — a
            # resolved case is closed and must not silently reabsorb a new
            # sighting, contradicting the README's documented behaviour.
            rows = self._conn.execute(
                "SELECT global_id, embedding, status FROM persons WHERE status != 'resolved'"
            ).fetchall()

            best_gid: Optional[str] = None
            best_sim: float = -1.0
            best_status: str = "active"

            for row in rows:
                stored_emb = _blob_to_emb(row["embedding"])
                sim = _cosine_sim(emb, stored_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_gid = row["global_id"]
                    best_status = row["status"]

            is_new = False
            was_lost = False

            if best_gid is None or best_sim < self.sim_threshold:
                # ── Create new identity ────────────────────────────────────
                global_id = _next_global_id()
                self._conn.execute(
                    """INSERT INTO persons
                       (global_id, status, embedding, first_seen_at,
                        last_seen_at, last_camera_id, best_crop_path)
                       VALUES (?,?,?,?,?,?,?)""",
                    (global_id, "active", _emb_to_blob(emb),
                     now, now, camera_id, crop_path),
                )
                self._log_event(global_id, "first_seen", camera_id,
                                f"Conf={conf:.2f}", t=now)
                is_new = True
            else:
                global_id = best_gid
                was_lost = (best_status == "lost")

                # D-06 fix: EMA blend weight comes from config (ema_alpha,
                # default 0.10) instead of a hardcoded 0.9/0.1 split, and the
                # blended vector is re-normalised before storing — previously
                # it was stored raw, so the stored "embedding" slowly drifted
                # off the unit sphere while _cosine_sim silently compensated.
                old_emb = _blob_to_emb(
                    self._conn.execute(
                        "SELECT embedding FROM persons WHERE global_id=?",
                        (global_id,)
                    ).fetchone()["embedding"]
                )
                updated_emb = (1 - self.ema_alpha) * old_emb + self.ema_alpha * emb
                norm = np.linalg.norm(updated_emb)
                if norm > 1e-9:
                    updated_emb = updated_emb / norm

                self._conn.execute(
                    """UPDATE persons
                       SET embedding=?, last_seen_at=?, last_camera_id=?,
                           best_crop_path=COALESCE(?,best_crop_path),
                           status='active'
                       WHERE global_id=?""",
                    (_emb_to_blob(updated_emb), now, camera_id,
                     crop_path, global_id),
                )

                if was_lost:
                    self._log_event(global_id, "reappeared", camera_id,
                                    f"Conf={conf:.2f}  sim={best_sim:.3f}", t=now)

            # ── Write sighting ─────────────────────────────────────────────
            self._conn.execute(
                """INSERT INTO sightings
                   (global_id, camera_id, frame_idx, seen_at,
                    bbox, conf, crop_path, embedding)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (global_id, camera_id, frame_idx, now,
                 json.dumps(bbox), conf, crop_path, _emb_to_blob(emb)),
            )
            self._conn.commit()

        return global_id, is_new, was_lost

    # ── Lost promotion ─────────────────────────────────────────────────────────

    def promote_lost(self, now: float) -> List[str]:
        """
        Mark as LOST any active person not seen within lost_threshold seconds
        of `now` (D-03: caller-supplied time, not an internal wall-clock read).
        Returns list of newly-promoted global_ids.
        """
        cutoff = now - self.lost_threshold
        promoted: List[str] = []

        with self._lock:
            rows = self._conn.execute(
                """SELECT global_id, last_camera_id
                   FROM persons
                   WHERE status='active' AND last_seen_at < ?""",
                (cutoff,),
            ).fetchall()

            for row in rows:
                gid = row["global_id"]
                self._conn.execute(
                    "UPDATE persons SET status='lost' WHERE global_id=?",
                    (gid,),
                )
                self._log_event(gid, "lost", row["last_camera_id"],
                                "Auto-promoted by lost threshold", t=now)
                promoted.append(gid)

            if promoted:
                self._conn.commit()

        return promoted

    # ── Operator actions ───────────────────────────────────────────────────────

    def resolve(self, global_id: str, note: str = "") -> None:
        """Mark a person as resolved (found / case closed).

        Operator action, not an observation — wall-clock is correct here
        (D-03's exception; see module docstring).
        """
        operator_now = time.time()
        with self._lock:
            self._conn.execute(
                """UPDATE persons
                   SET status='resolved', resolved_at=?,
                       notes=COALESCE(NULLIF(?,''), notes)
                   WHERE global_id=?""",
                (operator_now, note, global_id),
            )
            self._log_event(global_id, "resolved", None, note, t=operator_now)
            self._conn.commit()

    def reactivate(self, global_id: str) -> None:
        """Re-mark a person as active (undo a lost/resolved marking).

        Operator action, not an observation — wall-clock is correct here
        (D-03's exception; see module docstring).
        """
        operator_now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE persons SET status='active', resolved_at=NULL WHERE global_id=?",
                (global_id,),
            )
            self._log_event(global_id, "reactivated", None,
                            "Manually reactivated via dashboard", t=operator_now)
            self._conn.commit()

    def add_note(self, global_id: str, note: str) -> None:
        """Append an operator note.

        Operator action, not an observation — wall-clock is correct here
        (D-03's exception; see module docstring).
        """
        operator_now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE persons SET notes=? WHERE global_id=?",
                (note, global_id),
            )
            self._log_event(global_id, "note", None, note, t=operator_now)
            self._conn.commit()

    # ── Queries ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """Return aggregate counts (both APIs: persons-table + claims)."""
        with self._lock:
            active    = self._conn.execute(
                "SELECT COUNT(*) FROM persons WHERE status='active'"
            ).fetchone()[0]
            lost      = self._conn.execute(
                "SELECT COUNT(*) FROM persons WHERE status='lost'"
            ).fetchone()[0]
            resolved  = self._conn.execute(
                "SELECT COUNT(*) FROM persons WHERE status='resolved'"
            ).fetchone()[0]
            sightings = self._conn.execute(
                "SELECT COUNT(*) FROM sightings"
            ).fetchone()[0]
            reappear  = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='reappeared'"
            ).fetchone()[0]
            claims    = self._conn.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
        return {
            "active":        active,
            "lost":          lost,
            "resolved":      resolved,
            "sightings":     sightings,
            "reappearances": reappear,
            "claims":        claims,
        }

    # ── Node-local claims (claims API — apps/node.py only) ──────────────────────

    def append_local_observation(self, obs) -> str:
        """Append one `starling_perception.pipeline.Observation` as a claim
        in this node's own `claims` table. Does NO cross-camera identity
        matching whatsoever — that is the entire point of the node path
        (STARLING_BUILD_STATE.md §4.2: replicate the evidence, derive the
        decision — the deriving happens in starling_crdt, not here).

        Returns the new claim's id.
        """
        claim_id = str(ULID())
        physical_ms = int(obs.t_media * 1000)
        hlc = self._hlc_clock.now(physical_ms)

        with self._lock:
            seq = self._allocate_seq()
            self._conn.execute(
                """INSERT INTO claims
                   (claim_id, node_id, seq, hlc_physical_ms, hlc_logical,
                    local_track_id, t_media, embedding, embed_scale,
                    world_x, world_y, pos_sigma, anchor_type, identity_ref,
                    last_anchor_t, confidence, quality, signature)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    claim_id, self.node_id, seq, hlc.physical_ms, hlc.logical,
                    int(obs.local_track_id), float(obs.t_media),
                    _emb_to_blob(obs.embedding), 1.0,
                    None, None, None, "UNANCHORED", None,
                    None, float(obs.conf), float(obs.quality), None,
                ),
            )
            self._conn.commit()
        return claim_id

    def local_observations(self, since: float, until: float) -> List[Dict[str, Any]]:
        """Claims this node made with `t_media` in `[since, until]`, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM claims WHERE t_media BETWEEN ? AND ? ORDER BY t_media ASC",
                (since, until),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_tracks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recently-appended claims (one row per observation, not
        deduplicated by local_track_id) — a lightweight "what has this node
        seen lately" view.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM claims ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Queries (persons-table API — apps/baseline.py / dashboard only) ─────────

    def get_all(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all persons, optionally filtered by status."""
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM persons WHERE status=? ORDER BY last_seen_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM persons ORDER BY last_seen_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def get_person(self, global_id: str) -> Optional[Dict[str, Any]]:
        """Return a single person dict with embedded sightings and events."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM persons WHERE global_id=?", (global_id,)
            ).fetchone()
            if row is None:
                return None
            person = dict(row)

            sightings = self._conn.execute(
                """SELECT id, camera_id, frame_idx, seen_at,
                          bbox, conf, crop_path
                   FROM sightings WHERE global_id=?
                   ORDER BY seen_at DESC""",
                (global_id,),
            ).fetchall()
            person["sightings"] = [dict(s) for s in sightings]

            events = self._conn.execute(
                """SELECT id, event_type, occurred_at, camera_id, detail
                   FROM events WHERE global_id=?
                   ORDER BY occurred_at ASC""",
                (global_id,),
            ).fetchall()
            person["events"] = [dict(e) for e in events]

        return person

    def get_events(self, global_id: str) -> List[Dict[str, Any]]:
        """Return all events for a person, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, event_type, occurred_at, camera_id, detail
                   FROM events WHERE global_id=?
                   ORDER BY occurred_at ASC""",
                (global_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_sightings(self, global_id: str) -> List[Dict[str, Any]]:
        """Return all sightings for a person, newest first."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, camera_id, frame_idx, seen_at,
                          bbox, conf, crop_path
                   FROM sightings WHERE global_id=?
                   ORDER BY seen_at DESC""",
                (global_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_reappearances(
        self, now: float, since_seconds: float = 600
    ) -> List[Dict[str, Any]]:
        """
        Return persons that have a 'reappeared' event in the last
        `since_seconds` seconds before `now` (D-03: caller-supplied,
        typically the dashboard's own `time.time()` at render time — that's
        an operator query, not an observation, but the identity-store
        internals still never read the wall clock themselves).
        """
        since = now - since_seconds
        with self._lock:
            rows = self._conn.execute(
                """SELECT e.global_id, e.camera_id, e.occurred_at, e.detail,
                          p.best_crop_path
                   FROM events e
                   JOIN persons p ON p.global_id = e.global_id
                   WHERE e.event_type='reappeared' AND e.occurred_at >= ?
                   ORDER BY e.occurred_at DESC""",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_by_time(
        self,
        since: float,
        until: float,
        camera_id: Optional[int] = None,
    ) -> List[Optional[Dict[str, Any]]]:
        """
        Return persons that had at least one sighting in [since, until].
        Optionally filter by camera_id.

        `until` is required (D-03): callers supply the current time
        explicitly rather than this method defaulting to a wall-clock read.
        """
        with self._lock:
            if camera_id is not None:
                rows = self._conn.execute(
                    """SELECT DISTINCT global_id FROM sightings
                       WHERE seen_at BETWEEN ? AND ? AND camera_id=?""",
                    (since, until, camera_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT DISTINCT global_id FROM sightings
                       WHERE seen_at BETWEEN ? AND ?""",
                    (since, until),
                ).fetchall()

        return [self.get_person(r["global_id"]) for r in rows]

    # ── Internal ───────────────────────────────────────────────────────────────

    def _log_event(
        self,
        global_id: str,
        event_type: str,
        camera_id: Optional[int],
        detail: str = "",
        *,
        t: float,
    ) -> None:
        """Insert an event row. Caller must hold self._lock and commit.

        `t` (D-03): every caller supplies the relevant time explicitly —
        observation time for identity-path events, `time.time()` for
        operator actions — this helper never reads the wall clock itself.
        """
        self._conn.execute(
            """INSERT INTO events (global_id, event_type, occurred_at, camera_id, detail)
               VALUES (?,?,?,?,?)""",
            (global_id, event_type, t, camera_id, detail),
        )


# `apps/baseline.py` (and its companion `apps/dashboard/app.py`) are the only
# sanctioned callers of the persons-table API above (match_or_create,
# promote_lost, search_by_time, resolve, ...) — kept under this name so
# their imports need no change. The decentralized node path (`apps/node.py`)
# imports `LocalStore` directly and uses ONLY append_local_observation /
# local_observations / recent_tracks / stats; it never imports
# `IdentityStore` or calls `match_or_create` (STARLING_BUILD_STATE.md §4.1:
# no cross-camera matching happens on the node path — that's starling_crdt's
# job, a later work package). tests/test_no_coordinator.py guards this.
IdentityStore = LocalStore

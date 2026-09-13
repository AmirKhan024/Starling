"""
database/identity_store.py
--------------------------
SQLite-backed identity store for multi-camera re-identification.

Tables
------
  persons   – one row per unique global identity (global_id, status, embeddings …)
  sightings – every frame-level detection linked to a person
  events    – lifecycle log (first_seen, lost, reappeared, resolved, …)

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
"""

from __future__ import annotations

import json
import sqlite3
import time
import threading
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any


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


def _next_global_id(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COUNT(*) FROM persons")
    n = cur.fetchone()[0]
    return f"GID-{n + 1:04d}"


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
"""


# ── IdentityStore ──────────────────────────────────────────────────────────────

class IdentityStore:
    """
    Thread-safe SQLite store for global person identities.

    Parameters
    ----------
    db_path             : path to the SQLite file (created if absent)
    lost_threshold_secs : seconds of absence before marking a person LOST
    similarity_threshold: cosine-similarity cutoff for matching (0–1)
    ema_alpha           : blend weight for the running embedding average,
                           `emb = (1 - ema_alpha) * old + ema_alpha * new`
                           (D-06 fix: was hardcoded 0.9/0.1 in code while the
                           README claimed 0.7/0.3; now a single documented
                           config value, default 0.10, matching MatchConfig)
    """

    def __init__(
        self,
        db_path: str = "database/identities.db",
        lost_threshold_secs: float = 120.0,
        similarity_threshold: float = 0.60,
        ema_alpha: float = 0.10,
    ) -> None:
        self.db_path = db_path
        self.lost_threshold = lost_threshold_secs
        self.sim_threshold = similarity_threshold
        self.ema_alpha = ema_alpha
        self._lock = threading.Lock()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── Core matching ──────────────────────────────────────────────────────────

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
                global_id = _next_global_id(self._conn)
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
        """Return aggregate counts."""
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
        return {
            "active":        active,
            "lost":          lost,
            "resolved":      resolved,
            "sightings":     sightings,
            "reappearances": reappear,
        }

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

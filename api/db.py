"""SQLite catalogue behind a small Repository interface (#18; PostgreSQL in #19)."""
import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from . import ids, listen_events
from .auth import new_token, session_key
from .dblock import synchronized
from .migrations import (
    DEFAULT_APPLICATION_NAME,
    DEFAULT_ENVIRONMENT,
    DEFAULT_SPACE_NAME,
    apply_migrations,
)
from .object_query import build_object_where, order_clause
from .transfer import (
    TRANSFER_RECORD_STATUSES,
    build_transfer_where,
    sanitize_transfer_error,
)

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def _as_dict(row):
    return dict(row) if row is not None else None


@synchronized
class Repository:
    dialect = "sqlite"

    def __init__(self, path: str):
        self.path = path
        # One connection is shared by every request thread (FastAPI runs sync
        # endpoints in a threadpool). `_lock` serializes access; see api/dblock.py.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        apply_migrations(self.conn, "sqlite")

    def now(self) -> int:
        return int(time.time())

    def new_id(self) -> str:
        return ids.new_id()

    # -- users ------------------------------------------------------------
    def get_user_by_name(self, username: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def get_user(self, uid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    def get_user_by_oauth(self, provider: str, subject: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM users WHERE oauth_provider = ? AND oauth_sub = ?",
            (provider, subject),
        ).fetchone()

    def get_public_user_by_email(self, email: str) -> Optional[sqlite3.Row]:
        """The oldest public-portal account using this (lower-cased) address."""
        return self.conn.execute(
            "SELECT * FROM users WHERE role = 'public' AND lower(email) = ? "
            "ORDER BY created_at LIMIT 1", (email.lower(),),
        ).fetchone()

    # -- e-mail sign-in links ---------------------------------------------
    def create_login_link(self, token_hash: str, email: str, now: int, expires_at: int) -> None:
        self.conn.execute("DELETE FROM login_links WHERE expires_at < ?", (now - 86400,))
        self.conn.execute(
            "INSERT INTO login_links (token_hash, email, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)", (token_hash, email, now, expires_at),
        )
        self.conn.commit()

    def peek_login_link(self, token_hash: str, now: int) -> bool:
        """Whether the link exists, is unused and not expired (nothing is consumed)."""
        return self.conn.execute(
            "SELECT 1 FROM login_links WHERE token_hash = ? AND used_at IS NULL "
            "AND expires_at > ?", (token_hash, now),
        ).fetchone() is not None

    def consume_login_link(self, token_hash: str, now: int) -> Optional[str]:
        """Use a link once: returns its e-mail, or None if unknown, used or expired."""
        cur = self.conn.execute(
            "UPDATE login_links SET used_at = ? WHERE token_hash = ? "
            "AND used_at IS NULL AND expires_at > ?", (now, token_hash, now),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            return None
        row = self.conn.execute(
            "SELECT email FROM login_links WHERE token_hash = ?", (token_hash,),
        ).fetchone()
        return row["email"] if row else None

    def create_oauth_user(
        self, username: str, pass_hash: str, provider: str, subject: str,
        email: str, role: str = "public", plan: str = "free",
    ) -> str:
        """Create a public-portal user from a verified OAuth identity.

        ``pass_hash`` is an argon2 hash of a random secret: the account has no
        usable password and can only be entered through the OAuth callback.
        The role defaults to ``public``, which carries no object capability.
        ``plan`` is a product label ("free" or "premium"), never a capability:
        authorization is always checked separately from the public session.
        """
        uid = self.new_id()
        application_id, space_id = self.default_scope()
        self.conn.execute(
            "INSERT INTO users (id, username, pass_hash, created_at, role, "
            "application_id, space_id, oauth_provider, oauth_sub, email, plan) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, username, pass_hash, self.now(), role, application_id,
             space_id, provider, subject, email, plan),
        )
        self.conn.commit()
        return uid

    def set_user_plan(self, uid: str, plan: str) -> None:
        """Set the product plan of a public account. Never called on downgrade."""
        self.conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, uid))
        self.conn.commit()

    def create_user(
        self, username: str, pass_hash: str, role: str = "user",
        space_id: Optional[str] = None, application_id: Optional[str] = None,
    ) -> str:
        uid = self.new_id()
        application_id, space_id = self.default_scope(application_id, space_id)
        self.conn.execute(
            "INSERT INTO users (id, username, pass_hash, created_at, role, "
            "application_id, space_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, username, pass_hash, self.now(), role, application_id, space_id),
        )
        self.conn.commit()
        return uid

    def ensure_admin(self, uid: str) -> None:
        application_id, space_id = self.default_scope()
        self.conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (uid,))
        self.conn.execute(
            "UPDATE users SET application_id = ? WHERE id = ? AND application_id IS NULL",
            (application_id, uid),
        )
        self.conn.execute(
            "UPDATE users SET space_id = ? WHERE id = ? AND space_id IS NULL",
            (space_id, uid),
        )

    def update_user_display_name(self, uid: str, display_name: str) -> None:
        self.conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            (display_name, uid),
        )
        self.conn.commit()

    def delete_public_account(self, uid: str) -> None:
        """Delete a public portal account and its portal-owned data."""
        # Events stay append-only for aggregate history but are anonymised:
        # no event can be linked back to the deleted visitor (#320).
        self.conn.execute(
            "UPDATE listen_events SET user_id = NULL, anonymized_at = ? WHERE user_id = ?",
            (int(time.time()), uid),
        )
        self.conn.execute("DELETE FROM listen_progress WHERE user_id = ?", (uid,))
        self.conn.execute("DELETE FROM listen_favorites WHERE user_id = ?", (uid,))
        self.conn.execute("DELETE FROM listen_bookmarks WHERE user_id = ?", (uid,))
        self.conn.execute(
            "DELETE FROM listen_playlist_items WHERE playlist_id IN "
            "(SELECT id FROM listen_playlists WHERE user_id = ?)", (uid,)
        )
        self.conn.execute("DELETE FROM listen_playlists WHERE user_id = ?", (uid,))
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        self.conn.execute(
            "DELETE FROM users WHERE id = ? AND role = 'public'", (uid,)
        )
        self.conn.commit()

    # -- default tenant ---------------------------------------------------
    def get_default_space(self, application_id: str) -> Optional[dict]:
        """The seeded default space of ``application_id`` (name + environment)."""
        return _as_dict(self.conn.execute(
            "SELECT * FROM spaces WHERE application_id = ? AND name = ? "
            "AND environment = ? ORDER BY created_at LIMIT 1",
            (application_id, DEFAULT_SPACE_NAME, DEFAULT_ENVIRONMENT),
        ).fetchone())

    def default_scope(
        self,
        application_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve the seeded default application/space ids for a new row.

        Ids are generated UUID v4 values, not constants, so they are looked up by
        the seed names (``aura`` / ``default`` / ``prod``) and only used to fill a
        missing argument. Either element stays ``None`` if the seed row is absent.
        """
        if not application_id:
            application = self.get_application_by_name(DEFAULT_APPLICATION_NAME)
            application_id = application["id"] if application else None
        if not space_id and application_id:
            space = self.get_default_space(application_id)
            space_id = space["id"] if space else None
        return application_id, space_id

    # -- sessions ---------------------------------------------------------
    def create_session(self, user_id: str, csrf: str, expires_at: int) -> str:
        """Create a session and return its opaque cookie token.

        Only ``session_key(token)`` is stored (row ``id``); the clear token
        exists solely in the returned value and the client cookie. Expired rows
        are pruned here so the table cannot grow without bound.
        """
        token = new_token(32)
        now = self.now()
        self.conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        self.conn.execute(
            "INSERT INTO sessions (id, user_id, csrf, expires_at) VALUES (?, ?, ?, ?)",
            (session_key(token), user_id, csrf, expires_at),
        )
        self.conn.commit()
        return token

    def get_session(self, token: str) -> Optional[sqlite3.Row]:
        """Look a session up by its cookie token (hashed before the query)."""
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND expires_at > ?",
            (session_key(token), self.now()),
        ).fetchone()

    # -- public portal listening position --------------------------------
    def get_progress_map(self, user_id: str, object_ids: list) -> dict:
        if not object_ids:
            return {}
        marks = ",".join("?" for _ in object_ids)
        rows = self.conn.execute(
            f"SELECT object_id, position_seconds FROM listen_progress "
            f"WHERE user_id = ? AND object_id IN ({marks})",
            (user_id, *object_ids),
        ).fetchall()
        return {r["object_id"]: float(r["position_seconds"]) for r in rows}

    # -- append-only listening events (#320) ------------------------------
    def record_listen_event(
        self, user_id: str, object_id: str, kind: str, position_seconds: float,
        delta_seconds: float, now: int, client_event_id: str = "",
    ) -> bool:
        """Insert one idempotent event; False means it was already recorded."""
        eid = listen_events.event_id(
            user_id, object_id, kind, position_seconds, now, client_event_id
        )
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO listen_events "
            "(event_id, user_id, object_id, kind, position_seconds, delta_seconds, "
            "created_at, anonymized_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (eid, user_id, object_id, kind, max(0.0, float(position_seconds)),
             max(0.0, float(delta_seconds)), int(now)),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def last_listen_event_at(self, user_id: str, object_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(created_at), 0) AS t FROM listen_events "
            "WHERE user_id = ? AND object_id = ?", (user_id, object_id),
        ).fetchone()
        return int(row["t"] or 0)

    def listening_totals(self, user_id: str, now: int, retention_seconds: int) -> dict:
        """Prune expired events, then project one visitor's measured totals."""
        cutoff = int(now) - max(0, int(retention_seconds))
        self.conn.execute("DELETE FROM listen_events WHERE created_at < ?", (cutoff,))
        row = self.conn.execute(
            "SELECT COALESCE(SUM(delta_seconds), 0) AS listened, "
            "COALESCE(SUM(CASE WHEN kind = 'start' THEN 1 ELSE 0 END), 0) AS starts, "
            "COALESCE(SUM(CASE WHEN kind = 'end' THEN 1 ELSE 0 END), 0) AS ends, "
            "COUNT(*) AS samples, COALESCE(MAX(created_at), 0) AS last_at "
            "FROM listen_events WHERE user_id = ? AND created_at >= ?",
            (user_id, cutoff),
        ).fetchone()
        self.conn.commit()
        return {
            "listened_seconds": int(float(row["listened"])),
            "starts": int(row["starts"]),
            "ends": int(row["ends"]),
            "samples": int(row["samples"]),
            "last_event_at": int(row["last_at"]),
        }

    def portal_stats(self, period: str, available: str) -> dict:
        """Aggregate portal figures per published book: no visitor is identifiable."""
        books = [dict(r) for r in self.conn.execute(
            "SELECT o.id, o.display_name, o.duration_seconds, "
            "(SELECT COUNT(*) FROM listen_progress p WHERE p.object_id = o.id "
            "  AND p.position_seconds > 0) AS listeners, "
            "(SELECT COUNT(*) FROM listen_progress p WHERE p.object_id = o.id "
            "  AND o.duration_seconds > 0 AND p.position_seconds >= 0.9 * o.duration_seconds) AS completed, "
            "(SELECT COUNT(*) FROM listen_favorites f WHERE f.object_id = o.id) AS favorites, "
            "COALESCE((SELECT u.views FROM object_usage_monthly u "
            "  WHERE u.object_id = o.id AND u.period = ?), 0) AS views_month "
            "FROM objects o WHERE o.published_at IS NOT NULL AND o.status = ?",
            (period, available),
        ).fetchall()]
        accounts = self.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'public'").fetchone()["n"]
        return {"books": books, "accounts": accounts}

    # -- public portal bookmarks -------------------------------------------
    def list_bookmarks(self, user_id: str, object_id: str) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT id, position_seconds, note, created_at FROM listen_bookmarks "
            "WHERE user_id = ? AND object_id = ? ORDER BY position_seconds, created_at",
            (user_id, object_id),
        ).fetchall()]

    def add_bookmark(self, user_id: str, object_id: str, position: float, note: str,
                     now: int, limit: int) -> Optional[dict]:
        """Store a bookmark; None when the visitor already has ``limit`` on this book."""
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM listen_bookmarks WHERE user_id = ? AND object_id = ?",
            (user_id, object_id),
        ).fetchone()["n"]
        if count >= limit:
            return None
        bid = self.new_id()
        self.conn.execute(
            "INSERT INTO listen_bookmarks (id, user_id, object_id, position_seconds, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (bid, user_id, object_id, position, note, now),
        )
        self.conn.commit()
        return {"id": bid, "position_seconds": position, "note": note, "created_at": now}

    def delete_bookmark(self, user_id: str, bookmark_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM listen_bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount == 1

    # -- private playlists (issue #302) ------------------------------------
    def list_listen_playlists(self, user_id: str) -> list:
        rows = self.conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM listen_playlist_items i "
            "WHERE i.playlist_id = p.id) AS item_count "
            "FROM listen_playlists p WHERE p.user_id = ? "
            "ORDER BY p.updated_at DESC", (user_id,),
        ).fetchall()
        return [_as_dict(r) for r in rows]

    def create_listen_playlist(self, user_id: str, name: str, now: int) -> dict:
        pid = self.new_id()
        self.conn.execute(
            "INSERT INTO listen_playlists (id, user_id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (pid, user_id, name, now, now),
        )
        self.conn.commit()
        return {"id": pid, "name": name, "item_count": 0}

    def rename_listen_playlist(self, user_id: str, pid: str, name: str, now: int) -> bool:
        cur = self.conn.execute(
            "UPDATE listen_playlists SET name = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?", (name, now, pid, user_id),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def delete_listen_playlist(self, user_id: str, pid: str) -> bool:
        self.conn.execute(
            "DELETE FROM listen_playlist_items WHERE playlist_id = ? "
            "AND playlist_id IN (SELECT id FROM listen_playlists WHERE user_id = ?)",
            (pid, user_id),
        )
        cur = self.conn.execute(
            "DELETE FROM listen_playlists WHERE id = ? AND user_id = ?", (pid, user_id),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def get_listen_playlist(self, user_id: str, pid: str):
        row = self.conn.execute(
            "SELECT * FROM listen_playlists WHERE id = ? AND user_id = ?", (pid, user_id),
        ).fetchone()
        return _as_dict(row) if row else None

    def list_listen_playlist_items(self, pid: str) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT object_id, position FROM listen_playlist_items "
            "WHERE playlist_id = ? ORDER BY position ASC", (pid,),
        ).fetchall()]

    def add_listen_playlist_item(self, pid: str, object_id: str, position: int, now: int) -> bool:
        cur = self.conn.execute(
            "INSERT INTO listen_playlist_items (playlist_id, object_id, position) "
            "VALUES (?, ?, ?) ON CONFLICT(playlist_id, object_id) DO NOTHING",
            (pid, object_id, position),
        )
        self.conn.commit()
        if cur.rowcount:
            self.conn.execute(
                "UPDATE listen_playlists SET updated_at = ? WHERE id = ?", (now, pid)
            )
            self.conn.commit()
        return cur.rowcount == 1

    def remove_listen_playlist_item(self, pid: str, object_id: str, now: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM listen_playlist_items WHERE playlist_id = ? AND object_id = ?",
            (pid, object_id),
        )
        self.conn.commit()
        if cur.rowcount:
            self.conn.execute(
                "UPDATE listen_playlists SET updated_at = ? WHERE id = ?", (now, pid)
            )
            self.conn.commit()
        return cur.rowcount == 1

    def get_favorite_ids(self, user_id: str, object_ids: list) -> set:
        """Which of ``object_ids`` the visitor has put in their favourites."""
        found: set = set()
        for start in range(0, len(object_ids), 500):
            batch = object_ids[start:start + 500]
            marks = ",".join("?" for _ in batch)
            found.update(r["object_id"] for r in self.conn.execute(
                "SELECT object_id FROM listen_favorites "
                f"WHERE user_id = ? AND object_id IN ({marks})",
                (user_id, *batch),
            ).fetchall())
        return found

    def set_favorite(self, user_id: str, object_id: str, favorite: bool, now: int) -> None:
        if favorite:
            self.conn.execute(
                "INSERT INTO listen_favorites (user_id, object_id, created_at) "
                "VALUES (?, ?, ?) ON CONFLICT(user_id, object_id) DO NOTHING",
                (user_id, object_id, now),
            )
        else:
            self.conn.execute(
                "DELETE FROM listen_favorites WHERE user_id = ? AND object_id = ?",
                (user_id, object_id),
            )
        self.conn.commit()

    def save_progress(
        self, user_id: str, object_id: str, position_seconds: float, now: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO listen_progress (user_id, object_id, position_seconds, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, object_id) DO UPDATE SET "
            "position_seconds = excluded.position_seconds, "
            "updated_at = excluded.updated_at",
            (user_id, object_id, max(0.0, float(position_seconds)), now),
        )
        self.conn.commit()

    def revoke_sessions_beyond(self, max_expires_at: int) -> int:
        """Delete sessions whose expiry exceeds the current policy.

        Used at boot after AURA_SESSION_TTL is shortened: rows created under the
        old 90-day policy must not outlive the new 8-hour one.
        """
        cur = self.conn.execute(
            "DELETE FROM sessions WHERE expires_at > ?", (max_expires_at,)
        )
        self.conn.commit()
        return cur.rowcount

    def delete_session(self, sid: str) -> None:
        """Delete by stored row id (``session["id"]``, i.e. the digest)."""
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        self.conn.commit()

    def extend_session(self, sid: str, expires_at: int) -> None:
        """Slide the session expiry forward. Only ever extends, never shortens."""
        self.conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ? AND expires_at < ?",
            (expires_at, sid, expires_at),
        )
        self.conn.commit()

    def set_session_master(self, sid: str, until: Optional[int]) -> None:
        """Grant (epoch seconds) or end (None) master mode on one session."""
        self.conn.execute("UPDATE sessions SET master_until = ? WHERE id = ?", (until, sid))
        self.conn.commit()

    # -- applications / spaces / buckets (#35) ----------------------------
    def create_application(self, name: str) -> str:
        aid = self.new_id()
        self.conn.execute(
            "INSERT INTO applications (id, name, status, created_at) VALUES (?, ?, 'active', ?)",
            (aid, name, self.now()),
        )
        self.conn.commit()
        return aid

    def get_application(self, aid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM applications WHERE id = ?", (aid,)
        ).fetchone())

    def get_application_by_name(self, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM applications WHERE name = ?", (name,)
        ).fetchone())

    def list_applications(self) -> list:
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT * FROM applications ORDER BY created_at"
        ).fetchall()]

    def application_name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        sql = "SELECT 1 FROM applications WHERE name = ?"
        params: list = [name]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        return self.conn.execute(sql, params).fetchone() is not None

    def update_application(
        self, aid: str, *, name: Optional[str] = None, status: Optional[str] = None
    ) -> None:
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if not sets:
            return
        params.append(aid)
        self.conn.execute(
            f"UPDATE applications SET {', '.join(sets)} WHERE id = ?", params
        )
        self.conn.commit()

    def count_spaces_for_application(self, aid: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM spaces WHERE application_id = ?", (aid,)
        ).fetchone()["n"])

    def create_space(self, application_id: str, name: str, environment: str) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO spaces (id, application_id, name, environment, status, "
            "created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (sid, application_id, name, environment, self.now()),
        )
        self.conn.commit()
        return sid

    def get_space(self, sid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM spaces WHERE id = ?", (sid,)
        ).fetchone())

    def list_spaces(self, application_id: Optional[str] = None) -> list:
        if application_id:
            rows = self.conn.execute(
                "SELECT * FROM spaces WHERE application_id = ? ORDER BY created_at",
                (application_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM spaces ORDER BY created_at"
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def space_exists(
        self, application_id: str, name: str, environment: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        sql = (
            "SELECT 1 FROM spaces WHERE application_id = ? AND name = ? "
            "AND environment = ?"
        )
        params: list = [application_id, name, environment]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        return self.conn.execute(sql, params).fetchone() is not None

    def update_space(
        self, sid: str, *, name: Optional[str] = None,
        environment: Optional[str] = None, status: Optional[str] = None,
    ) -> None:
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if environment is not None:
            sets.append("environment = ?")
            params.append(environment)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if not sets:
            return
        params.append(sid)
        self.conn.execute(f"UPDATE spaces SET {', '.join(sets)} WHERE id = ?", params)
        self.conn.commit()

    def space_counts(self, sid: str) -> dict:
        def count(sql: str) -> int:
            return int(self.conn.execute(sql, (sid,)).fetchone()["n"])

        return {
            "buckets": count("SELECT COUNT(*) AS n FROM buckets WHERE space_id = ?"),
            "identities": count(
                "SELECT COUNT(*) AS n FROM service_identities WHERE space_id = ?"
            ),
            "objects": count("SELECT COUNT(*) AS n FROM objects WHERE space_id = ?"),
        }

    def create_bucket(self, space_id: str, name: str, is_default: bool = False) -> str:
        bid = self.new_id()
        self.conn.execute(
            "INSERT INTO buckets (id, space_id, name, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bid, space_id, name, 1 if is_default else 0, self.now()),
        )
        self.conn.commit()
        return bid

    def get_bucket_for_space(self, space_id: str, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? AND name = ?", (space_id, name)
        ).fetchone())

    def get_default_bucket(self, space_id: str) -> Optional[dict]:
        # Strict default only (M06): a space with no default bucket yields None
        # so upload-intents without an explicit registered bucket fail with 409
        # instead of silently falling back to a non-default bucket.
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? AND is_default = 1 "
            "ORDER BY created_at ASC LIMIT 1",
            (space_id,),
        ).fetchone())

    def get_bucket_by_name(self, name: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE name = ?", (name,)
        ).fetchone())

    def get_bucket(self, bid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM buckets WHERE id = ?", (bid,)
        ).fetchone())

    def list_buckets(self, space_id: str) -> list:
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT * FROM buckets WHERE space_id = ? ORDER BY created_at", (space_id,)
        ).fetchall()]

    def has_object(self, bucket: str, object_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM objects WHERE bucket = ? AND object_key = ? LIMIT 1",
            (bucket, object_key),
        ).fetchone()
        return row is not None

    def list_all_buckets(self) -> list:
        # Every registered bucket, oldest first; the API joins space/application
        # names so a bucket is never shown without its attachment (#M04).
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT * FROM buckets ORDER BY created_at, name"
        ).fetchall()]

    def set_default_bucket(self, space_id: str, bid: str, is_default: bool = True) -> None:
        # Exactly one default per space: clear the flag on the space's other
        # buckets, then set it on the target (scoped to the same space).
        if is_default:
            self.conn.execute(
                "UPDATE buckets SET is_default = 0 WHERE space_id = ?", (space_id,)
            )
            self.conn.execute(
                "UPDATE buckets SET is_default = 1 WHERE id = ? AND space_id = ?",
                (bid, space_id),
            )
        else:
            self.conn.execute(
                "UPDATE buckets SET is_default = 0 WHERE id = ? AND space_id = ?",
                (bid, space_id),
            )
        self.conn.commit()

    # -- service identities (#38) -----------------------------------------
    def create_identity(
        self, iid: str, application_id: str, space_id: str, name: str,
        secret_hash: str, scopes: str, expires_at: Optional[int] = None,
    ) -> str:
        self.conn.execute(
            "INSERT INTO service_identities (id, application_id, space_id, name, "
            "secret_hash, scopes, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, application_id, space_id, name, secret_hash, scopes, self.now(), expires_at),
        )
        self.conn.commit()
        return iid

    def get_identity(self, iid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM service_identities WHERE id = ?", (iid,)
        ).fetchone())

    def list_identities(self, space_id: Optional[str] = None) -> list:
        if space_id:
            rows = self.conn.execute(
                "SELECT * FROM service_identities WHERE space_id = ? ORDER BY created_at",
                (space_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM service_identities ORDER BY created_at"
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def update_identity_secret(self, iid: str, secret_hash: str) -> None:
        self.conn.execute(
            "UPDATE service_identities SET secret_hash = ?, rotated_at = ? WHERE id = ?",
            (secret_hash, self.now(), iid),
        )
        self.conn.commit()

    def revoke_identity(self, iid: str) -> None:
        self.conn.execute(
            "UPDATE service_identities SET revoked_at = ? WHERE id = ?",
            (self.now(), iid),
        )
        self.conn.commit()

    # -- partner integrations -------------------------------------------
    _PARTNER_SELECT = (
        "SELECT p.*, i.name AS identity_name, i.scopes AS identity_scopes, "
        "i.expires_at AS identity_expires_at, i.last_used_at AS identity_last_used_at, "
        "i.revoked_at AS identity_revoked_at, i.rotated_at AS identity_rotated_at "
        "FROM partner_sites p JOIN service_identities i ON i.id = p.identity_id "
    )

    def create_partner_site(
        self, pid: str, space_id: str, identity_id: str, name: str, site_url: str,
        default_ttl_seconds: Optional[int], notes: str, created_by: Optional[str],
    ) -> str:
        now = self.now()
        self.conn.execute(
            "INSERT INTO partner_sites (id, space_id, identity_id, name, site_url, "
            "default_ttl_seconds, notes, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, space_id, identity_id, name, site_url, default_ttl_seconds,
             notes, created_by, now, now),
        )
        self.conn.commit()
        return pid

    def list_partner_sites(self) -> list:
        rows = self.conn.execute(
            self._PARTNER_SELECT + "ORDER BY p.created_at"
        ).fetchall()
        return [_as_dict(r) for r in rows]

    def get_partner_site(self, pid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            self._PARTNER_SELECT + "WHERE p.id = ?", (pid,)
        ).fetchone())

    def update_partner_site(
        self, pid: str, name: str, site_url: str,
        default_ttl_seconds: Optional[int], notes: str,
    ) -> None:
        self.conn.execute(
            "UPDATE partner_sites SET name = ?, site_url = ?, "
            "default_ttl_seconds = ?, notes = ?, updated_at = ? WHERE id = ?",
            (name, site_url, default_ttl_seconds, notes, self.now(), pid),
        )
        self.conn.commit()

    def delete_partner_site(self, pid: str) -> None:
        self.conn.execute("DELETE FROM partner_sites WHERE id = ?", (pid,))
        self.conn.commit()

    def touch_identity(self, iid: str, ts: int) -> None:
        self.conn.execute(
            "UPDATE service_identities SET last_used_at = ? WHERE id = ?", (ts, iid)
        )
        self.conn.commit()

    # -- object shares ----------------------------------------------------
    def create_share(
        self, object_id: str, space_id: str, created_by: str,
        created_by_kind: str, token_hash: str, expires_at: int,
        content_disposition: str = "attachment",
        max_uses: Optional[int] = None,
    ) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO object_shares (id, object_id, space_id, created_by, "
            "created_by_kind, token_hash, content_disposition, expires_at, "
            "max_uses, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, object_id, space_id, created_by, created_by_kind, token_hash,
             content_disposition, expires_at, max_uses, self.now()),
        )
        self.conn.commit()
        return sid

    def get_share(self, sid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM object_shares WHERE id = ?", (sid,)
        ).fetchone())

    def get_share_by_token_hash(self, token_hash: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM object_shares WHERE token_hash = ?", (token_hash,)
        ).fetchone())

    def list_shares(self, object_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM object_shares WHERE object_id = ? "
            "ORDER BY created_at DESC, id",
            (object_id,),
        ).fetchall()
        return [_as_dict(r) for r in rows]

    # -- content revisions (docs/CONTENT-REVISIONS.md, phase 1) ---------------
    # Schema and persistence only: nothing in the API creates, reads or purges a
    # revision yet. Bytes of a revision live under its own `storage_key`, never
    # under `objects.object_key`, so the "one live key per object" invariant the
    # reconciler and orphan sweeps rely on is untouched.
    def create_revision(
        self, object_id: str, revision_number: int, bucket: str,
        storage_key: str, size_bytes: int, checksum_sha256: str,
        content_type: str, created_by_id: Optional[str] = None,
        created_by_kind: Optional[str] = None, keep_forever: bool = False,
    ) -> str:
        rid = self.new_id()
        self.conn.execute(
            "INSERT INTO object_revisions (id, object_id, revision_number, bucket, "
            "storage_key, size_bytes, checksum_sha256, content_type, created_at, "
            "created_by_id, created_by_kind, keep_forever) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, object_id, revision_number, bucket, storage_key, size_bytes,
             checksum_sha256, content_type, self.now(), created_by_id,
             created_by_kind, 1 if keep_forever else 0),
        )
        self.conn.commit()
        return rid

    def list_revisions(self, object_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM object_revisions WHERE object_id = ? "
            "ORDER BY revision_number DESC",
            (object_id,),
        ).fetchall()
        return [_as_dict(r) for r in rows]

    def count_object_keep_forever_revisions(self, object_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM object_revisions WHERE object_id = ? AND keep_forever = 1",
            (object_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def delete_revisions_for_object(self, object_id: str) -> list[dict]:
        """Delete revision rows for an object and return their storage locations.

        Callers are responsible for deleting the bytes; this is used when an
        object is purged and no keep-forever revisions block the purge.
        """
        rows = self.conn.execute(
            "SELECT id, bucket, storage_key FROM object_revisions WHERE object_id = ?",
            (object_id,),
        ).fetchall()
        self.conn.execute("DELETE FROM object_revisions WHERE object_id = ?", (object_id,))
        self.conn.commit()
        return [_as_dict(r) for r in rows]

    def get_revision(self, object_id: str, revision_id: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM object_revisions WHERE object_id = ? AND id = ?",
            (object_id, revision_id),
        ).fetchone())

    def delete_revision(self, revision_id: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM object_revisions WHERE id = ?", (revision_id,)
        )
        self.conn.commit()
        return cur.rowcount

    def set_revision_keep_forever(self, revision_id: str, keep: bool) -> int:
        cur = self.conn.execute(
            "UPDATE object_revisions SET keep_forever = ? WHERE id = ?",
            (1 if keep else 0, revision_id),
        )
        self.conn.commit()
        return cur.rowcount

    def count_keep_forever(self, owner_id: str) -> int:
        """Revisions pinned by one owner, across all their objects (per-user cap)."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM object_revisions r "
            "JOIN objects o ON o.id = r.object_id "
            "WHERE o.owner_id = ? AND r.keep_forever = 1",
            (owner_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def consume_share(self, sid: str, now: int) -> bool:
        """Redeem one use atomically. False when revoked, expired or exhausted.

        The condition lives in the UPDATE so two concurrent readers cannot both
        take the last remaining use of a ``max_uses`` link.
        """
        cur = self.conn.execute(
            "UPDATE object_shares SET use_count = use_count + 1, last_used_at = ? "
            "WHERE id = ? AND revoked_at IS NULL AND expires_at > ? "
            "AND (max_uses IS NULL OR use_count < max_uses)",
            (now, sid, now),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def revoke_share(self, sid: str, now: int) -> None:
        self.conn.execute(
            "UPDATE object_shares SET revoked_at = ? "
            "WHERE id = ? AND revoked_at IS NULL",
            (now, sid),
        )
        self.conn.commit()

    def delete_shares_for_object(self, object_id: str) -> None:
        self.conn.execute(
            "DELETE FROM object_shares WHERE object_id = ?", (object_id,)
        )
        self.conn.commit()

    # -- folder shares ----------------------------------------------------
    # Same capability model as object shares, scoped to a folder subtree. The
    # folder row is deliberately not a foreign key: deleting a folder must not
    # be blocked by a link, and the share then answers 404.
    def create_folder_share(
        self, folder_id: str, space_id: str, created_by: str,
        created_by_kind: str, token_hash: str, expires_at: int,
        max_uses: Optional[int] = None,
    ) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO folder_shares (id, folder_id, space_id, created_by, "
            "created_by_kind, token_hash, expires_at, max_uses, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, folder_id, space_id, created_by, created_by_kind, token_hash,
             expires_at, max_uses, self.now()),
        )
        self.conn.commit()
        return sid

    def get_folder_share(self, sid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM folder_shares WHERE id = ?", (sid,)
        ).fetchone())

    def get_folder_share_by_token_hash(self, token_hash: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM folder_shares WHERE token_hash = ?", (token_hash,)
        ).fetchone())

    def list_folder_shares(self, folder_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM folder_shares WHERE folder_id = ? "
            "ORDER BY created_at DESC, id",
            (folder_id,),
        ).fetchall()
        return [_as_dict(r) for r in rows]

    def consume_folder_share(self, sid: str, now: int) -> bool:
        """Redeem one download atomically (revocation, expiry and max_uses)."""
        cur = self.conn.execute(
            "UPDATE folder_shares SET use_count = use_count + 1, last_used_at = ? "
            "WHERE id = ? AND revoked_at IS NULL AND expires_at > ? "
            "AND (max_uses IS NULL OR use_count < max_uses)",
            (now, sid, now),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def revoke_folder_share(self, sid: str, now: int) -> None:
        self.conn.execute(
            "UPDATE folder_shares SET revoked_at = ? "
            "WHERE id = ? AND revoked_at IS NULL",
            (now, sid),
        )
        self.conn.commit()

    # -- objects ----------------------------------------------------------
    def create_pending_object(
        self, *, space_id: str, application_id: Optional[str], environment: Optional[str],
        bucket: str, object_key: str, display_name: str, content_type: str,
        owner_id: Optional[str], actor_id: str, actor_kind: str,
        intent_expires_at: Optional[int], folder_id: Optional[str] = None,
        expected_size_bytes: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        content_encoding: Optional[str] = None,
        transfer_session_id: Optional[str] = None,
        replace_target_id: Optional[str] = None,
    ) -> str:
        oid = self.new_id()
        now = self.now()
        self.conn.execute(
            """INSERT INTO objects (id, bucket, object_key, display_name, content_type,
               size_bytes, checksum_sha256, folder_id, owner_id, visibility, status,
               created_at, updated_at, actor_kind, actor_id, application_id, space_id,
               environment, intent_expires_at, expected_size_bytes, idempotency_key,
               content_encoding, transfer_session_id, replace_target_id)
               VALUES (?, ?, ?, ?, ?, -1, '', ?, ?, 'private', 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (oid, bucket, object_key, display_name, content_type, folder_id, owner_id,
             now, now, actor_kind, actor_id, application_id, space_id, environment,
             intent_expires_at, expected_size_bytes, idempotency_key, content_encoding,
             transfer_session_id, replace_target_id),
        )
        self.conn.commit()
        return oid

    def set_transfer_session(self, oid: str, transfer_session_id: Optional[str]) -> None:
        """Attach a client session id to a live intent (replay without one)."""
        self.conn.execute(
            "UPDATE objects SET transfer_session_id = ?, updated_at = ? "
            "WHERE id = ? AND transfer_session_id IS NULL",
            (transfer_session_id, self.now(), oid),
        )
        self.conn.commit()

    # -- transfer history journal (#246) ----------------------------------
    def record_transfer_record(
        self, oid: str, status: str, *,
        final_size_bytes: Optional[int] = None,
        checksum_sha256: str = "",
        failure_kind: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[str]:
        """Append one terminal transfer row for ``oid``, idempotently.

        ``objects`` remains the source of truth; this journal only stores the
        terminal transition and final metadata. A replayed terminal event (same
        ``object_id``) returns the existing row id and inserts nothing. The
        object row is read here so callers cannot forget to copy the tenant,
        owner, actor or display metadata. Returns ``None`` when the object no
        longer exists or ``status`` is not a transfer terminal state.
        """
        if status not in TRANSFER_RECORD_STATUSES:
            return None
        row = self.conn.execute(
            "SELECT * FROM objects WHERE id = ?", (oid,)
        ).fetchone()
        if row is None:
            return None
        existing = self.conn.execute(
            "SELECT id FROM transfer_records WHERE object_id = ?", (oid,)
        ).fetchone()
        if existing is not None:
            return existing["id"]
        if final_size_bytes is None and status == "available":
            stored = row["size_bytes"]
            if stored is not None and int(stored) >= 0:
                final_size_bytes = int(stored)
        if not checksum_sha256 and status == "available":
            checksum_sha256 = row["checksum_sha256"] or ""
        rid = self.new_id()
        now = self.now()
        self.conn.execute(
            "INSERT INTO transfer_records (id, transfer_session_id, object_id, "
            "space_id, owner_id, actor_id, actor_kind, display_name, content_type, "
            "expected_size_bytes, final_size_bytes, status, failure_kind, "
            "error_message, checksum_sha256, created_at, terminal_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (
                rid, row["transfer_session_id"], oid, row["space_id"],
                row["owner_id"], row["actor_id"], row["actor_kind"],
                row["display_name"], row["content_type"],
                row["expected_size_bytes"], final_size_bytes, status,
                failure_kind, sanitize_transfer_error(error_message),
                checksum_sha256 or "", int(row["created_at"] or now), now,
            ),
        )
        self.conn.commit()
        return rid

    def list_transfer_records(
        self, *, space_id: str, owner_id: Optional[str] = None,
        status: Optional[str] = None,
        transfer_session_id: Optional[str] = None,
        created_after: Optional[int] = None,
        created_before: Optional[int] = None,
        limit: int = 50, offset: int = 0,
    ):
        where, params = build_transfer_where(
            space_id=space_id, owner_id=owner_id, status=status,
            transfer_session_id=transfer_session_id,
            created_after=created_after, created_before=created_before,
        )
        params += [limit, offset]
        return self.conn.execute(
            f"SELECT * FROM transfer_records WHERE {where} "
            "ORDER BY terminal_at DESC, id ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

    def get_transfer_record(
        self, rid: str, *, space_id: str, owner_id: Optional[str] = None,
    ):
        sql = "SELECT * FROM transfer_records WHERE id = ? AND space_id = ?"
        params = [rid, space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        return self.conn.execute(sql, params).fetchone()

    def purge_transfer_records_before(self, cutoff: int, limit: int = 500) -> int:
        """Drop journal rows whose terminal state is older than ``cutoff``.

        Bounded so a forgotten retention setting cannot stall the sweep on a
        huge table; the next run continues where this one stopped.
        """
        cur = self.conn.execute(
            "DELETE FROM transfer_records WHERE id IN ("
            "SELECT id FROM transfer_records WHERE terminal_at < ? "
            "ORDER BY terminal_at ASC LIMIT ?)",
            (cutoff, limit),
        )
        self.conn.commit()
        return cur.rowcount

    def get_object_unscoped(self, oid: str) -> Optional[sqlite3.Row]:
        """Look an object up by id without a tenant filter.

        Only for callers that already hold an unguessable public capability
        (a published slug) or that verify publication explicitly, as the public
        progress route does. Never use this for ordinary data-plane reads.
        """
        return self.conn.execute("SELECT * FROM objects WHERE id = ?", (oid,)).fetchone()

    def get_object(self, oid: str, *, space_id: str, owner_id: Optional[str] = None):
        sql = "SELECT * FROM objects WHERE id = ? AND space_id = ?"
        params = [oid, space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        return self.conn.execute(sql, params).fetchone()

    def get_object_by_slug(self, slug: str):
        return self.conn.execute(
            "SELECT * FROM objects WHERE public_slug = ?", (slug,)
        ).fetchone()

    def set_object_publication(
        self, oid: str, slug: Optional[str], published_at: Optional[int],
    ) -> None:
        self.conn.execute(
            "UPDATE objects SET public_slug = ?, published_at = ?, "
            "version = version + 1, updated_at = ? WHERE id = ?",
            (slug, published_at, self.now(), oid),
        )
        self.conn.commit()

    def set_object_thumbnail(
        self, oid: str, thumbnail_key: Optional[str],
        duration_seconds: Optional[float],
    ) -> None:
        self.conn.execute(
            "UPDATE objects SET thumbnail_key = ?, duration_seconds = ? WHERE id = ?",
            (thumbnail_key, duration_seconds, oid),
        )
        self.conn.commit()

    def set_object_cover(self, oid: str, cover_key: Optional[str]) -> None:
        self.conn.execute(
            "UPDATE objects SET cover_key = ? WHERE id = ?", (cover_key, oid)
        )
        self.conn.commit()

    def set_object_duration(self, oid: str, duration_seconds: float) -> None:
        self.conn.execute(
            "UPDATE objects SET duration_seconds = ? WHERE id = ?",
            (float(duration_seconds), oid),
        )
        self.conn.commit()

    def mark_media_probe(self, oid: str, kind: str, now: int) -> None:
        column = {"cover": "cover_probe_at", "chapters": "chapters_probe_at"}[kind]
        self.conn.execute(
            f"UPDATE objects SET {column} = ? WHERE id = ?", (now, oid)
        )
        self.conn.commit()

    def replace_audio_chapters(self, oid: str, chapters: list[dict]) -> None:
        self.conn.execute("DELETE FROM audio_chapters WHERE object_id = ?", (oid,))
        self.conn.executemany(
            "INSERT INTO audio_chapters "
            "(object_id, chapter_index, title, start_seconds, end_seconds) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (oid, int(c["index"]), str(c.get("title") or ""),
                 float(c["start"]), c.get("end"))
                for c in chapters
            ],
        )
        self.conn.commit()

    def get_audio_chapters(self, oid: str) -> list:
        return [
            dict(r) for r in self.conn.execute(
                "SELECT chapter_index, title, start_seconds, end_seconds "
                "FROM audio_chapters WHERE object_id = ? ORDER BY chapter_index",
                (oid,),
            ).fetchall()
        ]

    def get_audio_chapters_map(self, oids: list) -> dict:
        """Chapters of many objects in a few queries: ``{object_id: [chapter]}``."""
        result: dict = {oid: [] for oid in oids}
        for start in range(0, len(oids), 500):  # SQLite caps bound variables
            batch = oids[start:start + 500]
            marks = ",".join("?" for _ in batch)
            for r in self.conn.execute(
                "SELECT object_id, chapter_index, title, start_seconds, end_seconds "
                f"FROM audio_chapters WHERE object_id IN ({marks}) "
                "ORDER BY object_id, chapter_index",
                tuple(batch),
            ).fetchall():
                row = dict(r)
                result[row.pop("object_id")].append(row)
        return result

    def replace_object_content(self, target_id: str, source_id: str, source: dict) -> None:
        """Point ``target_id`` at ``source_id``'s bytes, keeping id and slug.

        The source row is deleted first: ``(bucket, object_key)`` is unique, so
        updating the target before removing the source would collide. Both
        statements share one transaction.
        """
        self.conn.execute("DELETE FROM objects WHERE id = ?", (source_id,))
        self.conn.execute(
            "UPDATE objects SET bucket = ?, object_key = ?, size_bytes = ?, "
            "checksum_sha256 = ?, content_type = ?, expected_size_bytes = ?, "
            "content_encoding = ?, thumbnail_key = ?, duration_seconds = ?, "
            "scrubbed_at = ?, scrub_result = 'ok', version = version + 1, "
            "updated_at = ? WHERE id = ?",
            (source["bucket"], source["object_key"], source["size_bytes"],
             source["checksum_sha256"], source["content_type"],
             source.get("expected_size_bytes"), source.get("content_encoding"),
             source.get("thumbnail_key"), source.get("duration_seconds"),
             self.now(), self.now(), target_id),
        )
        self.conn.commit()

    def list_objects(
        self, *, space_id: str, owner_id: Optional[str] = None,
        folder_id: Optional[str] = None, q: Optional[str] = None,
        search: Optional[str] = None,
        status: Optional[str] = None, hide_deleted: bool = False,
        content_type: Optional[str] = None, tag: Optional[str] = None,
        tags: Optional[list[str]] = None, tag_mode: str = "all",
        min_size: Optional[int] = None, max_size: Optional[int] = None,
        created_after: Optional[int] = None, created_before: Optional[int] = None,
        sort: str = "created_at", order: str = "desc",
        limit: int = 50, offset: int = 0,
    ):
        # Filters and sort are built by api/object_query.py so this stays in
        # lockstep with the PostgreSQL repository (M02). Every argument is
        # optional: omitting them keeps the historical "every visible object,
        # newest first" query.
        where, params = build_object_where(
            space_id=space_id, owner_id=owner_id, folder_id=folder_id, q=q,
            search=search,
            status=status, hide_deleted=hide_deleted,
            content_type=content_type, tag=tag, tags=tags, tag_mode=tag_mode,
            min_size=min_size,
            max_size=max_size, created_after=created_after,
            created_before=created_before,
        )
        sql = (
            f"SELECT * FROM objects WHERE {where} "
            f"{order_clause(sort=sort, order=order)} LIMIT ? OFFSET ?"
        )
        params += [limit, offset]
        return self.conn.execute(sql, params).fetchall()

    def count_pending(
        self, *, space_id: str, owner_id: Optional[str] = None,
        min_expires_at: Optional[int] = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS n FROM objects WHERE status = 'pending' AND space_id = ?"
        params: list = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        if min_expires_at is not None:
            # Expired intents stay 'pending' until the sweep deletes their
            # bytes: they must not count against the live-intent cap.
            sql += " AND (intent_expires_at IS NULL OR intent_expires_at >= ?)"
            params.append(min_expires_at)
        return int(self.conn.execute(sql, params).fetchone()["n"])

    def reserved_bytes_for(self, *, space_id: str,
                           owner_id: Optional[str] = None,
                           min_expires_at: Optional[int] = None) -> int:
        """Declared bytes of live uploads reserved by one owner (or services).

        Expired intents still awaiting the sweep must not block new uploads,
        just like they are excluded from the pending-intent count.
        """
        sql = (
            "SELECT COALESCE(SUM(expected_size_bytes), 0) AS n FROM objects "
            "WHERE status = 'pending' AND space_id = ?"
        )
        params: list = [space_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        else:
            sql += " AND owner_id IS NULL"
        if min_expires_at is not None:
            sql += " AND (intent_expires_at IS NULL OR intent_expires_at >= ?)"
            params.append(min_expires_at)
        return int(self.conn.execute(sql, params).fetchone()["n"])

    def get_pending_by_idempotency(
        self, *, actor_id: str, idempotency_key: str, space_id: str,
    ):
        """The live pending intent for an ``Idempotency-Key`` + actor, if any.

        Scoped by actor and space so one caller can never replay or observe
        another caller's (or another space's) intent. Returns the newest match.
        """
        return self.conn.execute(
            "SELECT * FROM objects WHERE status = 'pending' AND actor_id = ? "
            "AND idempotency_key = ? AND space_id = ? ORDER BY created_at DESC LIMIT 1",
            (actor_id, idempotency_key, space_id),
        ).fetchone()

    # -- asynchronous verification (N5) ------------------------------------
    def mark_verifying(self, oid: str, etag: Optional[str]) -> None:
        """Hand an uploaded object to the verification worker."""
        self.conn.execute(
            "UPDATE objects SET status = 'verifying', verify_etag = ?, "
            "verify_lease_until = NULL, verify_attempts = 0, updated_at = ? "
            "WHERE id = ? AND status IN ('pending', 'verifying')",
            (etag, self.now(), oid),
        )
        self.conn.commit()

    def claim_verification(self, now: int, lease_until: int):
        """Take the oldest verifying object nobody holds, under a lease.

        Compare-and-set on the lease, so two workers (threads or processes)
        never hash the same object at once; a crashed worker's lease simply
        runs out and the object is taken again.
        """
        row = self.conn.execute(
            "SELECT id FROM objects WHERE status = 'verifying' "
            "AND (verify_lease_until IS NULL OR verify_lease_until < ?) "
            "ORDER BY updated_at ASC LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            return None
        cur = self.conn.execute(
            "UPDATE objects SET verify_lease_until = ?, "
            "verify_attempts = COALESCE(verify_attempts, 0) + 1 "
            "WHERE id = ? AND status = 'verifying' "
            "AND (verify_lease_until IS NULL OR verify_lease_until < ?)",
            (lease_until, row["id"], now),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            return None
        return self.conn.execute("SELECT * FROM objects WHERE id = ?", (row["id"],)).fetchone()

    def extend_verification(self, oid: str, lease_until: int) -> None:
        """Push the lease (heartbeat while hashing, or a retry delay)."""
        self.conn.execute(
            "UPDATE objects SET verify_lease_until = ? WHERE id = ? AND status = 'verifying'",
            (lease_until, oid),
        )
        self.conn.commit()

    def get_by_idempotency(
        self, *, actor_id: str, idempotency_key: str, space_id: str,
    ):
        """Newest object of any status for an ``Idempotency-Key`` + actor."""
        return self.conn.execute(
            "SELECT * FROM objects WHERE actor_id = ? AND idempotency_key = ? "
            "AND space_id = ? ORDER BY created_at DESC LIMIT 1",
            (actor_id, idempotency_key, space_id),
        ).fetchone()

    def storage_commitment(self) -> dict:
        """Bytes the object store holds or has promised, across every space.

        ``stored``: verified bytes still on disk (available, trash, purge in
        progress). ``reserved``: declared sizes of uploads not yet verified
        (pending, verifying) — counted from the moment the intent is issued.
        """
        row = self.conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN status IN ('available', 'deleted', 'purging') "
            "AND size_bytes > 0 THEN size_bytes ELSE 0 END), 0) AS stored, "
            "COALESCE(SUM(CASE WHEN status IN ('pending', 'verifying') "
            "AND expected_size_bytes > 0 THEN expected_size_bytes ELSE 0 END), 0) AS reserved "
            "FROM objects"
        ).fetchone()
        return {"stored": int(row["stored"]), "reserved": int(row["reserved"])}
    # -- periodic integrity scrub ------------------------------------------
    def has_pending_uploads(self, since: int) -> bool:
        """True if an upload intent created at or after ``since`` is still pending."""
        return self.conn.execute(
            "SELECT 1 FROM objects WHERE status = 'pending' AND created_at >= ? LIMIT 1",
            (since,),
        ).fetchone() is not None

    def claim_scrub(self, now: int, lease_until: int, checked_before: int):
        """Take the available object checked longest ago (never-checked first),
        under a lease, if it is due (checked before ``checked_before``)."""
        row = self.conn.execute(
            "SELECT id FROM objects WHERE status = 'available' "
            "AND (scrubbed_at IS NULL OR scrubbed_at < ?) "
            "AND (scrub_lease_until IS NULL OR scrub_lease_until < ?) "
            "ORDER BY COALESCE(scrubbed_at, 0) ASC, created_at ASC LIMIT 1",
            (checked_before, now),
        ).fetchone()
        if row is None:
            return None
        cur = self.conn.execute(
            "UPDATE objects SET scrub_lease_until = ? WHERE id = ? "
            "AND (scrub_lease_until IS NULL OR scrub_lease_until < ?)",
            (lease_until, row["id"], now),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            return None
        return self.conn.execute("SELECT * FROM objects WHERE id = ?", (row["id"],)).fetchone()

    def record_scrub(self, oid: str, result: str, at: int) -> None:
        self.conn.execute(
            "UPDATE objects SET scrubbed_at = ?, scrub_result = ?, scrub_lease_until = NULL "
            "WHERE id = ?",
            (at, result, oid),
        )
        self.conn.commit()

    def has_active_transfers(self, since: int) -> bool:
        """True while uploads are in flight: a verifying object, or a pending
        intent created at or after ``since``. The scrubber yields to them."""
        row = self.conn.execute(
            "SELECT 1 FROM objects WHERE status = 'verifying' "
            "OR (status = 'pending' AND created_at >= ?) LIMIT 1",
            (since,),
        ).fetchone()
        return row is not None

    def release_scrub(self, oid: str) -> None:
        """Give the object back unchecked (storage outage): retried next run."""
        self.conn.execute("UPDATE objects SET scrub_lease_until = NULL WHERE id = ?", (oid,))
        self.conn.commit()

    def integrity_summary(self) -> dict:
        rows = self.conn.execute(
            "SELECT COALESCE(scrub_result, 'unchecked') AS result, COUNT(*) AS n, "
            "MIN(scrubbed_at) AS oldest FROM objects WHERE status IN ('available', 'suspect') "
            "GROUP BY COALESCE(scrub_result, 'unchecked')"
        ).fetchall()
        return {r["result"]: {"count": int(r["n"]), "oldest": r["oldest"]} for r in rows}

    def list_integrity_problems(self, limit: int = 100):
        return self.conn.execute(
            "SELECT id, space_id, display_name, size_bytes, scrub_result, scrubbed_at "
            "FROM objects WHERE status IN ('available', 'suspect') "
            "AND scrub_result IN ('mismatch', 'missing') "
            "ORDER BY scrubbed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    def object_states_for_keys(self, bucket: str, keys: list) -> dict:
        """Catalogue state of storage keys: ``{key: {id, status, multipart_upload_id}}``.

        Keys without a row are absent from the result (storage orphans).
        """
        out: dict = {}
        for i in range(0, len(keys), 500):
            chunk = list(keys[i:i + 500])
            if not chunk:
                continue
            marks = ",".join("?" for _ in chunk)
            for r in self.conn.execute(
                f"SELECT id, object_key, status, multipart_upload_id FROM objects "
                f"WHERE bucket = ? AND object_key IN ({marks})",
                (bucket, *chunk),
            ).fetchall():
                out[r["object_key"]] = {
                    "id": r["id"], "status": r["status"],
                    "multipart_upload_id": r["multipart_upload_id"],
                }
        return out

    def revision_keys(self, bucket: str, keys: list) -> set[str]:
        """Storage keys that belong to unpurged content revisions.

        These bytes are accounted for by ``object_revisions`` and must never be
        treated as storage orphans, even though no live object row owns them.
        """
        found: set[str] = set()
        for i in range(0, len(keys), 500):
            chunk = list(keys[i:i + 500])
            if not chunk:
                continue
            marks = ",".join("?" for _ in chunk)
            for r in self.conn.execute(
                f"SELECT storage_key FROM object_revisions "
                f"WHERE bucket = ? AND purged_at IS NULL AND storage_key IN ({marks})",
                (bucket, *chunk),
            ).fetchall():
                found.add(r["storage_key"])
        return found

    def has_revision_key(self, bucket: str, key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM object_revisions WHERE bucket = ? AND storage_key = ? "
            "AND purged_at IS NULL LIMIT 1",
            (bucket, key),
        ).fetchone()
        return row is not None

    TERMINAL_STATUSES = {"failed", "expired", "aborted", "deleted"}

    def mark_available(self, oid: str, size_bytes: int, checksum_sha256: str,
                       expected_version=None) -> int:
        if expected_version is None:
            cur = self.conn.execute(
                "UPDATE objects SET status = 'available', size_bytes = ?, "
                "checksum_sha256 = ?, version = version + 1, updated_at = ?, "
                "scrubbed_at = ?, scrub_result = 'ok' "
                "WHERE id = ? AND status IN ('pending', 'verifying')",
                (size_bytes, checksum_sha256, self.now(), self.now(), oid),
            )
        else:
            cur = self.conn.execute(
                "UPDATE objects SET status = 'available', size_bytes = ?, "
                "checksum_sha256 = ?, version = version + 1, updated_at = ?, "
                "scrubbed_at = ?, scrub_result = 'ok' "
                "WHERE id = ? AND status IN ('pending', 'verifying') AND version = ?",
                (size_bytes, checksum_sha256, self.now(), self.now(), oid, expected_version),
            )
        self.conn.commit()
        # The journal write is best-effort and idempotent: a failed insert must
        # never undo a successful publication, and a replayed commit must not
        # create a second row for the same object.
        if cur.rowcount:
            try:
                self.record_transfer_record(
                    oid, "available", final_size_bytes=size_bytes,
                    checksum_sha256=checksum_sha256,
                )
            except Exception:
                pass
        return cur.rowcount

    def set_multipart(self, oid: str, upload_id: Optional[str],
                      part_bytes: Optional[int]) -> None:
        """Record (or clear, with ``upload_id=None``) a multipart session (#72)."""
        self.conn.execute(
            "UPDATE objects SET multipart_upload_id = ?, multipart_part_bytes = ?, "
            "updated_at = ? WHERE id = ?",
            (upload_id, part_bytes, self.now(), oid),
        )
        self.conn.commit()

    def list_pending_before(self, cutoff: int, limit: int = 500,
                            multipart_expired_before: Optional[int] = None):
        # A multipart session lives longer than a single-PUT intent: it is only
        # stale once its own expiry has passed, whatever its creation time.
        mp_cut = multipart_expired_before if multipart_expired_before is not None else cutoff
        return self.conn.execute(
            "SELECT * FROM objects WHERE status = 'pending' AND created_at < ? "
            "AND (multipart_upload_id IS NULL OR intent_expires_at < ?) "
            "ORDER BY created_at ASC LIMIT ?",
            (cutoff, mp_cut, limit),
        ).fetchall()

    def list_available(self, limit: int = 500):
        """Available rows oldest-first, bounded (M07 orphan scan)."""
        return self.conn.execute(
            "SELECT * FROM objects WHERE status = 'available' "
            "ORDER BY updated_at ASC LIMIT ?",
            (limit,),
        ).fetchall()

    def mark_reverified(self, oid: str, size_bytes: int,
                        checksum_sha256: str) -> int:
        """Publish an object after an operator re-hash (exit from ``suspect``).

        Unlike :meth:`mark_available`, this accepts an already-published row:
        the whole point is to rehabilitate an object whose bytes now match.
        """
        cur = self.conn.execute(
            "UPDATE objects SET status = 'available', size_bytes = ?, "
            "checksum_sha256 = ?, version = version + 1, updated_at = ?, "
            "scrubbed_at = ?, scrub_result = 'ok' "
            "WHERE id = ? AND status IN ('available', 'suspect', 'failed')",
            (size_bytes, checksum_sha256, self.now(), self.now(), oid),
        )
        self.conn.commit()
        return cur.rowcount

    def set_status(self, oid: str, status: str, *,
                   expected_version=None, allowed_from=None,
                   failure_kind: Optional[str] = None,
                   error_message: Optional[str] = None) -> int:
        clauses = ["status = ?", "version = version + 1", "updated_at = ?"]
        params = [status, self.now()]
        where = ["id = ?"]
        params.append(oid)
        if allowed_from:
            where.append("status IN (%s)" % ",".join("?" for _ in allowed_from))
            params.extend(allowed_from)
        if expected_version is not None:
            where.append("version = ?")
            params.append(expected_version)
        if status in self.TERMINAL_STATUSES:
            clauses.append("terminal_since = COALESCE(terminal_since, ?)")
            params.insert(1, self.now())
        sql = "UPDATE objects SET " + ", ".join(clauses) + " WHERE " + " AND ".join(where)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        # Successful transfers are journaled by `mark_available`; `set_status`
        # journals the failure/abort/expiry terminal transitions. `available`
        # is excluded here on purpose: a restore is not a new transfer.
        if cur.rowcount and status in TRANSFER_RECORD_STATUSES and status != "available":
            try:
                self.record_transfer_record(
                    oid, status, failure_kind=failure_kind,
                    error_message=error_message,
                )
            except Exception:
                pass
        return cur.rowcount

    def list_status_before(self, status: str, cutoff: int, limit: int = 500):
        """Rows in ``status`` not updated since ``cutoff``, oldest first."""
        return self.conn.execute(
            "SELECT * FROM objects WHERE status = ? AND updated_at < ? "
            "ORDER BY updated_at ASC LIMIT ?",
            (status, cutoff, limit),
        ).fetchall()

    def delete_object_row(self, oid: str) -> None:
        self.conn.execute("DELETE FROM objects WHERE id = ?", (oid,))
        self.conn.commit()

    # -- folders (#61) ----------------------------------------------------
    # Folders are logical catalogue entities owned by a human user. They are
    # never real host directories; parent/child links live in `parent_id`.
    def create_folder(self, owner_id: str, name: str, parent_id: Optional[str] = None) -> str:
        fid = self.new_id()
        self.conn.execute(
            "INSERT INTO folders (id, owner_id, parent_id, name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (fid, owner_id, parent_id, name, self.now()),
        )
        self.conn.commit()
        return fid

    def get_folder(self, fid: str, *, owner_id: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM folders WHERE id = ? AND owner_id = ?", (fid, owner_id)
        ).fetchone())

    def get_folder_size(self, *, folder_id: str, owner_id: str) -> int:
        """Taille totale (octets) d'un dossier : objets disponibles directement
        + taille récursive des sous-dossiers."""
        total = 0
        # Objets directement dans ce dossier
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM objects "
            "WHERE folder_id = ? AND owner_id = ? AND status = 'available'",
            (folder_id, owner_id),
        ).fetchone()
        total += row["n"] or 0
        # Sous-dossiers récursifs
        subfolders = self.conn.execute(
            "SELECT id FROM folders WHERE parent_id = ? AND owner_id = ?",
            (folder_id, owner_id),
        ).fetchall()
        for sf in subfolders:
            total += self.get_folder_size(folder_id=sf["id"], owner_id=owner_id)
        return total

    def list_folders(self, *, owner_id: str, parent_id: Optional[str] = None) -> list:
        # parent_id=None lists the root level (parent_id IS NULL).
        if parent_id is None:
            rows = self.conn.execute(
                "SELECT * FROM folders WHERE owner_id = ? AND parent_id IS NULL "
                "ORDER BY name",
                (owner_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM folders WHERE owner_id = ? AND parent_id = ? ORDER BY name",
                (owner_id, parent_id),
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def list_all_folders(self, *, owner_id: str) -> list:
        # Flat listing of the owner's whole tree in one query (#62 follow-up).
        # Ordered by name for a deterministic payload; the client rebuilds the
        # hierarchy from parent_id. Owner-scoped, so no cross-user leak.
        rows = self.conn.execute(
            "SELECT * FROM folders WHERE owner_id = ? ORDER BY name, id", (owner_id,)
        ).fetchall()
        return [_as_dict(r) for r in rows]

    def folder_name_exists(
        self, *, owner_id: str, parent_id: Optional[str], name: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        if parent_id is None:
            sql = "SELECT 1 FROM folders WHERE owner_id = ? AND parent_id IS NULL AND name = ?"
            params: list = [owner_id, name]
        else:
            sql = "SELECT 1 FROM folders WHERE owner_id = ? AND parent_id = ? AND name = ?"
            params = [owner_id, parent_id, name]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        return self.conn.execute(sql, params).fetchone() is not None

    def rename_folder(self, fid: str, *, owner_id: str, name: str) -> None:
        self.conn.execute(
            "UPDATE folders SET name = ? WHERE id = ? AND owner_id = ?", (name, fid, owner_id)
        )
        self.conn.commit()

    def set_folder_parent(
        self, fid: str, *, owner_id: str, parent_id: Optional[str]
    ) -> None:
        self.conn.execute(
            "UPDATE folders SET parent_id = ? WHERE id = ? AND owner_id = ?",
            (parent_id, fid, owner_id),
        )
        self.conn.commit()

    def set_object_folder(self, oid: str, *, folder_id: Optional[str]) -> None:
        # File an object into a folder, or unfiled (folder_id IS NULL). Scope is
        # enforced by the caller first (#61/#62): the route reads the object with
        # the caller's space/owner filter before issuing this update.
        self.conn.execute(
            "UPDATE objects SET folder_id = ?, updated_at = ? WHERE id = ?",
            (folder_id, self.now(), oid),
        )
        self.conn.commit()

    def folder_child_count(self, fid: str, *, owner_id: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM folders WHERE parent_id = ? AND owner_id = ?",
            (fid, owner_id),
        ).fetchone()["n"])

    def folder_object_count(self, fid: str, *, owner_id: str) -> int:
        # Only live objects keep a folder "non-empty". Live means an object the
        # user can still act on: committed (``available``) plus in-flight
        # uploads (``pending``/``verifying``), which must block the delete
        # because their bytes may still land in the folder. Every other status
        # (deleted, failed, expired, aborted, purging) is a leftover row hidden
        # from the listings (api/object_query.py) but still carrying a
        # ``folder_id``: counting it would refuse the DELETE of a folder the
        # user already sees as empty, forever.
        return int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM objects WHERE folder_id = ? AND owner_id = ? "
            "AND status IN ('available', 'pending', 'verifying')",
            (fid, owner_id),
        ).fetchone()["n"])

    def release_folder_objects(self, fid: str, *, owner_id: str) -> None:
        # Called just before the folder row is deleted, after the counts
        # confirmed no live object remains attached. Detach every leftover row
        # (a dangling ``objects.folder_id`` would break the FK on PostgreSQL)
        # and mark it ``deleted`` so failed/aborted/expired leftovers do not
        # reappear as unfiled rows in the root listing. The guard keeps the
        # live statuses out even if a caller skipped the count check; rows are
        # kept in the catalogue until an explicit purge.
        self.conn.execute(
            "UPDATE objects SET folder_id = NULL, status = 'deleted', updated_at = ? "
            "WHERE folder_id = ? AND owner_id = ? "
            "AND status NOT IN ('available', 'pending', 'verifying')",
            (self.now(), fid, owner_id),
        )
        self.conn.commit()

    def delete_folder(self, fid: str, *, owner_id: str) -> None:
        self.conn.execute(
            "DELETE FROM folders WHERE id = ? AND owner_id = ?", (fid, owner_id)
        )
        self.conn.commit()

    # -- observability (#40, M07) ----------------------------------------
    def ping(self) -> None:
        """Liveness probe for supervision: raises on any backend failure."""
        self.conn.execute("SELECT 1").fetchone()

    def stored_bytes(self) -> int:
        """Verified bytes currently held: available objects only (M07).

        Pending intents still carry ``size_bytes = -1`` and deleted/expired
        rows hold no retrievable bytes, so only ``available`` rows count.
        """
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM objects "
            "WHERE status = 'available'"
        ).fetchone()
        return int(row["n"])

    def space_usage(self, sid: str) -> dict:
        """Real per-space consumption for the M07 usage endpoint."""
        by_status = {
            row["status"]: row["n"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM objects "
                "WHERE space_id = ? GROUP BY status", (sid,)
            ).fetchall()
        }
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes "
            "FROM objects WHERE space_id = ? AND status = 'available'",
            (sid,),
        ).fetchone()
        pending = int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM objects "
            "WHERE space_id = ? AND status = 'pending'", (sid,)
        ).fetchone()["n"])
        return {
            "objects_by_status": by_status,
            "available_count": int(row["n"]),
            "stored_bytes": int(row["bytes"]),
            "pending_count": pending,
        }

    def get_space_quotas(self, sid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM space_quotas WHERE space_id = ?", (sid,)
        ).fetchone())

    def set_space_quotas(
        self, sid: str, storage_bytes: Optional[int],
        egress_bytes_monthly: Optional[int], updated_by: Optional[str],
    ) -> None:
        self.conn.execute(
            "INSERT INTO space_quotas (space_id, storage_bytes, "
            "egress_bytes_monthly, updated_at, updated_by) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(space_id) DO UPDATE SET "
            "storage_bytes = excluded.storage_bytes, "
            "egress_bytes_monthly = excluded.egress_bytes_monthly, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (sid, storage_bytes, egress_bytes_monthly, self.now(), updated_by),
        )
        self.conn.commit()

    def get_space_usage_monthly(self, sid: str, period: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM space_usage_monthly WHERE space_id = ? AND period = ?",
            (sid, period),
        ).fetchone())

    def record_space_egress(
        self, sid: str, period: str, kind: str, size_bytes: int,
    ) -> None:
        """Add one transfer to the month. ``kind`` selects the counter column.

        Called only after a successful intent/redemption. The object size is the
        estimate of bytes transferred: AURA never proxies the bytes, so this is
        a planning figure, not an edge measurement.
        """
        column = {
            "download": "download_intents",
            "preview": "preview_intents",
            "share": "share_redemptions",
        }[kind]
        self.conn.execute(
            "INSERT INTO space_usage_monthly (space_id, period, egress_bytes, "
            f"{column}, updated_at) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(space_id, period) DO UPDATE SET "
            # Qualify the target: PostgreSQL reads a bare RHS `egress_bytes` as
            # ambiguous between the target row and `excluded`.
            "egress_bytes = space_usage_monthly.egress_bytes + excluded.egress_bytes, "
            f"{column} = space_usage_monthly.{column} + 1, "
            "updated_at = excluded.updated_at",
            (sid, period, max(0, int(size_bytes)), self.now()),
        )
        self.conn.commit()


    # -- tags and packs (Sprint 2) --------------------------------------
    def set_object_tags(self, oid: str, tags: list) -> None:
        self.conn.execute("DELETE FROM object_tags WHERE object_id = ?", (oid,))
        self.conn.executemany(
            "INSERT INTO object_tags (object_id, tag) VALUES (?, ?)",
            [(oid, tag) for tag in tags],
        )
        self.conn.commit()

    def get_object_tags(self, oid: str) -> list:
        return [r["tag"] for r in self.conn.execute(
            "SELECT tag FROM object_tags WHERE object_id = ? ORDER BY tag", (oid,)
        ).fetchall()]

    def list_tags_for_objects(self, ids: list) -> dict:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT object_id, tag FROM object_tags WHERE object_id IN ({marks}) "
            "ORDER BY tag", tuple(ids),
        ).fetchall()
        out: dict = {}
        for row in rows:
            out.setdefault(row["object_id"], []).append(row["tag"])
        return out

    def list_tag_counts(
        self, *, space_id: str, owner_id: Optional[str] = None,
        limit: int = 200,
    ) -> list:
        """Distinct tags on objects the caller may list, with their counts.

        The visibility clause comes from the shared object-list grammar, so a
        tag can never reveal an object outside the caller's space/ownership or
        a soft-deleted object. No folder filter: this is the whole vocabulary.
        """
        where, params = build_object_where(
            space_id=space_id, owner_id=owner_id, hide_deleted=True,
        )
        sql = (
            "SELECT t.tag AS tag, COUNT(*) AS n FROM object_tags t "
            "JOIN objects ON objects.id = t.object_id "
            f"WHERE {where} GROUP BY t.tag ORDER BY n DESC, t.tag ASC LIMIT ?"
        )
        return self.conn.execute(sql, params + [limit]).fetchall()

    # -- Shared public rate limits and revocable media grants ---------------
    def rate_hit(self, key: str, *, now: float, window: float, limit: int) -> tuple[bool, int]:
        """Atomically count one hit. Returns ``(allowed, retry_after_seconds)``.

        The counter lives in the catalogue so every API worker enforces the
        same limit; a process-local dict allowed bypassing it with --workers>1.
        """
        self.conn.execute(
            "INSERT INTO public_rate_counters(key, window_start, hits) VALUES(?,?,1) "
            "ON CONFLICT(key) DO UPDATE SET "
            "window_start = CASE WHEN public_rate_counters.window_start < ? "
            "THEN excluded.window_start ELSE public_rate_counters.window_start END, "
            "hits = CASE WHEN public_rate_counters.window_start < ? THEN 1 "
            "ELSE MIN(public_rate_counters.hits + 1, ?) END",
            (key, now, now - window, now - window, limit + 1),
        )
        row = self.conn.execute(
            "SELECT window_start, hits FROM public_rate_counters WHERE key = ?", (key,)
        ).fetchone()
        self.conn.commit()
        if row is None or int(row["hits"]) <= limit:
            return True, 0
        retry = max(1, int(window - (now - float(row["window_start"]))))
        return False, retry

    def rate_peek(self, key: str, *, now: float, window: float, limit: int) -> tuple[bool, int]:
        """Read-only check: has ``key`` exhausted ``limit`` in the current window?"""
        row = self.conn.execute(
            "SELECT window_start, hits FROM public_rate_counters WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return True, 0
        window_start = float(row["window_start"])
        if now - window_start >= window:
            return True, 0
        if int(row["hits"]) < limit:
            return True, 0
        retry = max(1, int(window - (now - window_start)))
        return False, retry

    def rate_clear(self, key: str) -> None:
        """Reset one counter (e.g. after a successful authentication)."""
        self.conn.execute("DELETE FROM public_rate_counters WHERE key = ?", (key,))
        self.conn.commit()

    def clear_rate_counters(self) -> None:
        self.conn.execute("DELETE FROM public_rate_counters")
        self.conn.commit()

    def create_public_access_grant(
        self, token_hash: str, oid: str, space_id: str, actor_id: str,
        created_at: int, expires_at: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO public_access_grants"
            "(token_hash, object_id, space_id, actor_id, created_at, expires_at) "
            "VALUES(?,?,?,?,?,?)",
            (token_hash, oid, space_id, actor_id, created_at, expires_at),
        )
        self.conn.commit()

    def get_public_access_grant(self, token_hash: str):
        return self.conn.execute(
            "SELECT * FROM public_access_grants WHERE token_hash = ?", (token_hash,)
        ).fetchone()

    def revoke_public_access_grant(self, token_hash: str, at: int) -> int:
        cur = self.conn.execute(
            "UPDATE public_access_grants SET revoked_at = ? "
            "WHERE token_hash = ? AND revoked_at IS NULL",
            (at, token_hash),
        )
        self.conn.commit()
        return cur.rowcount

    def revoke_public_access_grants_for_object(self, oid: str, at: int) -> int:
        cur = self.conn.execute(
            "UPDATE public_access_grants SET revoked_at = ? "
            "WHERE object_id = ? AND revoked_at IS NULL",
            (at, oid),
        )
        self.conn.commit()
        return cur.rowcount

    def purge_expired_public_access_grants(self, now: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM public_access_grants WHERE expires_at < ?", (now,)
        )
        self.conn.commit()
        return cur.rowcount

    def create_collection(
        self, cid: str, space_id: str, owner_id: Optional[str], slug: str,
        title: str, description: str,
    ) -> str:
        now = self.now()
        self.conn.execute(
            "INSERT INTO collections (id, space_id, owner_id, slug, title, "
            "description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, space_id, owner_id, slug, title, description, now, now),
        )
        self.conn.commit()
        return cid

    def list_collections(self, space_id: str, owner_id: Optional[str] = None) -> list:
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM collection_items i "
            "WHERE i.collection_id = c.id) AS item_count "
            "FROM collections c WHERE c.space_id = ?"
        )
        params = [space_id]
        if owner_id is not None:
            sql += " AND c.owner_id = ?"
            params.append(owner_id)
        sql += " ORDER BY c.created_at DESC"
        return [_as_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_published_collections_for_object(self, oid: str) -> list:
        """Published packs containing one object (book pages, bounded lookup)."""
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT c.* FROM collections c JOIN collection_items i "
            "ON i.collection_id = c.id WHERE i.object_id = ? "
            "AND c.published_at IS NOT NULL ORDER BY c.updated_at DESC",
            (oid,),
        ).fetchall()]

    def list_published_collections(self) -> list:
        """Published collections for the public portal, newest first.

        Deliberately not scoped to a space: publication is an explicit act and
        the portal must show every pack the operators chose to publish.
        """
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM collection_items i "
            "WHERE i.collection_id = c.id) AS item_count "
            "FROM collections c WHERE c.published_at IS NOT NULL "
            "ORDER BY c.updated_at DESC"
        ).fetchall()]

    def get_collection(self, cid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM collections WHERE id = ?", (cid,)
        ).fetchone())

    def get_collection_by_slug(self, slug: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM collections WHERE slug = ?", (slug,)
        ).fetchone())

    def update_collection(
        self, cid: str, title: str, description: str,
        published_at: Optional[int],
    ) -> None:
        self.conn.execute(
            "UPDATE collections SET title = ?, description = ?, published_at = ?, "
            "updated_at = ? WHERE id = ?",
            (title, description, published_at, self.now(), cid),
        )
        self.conn.commit()

    def replace_collection_items(self, cid: str, object_ids: list) -> None:
        self.conn.execute("DELETE FROM collection_items WHERE collection_id = ?", (cid,))
        self.conn.executemany(
            "INSERT INTO collection_items (collection_id, object_id, position) "
            "VALUES (?, ?, ?)",
            [(cid, oid, pos) for pos, oid in enumerate(object_ids)],
        )
        self.conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?", (self.now(), cid)
        )
        self.conn.commit()

    def get_collection_items(self, cid: str) -> list:
        return [_as_dict(r) for r in self.conn.execute(
            "SELECT o.*, i.position FROM collection_items i "
            "JOIN objects o ON o.id = i.object_id "
            "WHERE i.collection_id = ? ORDER BY i.position", (cid,)
        ).fetchall()]

    def delete_collection(self, cid: str) -> None:
        self.conn.execute("DELETE FROM collection_items WHERE collection_id = ?", (cid,))
        self.conn.execute("DELETE FROM collections WHERE id = ?", (cid,))
        self.conn.commit()


    # -- per-object analytics -------------------------------------------
    def record_object_event(self, oid: str, period: str, kind: str,
                            size_bytes: int, now: int) -> None:
        column = {"view": "views", "download": "downloads",
                  "share": "share_opens"}[kind]
        self.conn.execute(
            "INSERT INTO object_usage_monthly (object_id, period, views, downloads, "
            "share_opens, egress_bytes, last_access_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(object_id, period) DO UPDATE SET "
            f"{column} = object_usage_monthly.{column} + 1, "
            "egress_bytes = object_usage_monthly.egress_bytes + excluded.egress_bytes, "
            "last_access_at = excluded.last_access_at",
            (oid, period,
             1 if kind == "view" else 0,
             1 if kind == "download" else 0,
             1 if kind == "share" else 0,
             max(0, int(size_bytes)), now),
        )
        self.conn.commit()

    def get_object_usage(self, oid: str, period: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM object_usage_monthly WHERE object_id = ? AND period = ?",
            (oid, period),
        ).fetchone())

    def get_object_usage_totals(self, oid: str) -> dict:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(views),0) AS views, "
            "COALESCE(SUM(downloads),0) AS downloads, "
            "COALESCE(SUM(share_opens),0) AS share_opens, "
            "COALESCE(SUM(egress_bytes),0) AS egress_bytes, "
            "MAX(last_access_at) AS last_access_at "
            "FROM object_usage_monthly WHERE object_id = ?", (oid,),
        ).fetchone()
        return _as_dict(row) or {}


    # -- media jobs / HLS ------------------------------------------------
    def get_object_global(self, oid: str):
        return self.conn.execute("SELECT * FROM objects WHERE id = ?", (oid,)).fetchone()

    def enqueue_media_job(self, jid: str, oid: str, kind: str) -> str:
        row = self.conn.execute(
            "SELECT id FROM media_jobs WHERE object_id = ? AND kind = ? "
            "AND status IN ('queued', 'processing') ORDER BY created_at DESC LIMIT 1",
            (oid, kind),
        ).fetchone()
        if row is not None:
            return row["id"]
        now = self.now()
        self.conn.execute(
            "INSERT INTO media_jobs (id, object_id, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (jid, oid, kind, now, now),
        )
        self.conn.commit()
        return jid

    def claim_media_job(self, lease_until: int):
        now = self.now()
        row = self.conn.execute(
            "SELECT * FROM media_jobs WHERE status = 'queued' "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        cur = self.conn.execute(
            "UPDATE media_jobs SET status = 'processing', attempts = attempts + 1, "
            "lease_until = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
            (lease_until, now, row["id"]),
        )
        self.conn.commit()
        return _as_dict(row) if cur.rowcount else None

    def finish_media_job(self, jid: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE media_jobs SET status = ?, error = ?, lease_until = NULL, "
            "updated_at = ? WHERE id = ?", (status, error, self.now(), jid),
        )
        self.conn.commit()

    def get_media_job(self, oid: str, kind: str):
        return _as_dict(self.conn.execute(
            "SELECT * FROM media_jobs WHERE object_id = ? AND kind = ? "
            "ORDER BY created_at DESC LIMIT 1", (oid, kind),
        ).fetchone())

    def set_object_hls(self, oid: str, status: str, prefix: str | None) -> None:
        self.conn.execute(
            "UPDATE objects SET hls_status = ?, hls_prefix = ?, updated_at = ? "
            "WHERE id = ?", (status, prefix, self.now(), oid),
        )
        self.conn.commit()

    def set_object_subtitle(self, oid: str, subtitle_id: str | None) -> None:
        self.conn.execute(
            "UPDATE objects SET subtitle_object_id = ?, updated_at = ? WHERE id = ?",
            (subtitle_id, self.now(), oid),
        )
        self.conn.commit()
    def stats(self) -> dict:
        objects = {
            row["status"]: row["n"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM objects GROUP BY status"
            ).fetchall()
        }
        return {
            "objects_by_status": objects,
            "applications": self.conn.execute(
                "SELECT COUNT(*) AS n FROM applications"
            ).fetchone()["n"],
            "spaces": self.conn.execute("SELECT COUNT(*) AS n FROM spaces").fetchone()["n"],
            "buckets": self.conn.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"],
            "service_identities": self.conn.execute(
                "SELECT COUNT(*) AS n FROM service_identities"
            ).fetchone()["n"],
            "active_service_identities": self.conn.execute(
                "SELECT COUNT(*) AS n FROM service_identities WHERE revoked_at IS NULL"
            ).fetchone()["n"],
        }

    # -- import jobs ------------------------------------------------------
    def create_import_job(
        self, jid: str, space_id: str, application_id: str, created_by: str,
        total_items: int,
    ) -> str:
        now = self.now()
        self.conn.execute(
            "INSERT INTO import_jobs (id, space_id, application_id, created_by, "
            "status, total_items, processed_items, failed_items, summary, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (jid, space_id, application_id or "", created_by, "queued",
             total_items, 0, 0, now, now),
        )
        self.conn.commit()
        return jid

    def get_import_job(self, jid: str, *, space_id: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM import_jobs WHERE id = ? AND space_id = ?",
            (jid, space_id),
        ).fetchone())

    def list_import_jobs(
        self, *, space_id: str, status: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM import_jobs WHERE space_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (space_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM import_jobs WHERE space_id = ? AND status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (space_id, status, limit),
            ).fetchall()
        return [_as_dict(r) for r in rows]

    def update_import_job(
        self, jid: str, *, status: Optional[str] = None,
        processed_items: Optional[int] = None,
        failed_items: Optional[int] = None,
        summary: Optional[str] = None,
        worker_error: Optional[str] = None,
    ) -> None:
        fields = []
        params: list = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if processed_items is not None:
            fields.append("processed_items = ?")
            params.append(processed_items)
        if failed_items is not None:
            fields.append("failed_items = ?")
            params.append(failed_items)
        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)
        if worker_error is not None:
            fields.append("worker_error = ?")
            params.append(worker_error)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(self.now())
        params.append(jid)
        self.conn.execute(
            f"UPDATE import_jobs SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        self.conn.commit()

    def cancel_import_job(self, jid: str, *, space_id: str) -> bool:
        """Mark a queued/running job as cancelled. Idempotent: returns True if
        the job exists and is now cancelled (even if it already was)."""
        row = self.conn.execute(
            "SELECT status FROM import_jobs WHERE id = ? AND space_id = ?",
            (jid, space_id),
        ).fetchone()
        if row is None:
            return False
        if row["status"] == "cancelled":
            return True  # already cancelled: idempotent
        cur = self.conn.execute(
            "UPDATE import_jobs SET status = 'cancelled', updated_at = ?, lease_until = NULL "
            "WHERE id = ? AND space_id = ? AND status IN ('queued', 'running')",
            (self.now(), jid, space_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def claim_import_job(self, now: int, lease_until: int) -> Optional[dict]:
        """Claim the oldest queued job, or a running job whose lease expired.

        Compare-and-set so two workers never process the same job. A crashed
        worker's lease expires and the job is claimed again.
        """
        row = self.conn.execute(
            "SELECT id FROM import_jobs WHERE "
            "status = 'queued' OR (status = 'running' AND "
            "(lease_until IS NULL OR lease_until < ?)) "
            "ORDER BY created_at ASC LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            return None
        cur = self.conn.execute(
            "UPDATE import_jobs SET status = 'running', "
            "attempts = COALESCE(attempts, 0) + 1, "
            "started_at = COALESCE(started_at, ?), "
            "lease_until = ?, worker_error = NULL, updated_at = ? "
            "WHERE id = ? AND (status = 'queued' OR (status = 'running' AND "
            "(lease_until IS NULL OR lease_until < ?)))",
            (now, lease_until, now, row["id"], now),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            return None
        return _as_dict(self.conn.execute(
            "SELECT * FROM import_jobs WHERE id = ?", (row["id"],),
        ).fetchone())

    def renew_import_job_lease(self, jid: str, lease_until: int) -> bool:
        cur = self.conn.execute(
            "UPDATE import_jobs SET lease_until = ?, updated_at = ? "
            "WHERE id = ? AND status = 'running'",
            (lease_until, self.now(), jid),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def get_import_job_by_id(self, jid: str) -> Optional[dict]:
        return _as_dict(self.conn.execute(
            "SELECT * FROM import_jobs WHERE id = ?", (jid,),
        ).fetchone())

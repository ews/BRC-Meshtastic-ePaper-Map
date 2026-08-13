"""Thread-safe friend store backed by a JSON file.

Read by the display loop, written by the web API. Uses a lock to prevent
concurrent read/write corruption and atomic file replacement for writes.
"""

import json
import os
import threading
import time
from pathlib import Path

from burner_emojis import default_emoji, validate_emoji


class FriendStore:
    """CRUD operations on a JSON-backed friend database.

    Thread-safe: all public methods acquire a lock. File writes use a temp
    file + os.replace() for atomicity.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._friends: list[dict] = []
        self._load()

    # ── public read ────────────────────────────────────────────

    def get_friends(self) -> list[dict]:
        """Return a shallow copy of the current friend list."""
        with self._lock:
            return list(self._friends)

    def get_friend_ids(self) -> set[str]:
        """Return the set of whitelisted node IDs."""
        with self._lock:
            return {f["node_id"] for f in self._friends}

    def get_by_id(self, node_id: str) -> dict | None:
        """Return a single friend by node_id, or None."""
        with self._lock:
            for f in self._friends:
                if f["node_id"] == node_id:
                    return dict(f)
        return None

    # ── public write ───────────────────────────────────────────

    def add(
        self, node_id: str, name: str, notes: str = "", emoji: str | None = None
    ) -> dict:
        """Add a friend. Raises ValueError if node_id already exists."""
        node_id = node_id.strip()
        if not node_id.startswith("!") or len(node_id) < 4:
            raise ValueError(f"Invalid node_id: {node_id!r}")

        with self._lock:
            if any(f["node_id"] == node_id for f in self._friends):
                raise ValueError(f"Friend with node_id {node_id} already exists")
            used_emojis = {f["emoji"] for f in self._friends}
            emoji = (
                validate_emoji(emoji)
                if emoji
                else default_emoji(node_id, used_emojis)
            )
            if emoji in used_emojis:
                raise ValueError(f"Emoji {emoji} is already assigned to another friend")
            record = {
                "node_id": node_id,
                "name": name.strip() or node_id,
                "short_name": (name.strip()[:4] if name.strip() else node_id[-4:]),
                "notes": notes.strip(),
                "emoji": emoji,
                "added_at": _now_iso(),
                "last_seen": None,
            }
            self._friends.append(record)
            self._save()
            return dict(record)

    def update(self, node_id: str, **fields) -> dict:
        """Update fields on an existing friend. Returns updated record.

        Allowed fields: name, short_name, notes, emoji.
        Raises KeyError if node_id not found.
        """
        allowed = {"name", "short_name", "notes", "emoji"}
        updates = {k: v for k, v in fields.items() if k in allowed}

        with self._lock:
            for f in self._friends:
                if f["node_id"] == node_id:
                    if "emoji" in updates:
                        emoji = validate_emoji(updates["emoji"])
                        if any(
                            other["node_id"] != node_id
                            and other.get("emoji") == emoji
                            for other in self._friends
                        ):
                            raise ValueError(
                                f"Emoji {emoji} is already assigned to another friend"
                            )
                    f.update(updates)
                    self._save()
                    return dict(f)
            raise KeyError(f"Friend {node_id} not found")

    def remove(self, node_id: str) -> None:
        """Remove a friend by node_id. Raises KeyError if not found."""
        with self._lock:
            before = len(self._friends)
            self._friends = [f for f in self._friends if f["node_id"] != node_id]
            if len(self._friends) == before:
                raise KeyError(f"Friend {node_id} not found")
            self._save()

    def update_last_seen(self, node_id: str) -> None:
        """Update last_seen timestamp for a friend (no-op if unknown)."""
        with self._lock:
            for f in self._friends:
                if f["node_id"] == node_id:
                    f["last_seen"] = _now_iso()
                    # Don't save on every poll — only on explicit writes
                    return

    def flush_last_seen(self) -> None:
        """Persist any pending last_seen updates to disk."""
        with self._lock:
            self._save()

    def count(self) -> int:
        """Return number of friends."""
        with self._lock:
            return len(self._friends)

    # ── internal ───────────────────────────────────────────────

    def _load(self) -> None:
        """Load friends from JSON file. Creates empty file if missing."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._friends = data.get("friends", [])
                changed = self._assign_missing_emojis()
                if changed:
                    self._save()
            except (json.JSONDecodeError, KeyError):
                self._friends = []
        else:
            self._friends = []
            self._save()

    def _assign_missing_emojis(self) -> bool:
        """Migrate missing, invalid, or duplicate emoji values in place."""
        changed = False
        used = set()
        for friend in sorted(self._friends, key=lambda item: item["node_id"]):
            emoji = friend.get("emoji")
            if emoji in used:
                emoji = None
            try:
                validate_emoji(emoji)
            except ValueError:
                emoji = default_emoji(friend["node_id"], used)
            if friend.get("emoji") != emoji:
                friend["emoji"] = emoji
                changed = True
            used.add(emoji)
        return changed

    def _save(self) -> None:
        """Atomic write: temp file → rename."""
        tmp = self._path.with_suffix(".tmp")
        data = {"version": 2, "friends": self._friends}
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, self._path)


def _now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

"""Tests for persistent friend emoji assignment."""

import json

import pytest

from burner_emojis import EMOJIS
from friend_store import FriendStore


def test_add_assigns_and_persists_default_emoji(tmp_path):
    path = tmp_path / "friends.json"
    store = FriendStore(path)

    friend = store.add("!abcd1234", "Alice")
    reloaded = FriendStore(path).get_by_id("!abcd1234")

    assert friend["emoji"] in EMOJIS
    assert reloaded["emoji"] == friend["emoji"]


def test_selected_emoji_can_be_updated_and_cannot_be_duplicated(tmp_path):
    store = FriendStore(tmp_path / "friends.json")
    alice = store.add("!aaaa", "Alice", emoji="♥")
    bob = store.add("!bbbb", "Bob")

    assert alice["emoji"] == "♥"
    assert bob["emoji"] != "♥"
    assert store.update("!aaaa", emoji="★")["emoji"] == "★"
    with pytest.raises(ValueError, match="already assigned"):
        store.update("!bbbb", emoji="★")
    with pytest.raises(ValueError, match="Unsupported emoji"):
        store.update("!bbbb", emoji="🚀")


def test_legacy_file_is_migrated_with_distinct_emojis(tmp_path):
    path = tmp_path / "friends.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "friends": [
                    {"node_id": "!aaaa", "name": "Alice", "last_seen": "old"},
                    {"node_id": "!bbbb", "name": "Bob"},
                ],
            }
        )
    )

    friends = FriendStore(path).get_friends()
    saved = json.loads(path.read_text())

    assert len({friend["emoji"] for friend in friends}) == 2
    assert all("last_seen" not in friend for friend in friends)
    assert saved["version"] == 2


def test_friend_manager_contains_searchable_emoji_picker():
    from friend_server import UI_HTML

    assert 'id="emoji-search"' in UI_HTML
    assert "renderEmojiPicker" in UI_HTML
    assert "__EMOJI_CATALOG__" not in UI_HTML
    assert "last_seen" not in UI_HTML

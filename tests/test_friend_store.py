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

    assert "Channel 1 Locations" in UI_HTML
    assert 'id="emoji-search"' in UI_HTML
    assert "renderEmojiPicker" in UI_HTML
    assert "@media(max-width:680px)" in UI_HTML
    assert "viewport-fit=cover" in UI_HTML
    assert "/api/nodes/" in UI_HTML
    assert "__EMOJI_CATALOG__" not in UI_HTML
    assert "last_seen" not in UI_HTML


def test_channel_node_list_contains_only_source_nodes_with_effective_emojis(tmp_path):
    from friend_server import _list_channel_nodes

    store = FriendStore(tmp_path / "friends.json")
    store.add("!aaaa", "Alice", emoji="♥")
    source = lambda: [
        {
            "node_id": "!aaaa",
            "name": "Alice",
            "brc_address": "09:30+B",
            "position_time": 123,
        },
        {
            "node_id": "!bbbb",
            "name": "Bob",
            "brc_address": "03:00+C",
            "position_time": 456,
        },
    ]

    nodes = _list_channel_nodes(source, store)

    assert [node["node_id"] for node in nodes] == ["!aaaa", "!bbbb"]
    assert nodes[0]["emoji"] == "♥"
    assert nodes[0]["custom_emoji"] is True
    assert nodes[1]["emoji"] in EMOJIS
    assert nodes[1]["custom_emoji"] is False


def test_selecting_node_emoji_creates_and_updates_preference(tmp_path):
    from friend_server import _set_node_emoji

    store = FriendStore(tmp_path / "friends.json")
    source = lambda: [{"node_id": "!aaaa", "name": "Alice"}]

    assert _set_node_emoji(store, source, "!aaaa", "♥")["emoji"] == "♥"
    assert _set_node_emoji(store, source, "!aaaa", "★")["emoji"] == "★"
    with pytest.raises(KeyError):
        _set_node_emoji(store, source, "!missing", "♣")

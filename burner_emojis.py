"""Unicode burner emoji validation and deterministic assignment helpers."""

import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

EMOJI_DATA_PATH = (
    Path(__file__).resolve().parent
    / "vendor"
    / "emoji-mart"
    / "emoji-data.json"
)

# Keep automatic defaults to high-contrast glyphs covered by media/Font.ttc.
EMOJI_OPTIONS = (
    ("★", "Star", "star favorite featured"),
    ("☆", "Outline Star", "outline star favorite"),
    ("☎", "Phone", "phone telephone call"),
    ("♠", "Spade", "spade cards suit"),
    ("♥", "Heart", "heart love favorite"),
    ("♦", "Diamond", "diamond cards suit"),
    ("♣", "Club", "club cards suit"),
    ("♪", "Music", "music note song"),
    ("✧", "Sparkle", "sparkle shine magic"),
    ("♔", "King", "king crown chess"),
    ("♕", "Queen", "queen crown chess"),
    ("♖", "Rook", "rook castle chess"),
    ("♗", "Bishop", "bishop chess"),
    ("♘", "Knight", "knight horse chess"),
    ("♙", "Pawn", "pawn chess"),
)
EMOJIS = tuple(option[0] for option in EMOJI_OPTIONS)


def default_emoji(identity: str, used=()) -> str:
    """Choose a deterministic unused emoji for an identity when possible."""
    used = set(used)
    start = sha256(identity.encode("utf-8")).digest()[0] % len(EMOJIS)
    for offset in range(len(EMOJIS)):
        emoji = EMOJIS[(start + offset) % len(EMOJIS)]
        if emoji not in used:
            return emoji
    return EMOJIS[start]


def validate_emoji(emoji: str) -> str:
    """Return a picker/e-paper-supported Unicode emoji or raise ValueError."""
    if emoji not in supported_emojis():
        raise ValueError(f"Unsupported emoji: {emoji!r}")
    return emoji


@lru_cache(maxsize=1)
def supported_emojis() -> frozenset[str]:
    """Load the self-hosted picker's native Unicode values once."""
    values = set(EMOJIS)
    try:
        records = json.loads(EMOJI_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset(values)
    for record in records.get("emojis", {}).values():
        values.update(
            skin["native"]
            for skin in record.get("skins", ())
            if skin.get("native")
        )
    return frozenset(values)

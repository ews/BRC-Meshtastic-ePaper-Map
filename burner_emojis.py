"""E-paper-safe burner emoji catalog and deterministic assignment helpers."""

from hashlib import sha256

# Keep this catalog to glyphs covered by media/Font.ttc. The search terms feed
# the friend manager's searchable picker.
EMOJI_OPTIONS = (
    ("★", "Star", "star favorite featured"),
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
    """Return a supported emoji or raise ValueError."""
    if emoji not in EMOJIS:
        raise ValueError(f"Unsupported emoji: {emoji!r}")
    return emoji


def emoji_catalog() -> list[dict]:
    """Return JSON-ready picker metadata."""
    return [
        {"symbol": symbol, "name": name, "keywords": keywords}
        for symbol, name, keywords in EMOJI_OPTIONS
    ]

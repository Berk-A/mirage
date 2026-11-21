"""Output classification for served-model replies.

Pure functions, no I/O. A locally-served model — even an abliterated one — can still
emit a refusal, a moralizing deflection, or plain junk (empty / truncated) output.
The studio uses these helpers to decide whether a draft is worth keeping or should be
regenerated, independent of how the text was transported (that is `content.llm`'s job).

Labels returned by `classify_output`:

    "ok"        usable text (non-empty, not a refusal, long enough)
    "empty"     blank or whitespace-only
    "refusal"   matches a refusal / moralizing phrase (checked before length, so a
                short refusal is labelled "refusal", not "too_short")
    "too_short" fewer than MIN_USABLE_CHARS non-whitespace characters and not a refusal

Thresholds:
    MIN_USABLE_CHARS = 15  — a reply with fewer than 15 non-space characters carries
    no real content for an email/chat draft, so it is treated as junk.
"""
from __future__ import annotations

import re

# A usable draft needs at least this many non-whitespace characters. Below it there
# is not enough text to be a real message, so we flag it as "too_short".
MIN_USABLE_CHARS = 15

# Case-insensitive substrings that mark a refusal or a moralizing deflection. These
# are the shapes a served model (abliterated or not) can still slip out. Apostrophes
# are normalized to straight quotes before matching, so curly-quote variants match too.
REFUSAL_PATTERNS: tuple[str, ...] = (
    "i can't help",
    "i cannot help",
    "i won't",
    "i will not",
    "i'm not able to",
    "i am unable",
    "i cannot assist",
    "against my guidelines",
    "as an ai",
    "i must decline",
    "i'm sorry, but",
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase and fold curly apostrophes to straight ones for matching."""
    return text.lower().replace("’", "'").replace("ʼ", "'")


def _non_space_len(text: str) -> int:
    return len(_WHITESPACE.sub("", text))


def is_refusal(text: str) -> bool:
    """True if `text` contains any known refusal / moralizing phrase."""
    normalized = _normalize(text)
    return any(pattern in normalized for pattern in REFUSAL_PATTERNS)


def classify_output(text: str) -> str:
    """Classify a model reply as one of: "ok", "empty", "too_short", "refusal".

    Order matters: empty wins first, then refusal (so a terse refusal is not mislabelled
    "too_short"), then the length check, else "ok".
    """
    if text is None or not text.strip():
        return "empty"
    if is_refusal(text):
        return "refusal"
    if _non_space_len(text) < MIN_USABLE_CHARS:
        return "too_short"
    return "ok"


def is_usable(text: str) -> bool:
    """True only when `classify_output` returns "ok"."""
    return classify_output(text) == "ok"

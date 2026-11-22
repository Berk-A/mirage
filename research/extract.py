"""Extraction: `RawDoc` → typed `Fact` triples, each stamped with source URL + dates +
confidence.

Design stance — **conservative**. The rubric deducts up to 5 points for facts a run gets
wrong, so a missed fact is cheaper than a wrong one. Every rule is anchored on the seed
(the target's name/aliases/company) and on text actually present in the doc; we never
guess. Two early versions of this extractor over-reached — scanning arbitrary news prose
for SaaS-tool names produced a false "uses Stripe", and word-level topic picking produced
junk hooks like "nets". Both are gone: tool/vendor facts come only from sources that
genuinely reveal the stack (a GitHub account the person demonstrably uses; GitHub repo
languages), and hooks come from a *classified headline*, not loose words.

Confidence calibration:
  structured field (GitHub language/company) .... 0.85
  role keyword next to the name/company ......... 0.70
  colleague co-mentioned on an on-topic page .... 0.60
  recent coverage/activity (dated headline) ..... 0.50

`Fact` is our triple: (subject, predicate, object_value) + a natural-language
`canonical_claim` (what grounding matches and what a hook ships as). `observed_date` is
when we fetched; `event_date` is when the content is from (drives recency).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Iterable, Optional

from core.models import Fact
from research.sources import RawDoc, Seed

# --------------------------------------------------------------------------- #
# Lexicons
# --------------------------------------------------------------------------- #
ROLE_TERMS = [
    "co-founder & co-ceo", "co-founder and co-ceo", "co-founder & ceo", "co-founder",
    "cofounder", "founder", "co-ceo", "ceo", "cto", "coo", "cfo", "cpo",
    "chief technology officer", "chief executive officer", "chief product officer",
    "managing director", "head of", "vp of", "vice president",
]

# SaaS tools with a real login page → believable landing-page surface. Mapped to their
# real login host (for reference; the decider builds a *registerable lookalike* from the
# name, never the real domain). Only emitted from stack-revealing sources.
TOOL_LEXICON: dict[str, tuple[str, str]] = {
    "gitlab": ("GitLab", "gitlab.com"),
    "slack": ("Slack", "slack.com"),
    "notion": ("Notion", "notion.so"),
    "figma": ("Figma", "figma.com"),
    "linear": ("Linear", "linear.app"),
    "jira": ("Jira", "atlassian.net"),
    "atlassian": ("Atlassian", "atlassian.net"),
    "aws": ("AWS", "aws.amazon.com"),
    "google cloud": ("Google Cloud", "cloud.google.com"),
    "azure": ("Microsoft Azure", "portal.azure.com"),
    "salesforce": ("Salesforce", "salesforce.com"),
    "hubspot": ("HubSpot", "hubspot.com"),
    "datadog": ("Datadog", "datadoghq.com"),
    "sentry": ("Sentry", "sentry.io"),
    "vercel": ("Vercel", "vercel.com"),
    "github": ("GitHub", "github.com"),
    "cloudflare": ("Cloudflare", "cloudflare.com"),
    "docker": ("Docker", "docker.com"),
    "mongodb": ("MongoDB", "cloud.mongodb.com"),
    "grafana": ("Grafana", "grafana.com"),
    "stackit": ("STACKIT", "stackit.cloud"),
    "personio": ("Personio", "personio.de"),
    "kubernetes": ("Kubernetes", "kubernetes.io"),
    "terraform": ("Terraform", "app.terraform.io"),
}

# Account-footprint classification (holehe/maigret hits). A hit names a *service* (a
# maigret site name like "GitHub", or a holehe domain like "github.com"). We keep this
# conservative on purpose: a username/email footprint turns up dozens of sites, but only
# two kinds are worth a fact —
#   * a real SaaS *login* the founder plausibly uses  → a `uses_tool`/Vendor surface;
#   * a social/presence *platform*                    → a channel/rapport hook.
# Everything else (the long tail of forums, music sites, parked handles) is dropped.
# Keys are matched as substrings of the normalised (alnum-lowercased) service token, so
# both "GitHub" and "github.com" resolve to the same entry.
_ACCOUNT_VENDORS: dict[str, str] = {
    "github": "GitHub", "gitlab": "GitLab", "slack": "Slack", "notion": "Notion",
    "figma": "Figma", "linear": "Linear", "atlassian": "Atlassian", "jira": "Jira",
    "dropbox": "Dropbox", "zoom": "Zoom", "docker": "Docker", "calendly": "Calendly",
    "huggingface": "HuggingFace", "trello": "Trello", "asana": "Asana",
    "bitbucket": "Bitbucket", "gmail": "Google", "googl": "Google",
    "microsoft": "Microsoft", "office": "Microsoft", "replit": "Replit",
    "vercel": "Vercel", "cloudflare": "Cloudflare", "heroku": "Heroku",
}
_ACCOUNT_PLATFORMS: dict[str, str] = {
    "twitter": "X", "xcom": "X", "instagram": "Instagram", "linkedin": "LinkedIn",
    "reddit": "Reddit", "medium": "Medium", "mastodon": "Mastodon", "bsky": "Bluesky",
    "bluesky": "Bluesky", "tiktok": "TikTok", "youtube": "YouTube", "facebook": "Facebook",
    "telegram": "Telegram", "discord": "Discord", "threads": "Threads",
    "pinterest": "Pinterest", "tumblr": "Tumblr", "twitch": "Twitch", "devto": "Dev.to",
    "soundcloud": "SoundCloud", "spotify": "Spotify", "producthunt": "Product Hunt",
    "keybase": "Keybase", "stackoverflow": "Stack Overflow", "wordpress": "WordPress",
}

# Known investors/VCs → high-signal "backed by" pretexts. A named VC is a strong,
# flattering intro topic. We also capture generic "<Name> Capital/Ventures/Partners"
# phrases after a funding trigger, but only when they look like a firm (see _investors_in).
INVESTOR_LEXICON = [
    "Merantix Capital", "Project A", "Cherry Ventures", "HV Capital",
    "Earlybird", "La Famiglia", "Speedinvest", "Point Nine", "Index Ventures",
    "Accel", "Sequoia", "Balderton", "Lightspeed", "General Catalyst", "Y Combinator",
    "Insight Partners", "Atomico", "Northzone", "Creandum", "Bessemer",
]

# Phrases that genuinely reveal a stack (job posts, eng pages), so a tool named right
# after one is a real signal rather than incidental news prose.
_STACK_TRIGGERS = (
    "we use", "we're using", "we are using", "built with", "built on", "powered by",
    "our stack", "tech stack", "stack:", "we work with", "we rely on", "running on",
    "experience with", "proficient in", "familiarity with", "knowledge of",
    "hands-on with", "deployed on", "hosted on", "runs on", "we host", "we build",
    "infrastructure:", "we deploy",
)

# "backed by X", "raised €N from X", "led by X", "investors: X" → capture the firm.
_INVESTOR_TRIGGER_RE = re.compile(
    r"(?:backed by|led by|participation from|investors?(?:\s+include)?:?|"
    r"raised[^.]{0,40}?from|funded by)\s+"
    r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})"
)
_FIRM_SUFFIX_RE = re.compile(r"\b(Capital|Ventures|Partners|Fund|Group|Labs|Holdings)\b")
# A funding amount in € / $ with a magnitude word.
_MONEY_RE = re.compile(
    r"(?:€|eur\s*|\$|usd\s*)\s*\d{1,4}(?:[.,]\d+)?\s*(?:million|mio|m\b|billion|bn\b)",
    re.I,
)

PROGRAMMING_LANGS = {
    "python", "typescript", "javascript", "go", "rust", "java", "kotlin", "swift",
    "ruby", "c++", "c#", "php", "scala", "elixir", "dart",
}

# Headline event classes → a clean hook topic. Checked in order.
_EVENT_CLASSES: list[tuple[str, tuple[str, ...]]] = [
    ("the recent funding round",
     ("raise", "raises", "raised", "million", "seed", "funding", "€", "investment", "round", "secures")),
    ("their recent talk or interview",
     ("keynote", "panel", "conference", "speaks", "speaker", "talk", "fireside",
      "podcast", "interview", "episode", "webinar", "fireside", "q&a", "ama")),
    ("the recent product launch",
     ("launch", "launches", "unveils", "release", "releases", "introduc")),
    ("the company's growth",
     ("hiring", "hires", "joins", "expand", "grows", "office", "team")),
]

_SITE_SUFFIX = re.compile(r"\s[-–|]\s[^-–|]{1,40}$")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def extract(doc: RawDoc, seed: Seed) -> list[Fact]:
    if doc.source_type == "github":
        facts = _extract_github(doc, seed)
    elif doc.source_type == "feed":
        facts = _extract_feed(doc, seed)
    elif doc.source_type in ("holehe", "maigret"):
        facts = _extract_account(doc, seed)
    else:  # web, search, talk, ...
        facts = _extract_web(doc, seed)
    return [f for f in facts if f.object_value.strip() and f.canonical_claim.strip()]


def extract_all(docs: Iterable[RawDoc], seed: Seed) -> list[Fact]:
    out: list[Fact] = []
    for doc in docs:
        out.extend(extract(doc, seed))
    return out


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def _extract_web(doc: RawDoc, seed: Seed) -> list[Fact]:
    facts: list[Fact] = []
    low = doc.text.lower()
    name = seed.name
    about_target = _mentions_target(low, seed)
    about_company = bool(seed.company) and seed.company.lower() in low
    if not (about_target or about_company):
        return facts  # page isn't about the target or their company — extract nothing

    if about_target:
        role = _find_role(doc.text, seed)
        if role:
            facts.append(_fact(seed, "role_is", role, doc,
                               claim=f"{name} is {role}.", confidence=0.7))
        if about_company:
            facts.append(_fact(seed, "works_at", seed.company, doc,
                               claim=f"{name} works at {seed.company}.", confidence=0.7))

        # Colleagues co-mentioned here → the most credible senders.
        for colleague in _colleagues_in(low, seed):
            facts.append(_fact(seed, "colleague_of", colleague, doc,
                               claim=f"{name} and {colleague} both work at {seed.company or 'the same company'}.",
                               confidence=0.6))

    # main-side: structured event facts (talks, launches, coverage).
    if about_target or about_company:
        facts.extend(_extract_event_facts(doc, seed))

    # Recent coverage / talk / launch → a clean hook. A publish date makes it a dated
    # (recency-ranked) hook; without one we still surface strong event classes, undated.
    topic = _event_class_topic(doc.title or "") or _event_class_topic(doc.text)
    if topic and (about_target or about_company):
        host = _host(doc.url)
        headline = (doc.title or "").strip()
        when = f"On {doc.published_date}, " if doc.published_date else ""
        facts.append(_fact(seed, "engaged_with", topic, doc,
                           claim=f'{when}{name} and {seed.company or "their company"} '
                                 f'were covered by {host}'
                                 f'{": " + chr(34) + headline + chr(34) if headline else ""}.',
                           confidence=0.5 if doc.published_date else 0.45,
                           event_date=doc.published_date))

    # Investor / funding / stack facts (snippets and first-party pages carry these).
    if about_target or about_company:
        facts.extend(_investor_facts(doc, seed))
        facts.extend(_stack_facts(doc, seed))
    return facts


def _extract_event_facts(doc: RawDoc, seed: Seed) -> list[Fact]:
    """Extract only explicit dated attendance or scheduled-event statements.

    Article publication dates do not prove that a person attended an event, so this
    requires both a strong participation phrase and a date in the visible source text.
    """
    text = f"{doc.title}. {doc.text}"
    low = text.casefold()
    scheduled = re.search(
        r"\b(?:will speak|will be speaking|will present|will attend|will join|"
        r"scheduled to speak|scheduled as a speaker|will be a speaker)\b", low
    )
    spoke = re.search(r"\b(?:spoke at|presented at|joined the panel at)\b", low)
    attended = re.search(r"\b(?:attended|participated in)\b", low)
    if not scheduled and not spoke and not attended:
        return []
    statement = scheduled or spoke or attended
    event_date = _explicit_date_near(text, statement)
    if event_date is None:
        return []
    try:
        event_day = date.fromisoformat(event_date)
    except ValueError:
        return []
    if scheduled and event_day >= date.today():
        predicate = "scheduled_for"
        claim_verb = "is scheduled to speak at"
    elif spoke:
        predicate = "spoke_at"
        claim_verb = spoke.group(0)
    elif attended:
        predicate = "attended_event"
        claim_verb = attended.group(0)
    else:
        return []

    event_name = _SITE_SUFFIX.sub("", (doc.title or "").strip()).strip(" -–|.")
    if not event_name:
        return []
    host = _host(doc.url)
    claim = (f"The source {host} says {seed.name} {claim_verb} "
             f'"{event_name}" on {event_date}.')
    return [_fact(seed, predicate, event_name, doc, claim=claim, confidence=0.75,
                  event_date=event_date)]


def _explicit_date_near(text: str, statement: re.Match) -> Optional[str]:
    candidates = (
        r"\b20\d{2}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+[A-Za-z]+\s+20\d{2}\b",
        r"\b[A-Za-z]+\s+\d{1,2},?\s+20\d{2}\b",
    )
    formats = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y",
               "%B %d %Y", "%b %d, %Y", "%b %d %Y")
    found: list[tuple[int, str]] = []
    for pattern in candidates:
        for match in re.finditer(pattern, text):
            raw = match.group(0)
            for fmt in formats:
                try:
                    found.append((match.start(), datetime.strptime(raw, fmt).date().isoformat()))
                    break
                except ValueError:
                    continue
    if not found:
        return None
    position, parsed = min(found, key=lambda item: abs(item[0] - statement.end()))
    return parsed if abs(position - statement.end()) <= 180 else None


def _extract_feed(doc: RawDoc, seed: Seed) -> list[Fact]:
    facts: list[Fact] = []
    name = seed.name
    topic = _headline_topic(doc.title or doc.text, seed)
    if topic:
        host = _host(doc.url)
        facts.append(_fact(seed, "engaged_with", topic, doc,
                           claim=f'{name} published/was featured in "{(doc.title or topic).strip()}"'
                                 f'{(" on " + doc.published_date) if doc.published_date else ""} ({host}).',
                           confidence=0.5, event_date=doc.published_date))
    return facts


def _extract_github(doc: RawDoc, seed: Seed) -> list[Fact]:
    facts: list[Fact] = []
    meta = doc.meta or {}
    kind = meta.get("kind")
    name = seed.name

    # The person demonstrably uses GitHub → a real, high-confidence landing surface.
    facts.append(_fact(seed, "uses_tool", "GitHub", doc,
                       claim=f"{name} has a GitHub account.", confidence=0.9))

    if kind == "profile":
        company = _github_field(doc.text, "Company")
        if company:
            company = company.lstrip("@").strip()
            facts.append(_fact(seed, "works_at", company, doc,
                               claim=f"{name} lists {company} as their company on GitHub.",
                               confidence=0.85))

    elif kind == "repo":
        language = str(meta.get("language") or "").strip()
        repo_name = str(meta.get("name") or "").strip()
        if language and language.lower() in PROGRAMMING_LANGS:
            # A language is stack, not a login surface → its own predicate.
            facts.append(_fact(seed, "uses_language", language, doc,
                               claim=f"{name} works with {language}.", confidence=0.85,
                               event_date=doc.published_date))
        if repo_name:
            facts.append(_fact(seed, "works_on", repo_name, doc,
                               claim=f"{name} maintains the {repo_name} project on GitHub.",
                               confidence=0.6, event_date=doc.published_date))
        # SaaS tools named in a repo description are genuine stack signals.
        for display, _host in _tools_in(doc.text.lower()):
            facts.append(_fact(seed, "uses_tool", display, doc,
                               claim=f"{name}'s project uses {display}.", confidence=0.55,
                               event_date=doc.published_date))
    return facts


def _extract_account(doc: RawDoc, seed: Seed) -> list[Fact]:
    """holehe/maigret hit → at most one fact, and only for a recognised login or platform.

    The underlying signal is a *guess*: the probed email/username was derived from the
    public name, so a hit does not prove the account is the founder's. Confidence is kept
    low to reflect that, and the long tail of unrecognised sites yields nothing."""
    meta = doc.meta or {}
    service = str(meta.get("service") or meta.get("site") or "").strip()
    if not service:
        return []
    via = str(meta.get("via") or doc.source_type)
    url = doc.url
    name = seed.name
    kind, display = _classify_account(service)
    if kind == "vendor":
        # A real login surface the founder plausibly uses → vendor landing-page material.
        how = ("registered to their work email" if via == "holehe"
               else "under a handle they would use")
        return [_fact(seed, "uses_tool", display, doc,
                      claim=f"{name} has a {display} account ({how}).",
                      confidence=0.45)]
    if kind == "platform":
        # A social/presence footprint → a channel/rapport hook (where to reach them).
        return [_fact(seed, "engaged_with", f"their presence on {display}", doc,
                      claim=f"{name} is active on {display} ({url}).",
                      confidence=0.4)]
    return []


def _classify_account(service: str) -> tuple[Optional[str], Optional[str]]:
    """Map a service name/domain to ('vendor'|'platform', display) or (None, None).
    Vendors win ties (a login surface is the higher-value classification)."""
    norm = re.sub(r"[^a-z0-9]", "", service.lower())
    if not norm:
        return None, None
    for key, display in _ACCOUNT_VENDORS.items():
        if key in norm:
            return "vendor", display
    for key, display in _ACCOUNT_PLATFORMS.items():
        if key in norm:
            return "platform", display
    return None, None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mentions_target(low_text: str, seed: Seed) -> bool:
    for n in [seed.name, *seed.aliases]:
        n = n.strip().lower()
        if not n:
            continue
        if n in low_text:
            return True
        last = n.split()[-1]
        if len(last) > 3 and re.search(rf"\b{re.escape(last)}\b", low_text):
            return True
    return False


def _colleagues_in(low_text: str, seed: Seed) -> list[str]:
    found: list[str] = []
    for colleague in seed.colleagues:
        c = colleague.strip()
        if not c:
            continue
        last = c.split()[-1].lower()
        if c.lower() in low_text or (len(last) > 3 and re.search(rf"\b{re.escape(last)}\b", low_text)):
            if c not in found:
                found.append(c)
    return found


def _find_role(text: str, seed: Seed, *, max_gap: int = 45) -> Optional[str]:
    """Return the role term NEAREST a mention of the target, within `max_gap` chars.

    Nearest-wins (not first-senior-wins) so that when two people are listed back-to-back
    — e.g. "Robert Seilbeck · CTO  Tom Müller · CEO" — the target gets their own title,
    not the neighbour's. Ties break toward the longer (more specific) term.
    """
    low = text.lower()
    names = [seed.name.lower()] + [a.lower() for a in seed.aliases]
    last = seed.name.split()[-1].lower() if seed.name else ""
    if last:
        names.append(last)
    name_spans = []
    for n in names:
        if len(n) < 3:
            continue
        name_spans.extend(m.start() for m in re.finditer(rf"\b{re.escape(n)}\b", low))
    if not name_spans:
        return None

    best_term: Optional[str] = None
    best_gap = max_gap + 1
    for term in ROLE_TERMS:
        for m in re.finditer(re.escape(term), low):
            gap = min(abs(m.start() - p) for p in name_spans)
            if gap < best_gap or (gap == best_gap and best_term and len(term) > len(best_term)):
                best_gap, best_term = gap, term
    return _titlecase_role(best_term) if best_term and best_gap <= max_gap else None


def _titlecase_role(term: str) -> str:
    specials = {"ceo", "cto", "coo", "cfo", "cpo", "vp"}
    words = []
    for w in term.split():
        if w.strip("&").lower() in specials:
            words.append(w.upper())
        elif w == "&":
            words.append("&")
        else:
            words.append(w.capitalize())
    return " ".join(words)


def _tools_in(low_text: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for key, (display, host) in TOOL_LEXICON.items():
        if re.search(rf"\b{re.escape(key)}\b", low_text):
            found[display] = host
    return sorted(found.items())


def _event_class_topic(text: str) -> Optional[str]:
    """Classify text into a known event-class hook topic, or None. Unlike
    `_headline_topic` this never falls back to a loose capitalised phrase, so it is safe
    to run on a snippet with no publish date without inventing a junk hook."""
    if not text:
        return None
    low = text.lower()
    for topic, keywords in _EVENT_CLASSES:
        if any(k in low for k in keywords):
            return topic
    return None


def _investors_in(text: str) -> list[str]:
    """Named investors/VCs backing the company. Lexicon hits + "backed by <Firm>"
    captures, kept conservative: a captured phrase must look like a firm."""
    found: list[str] = []

    def _add(name: str) -> None:
        name = name.strip().rstrip(".,;:")
        if not name:
            return
        # skip if it's a substring of, or a superset of, something already kept
        for existing in found:
            if name.lower() in existing.lower() or existing.lower() in name.lower():
                return
        found.append(name)

    for inv in INVESTOR_LEXICON:
        if re.search(rf"\b{re.escape(inv)}\b", text):
            _add(inv)
    for m in _INVESTOR_TRIGGER_RE.finditer(text):
        cand = m.group(1).strip().rstrip(".,;:")
        if _FIRM_SUFFIX_RE.search(cand) or cand in INVESTOR_LEXICON:
            _add(cand)
    return found[:5]


def _investor_facts(doc: RawDoc, seed: Seed) -> list[Fact]:
    facts: list[Fact] = []
    company = seed.company or "the company"
    for inv in _investors_in(doc.text):
        facts.append(_fact(seed, "engaged_with", f"their investor {inv}", doc,
                           claim=f"{company} is backed by {inv}.",
                           confidence=0.55, event_date=doc.published_date))
    m = _MONEY_RE.search(doc.text)
    if m and re.search(r"\b(raise[ds]?|secur|nets|funding|round|invest)", doc.text.lower()):
        amount = re.sub(r"\s+", " ", m.group(0).strip())
        facts.append(_fact(seed, "engaged_with", "the recent funding round", doc,
                           claim=f"{company} raised {amount}.",
                           confidence=0.55, event_date=doc.published_date))
    return facts


def _stack_facts(doc: RawDoc, seed: Seed) -> list[Fact]:
    company = seed.company or "The company"
    facts: list[Fact] = []
    for display, _host in _stack_tools_in(doc.text):
        facts.append(_fact(seed, "uses_tool", display, doc,
                           claim=f"{company} uses {display}.",
                           confidence=0.55, event_date=doc.published_date))
    return facts


def _stack_tools_in(text: str) -> list[tuple[str, str]]:
    """Tools named within a stack-revealing window (after a `_STACK_TRIGGERS` phrase).
    Window-gated to avoid the classic false positive of a tool name in incidental prose."""
    low = text.lower()
    found: dict[str, str] = {}
    for trig in _STACK_TRIGGERS:
        for m in re.finditer(re.escape(trig), low):
            window = low[m.end(): m.end() + 160]
            for key, (display, host) in TOOL_LEXICON.items():
                if re.search(rf"\b{re.escape(key)}\b", window):
                    found[display] = host
    return sorted(found.items())


def _headline_topic(title: str, seed: Seed) -> Optional[str]:
    """Classify a headline into a clean, accurate hook topic. Prefer a known event class;
    never return the company/target name alone or a bare verb."""
    if not title:
        return None
    low = title.lower()
    for topic, keywords in _EVENT_CLASSES:
        if any(k in low for k in keywords):
            return topic
    # Fallback: a trimmed capitalised phrase that isn't just the company/person name.
    cleaned = _SITE_SUFFIX.sub("", title).strip()
    drop = {seed.company.lower(), *(a.lower() for a in seed.aliases), seed.name.lower()}
    tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", cleaned)]
    caps = [t for i, t in enumerate(tokens)
            if t[:1].isupper() and t.lower() not in drop and i > 0]
    for i in range(len(caps) - 1):
        return f"{caps[i]} {caps[i+1]}"
    return None


def _host(url: str) -> str:
    m = re.search(r"https?://([^/]+)/?", url)
    return m.group(1) if m else url


def _github_field(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}:\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _fact(seed: Seed, predicate: str, object_value: str, doc: RawDoc, *,
          claim: str, confidence: float, event_date: Optional[str] = None) -> Fact:
    object_value = object_value.strip()
    return Fact(
        id=_fact_id(seed.target_id, predicate, object_value, doc.url),
        subject=seed.target_id,
        predicate=predicate,
        object_value=object_value,
        canonical_claim=claim.strip(),
        source_url=doc.url,
        observed_date=doc.fetched_date,
        event_date=event_date or doc.published_date,
        confidence=max(0.0, min(1.0, confidence)),
    )


def _fact_id(subject: str, predicate: str, object_value: str, url: str) -> str:
    h = hashlib.sha1(
        f"{subject}|{predicate}|{object_value.lower()}|{url}".encode("utf-8")
    ).hexdigest()[:10]
    return f"f_{h}"

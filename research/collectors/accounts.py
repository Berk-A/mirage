"""Account-footprint collectors — the "where are they actually registered / active"
tier of the OSINT funnel.

Two tools, same `research.sources.Collector` protocol (seed → list[RawDoc]):

  * `HoleheCollector` (source_type="holehe") probes a small set of the *most likely*
    work-email patterns for the founder against holehe, which checks ~120 sites for a
    "this email is registered here" signal (no password, no email sent). One RawDoc per
    POSITIVE hit.
  * `MaigretCollector` (source_type="maigret") probes a small set of likely usernames
    against maigret, which checks hundreds of sites for an account with that handle. One
    RawDoc per found account.

Both are **guesses about identity**: the email/username is derived from the public name,
so a hit is a *candidate* signal, not proof the account is the founder's. Extraction
keeps the confidence low accordingly.

Design, mirroring the existing collectors (`github.py`, `brightdata.py`, `search.py`):
  * resilient by construction — missing tool, timeout, non-zero exit, or a parse error
    all degrade to `[]` and never raise (a dead tool must never sink the run);
  * the probe itself is an injectable seam (`probe=`), so the collector is unit-testable
    with no tool installed and no network;
  * probes are CAPPED and subprocess timeouts generous; results are CACHED to
    `runs/osint_cache/<tool>_<target>.json` so re-runs never re-probe the network;
  * gated by `holehe_available()` / `maigret_available()` (console script on PATH / in
    the active venv, or the importable module), so `default_provider()` only wires them
    in when the tool is actually installed.

Scope stays the three consenting founders (the authorized sandbox); nothing here
contacts a real person — holehe/maigret only ask third-party *sites* whether a handle or
email is known to them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from research.sources import Collector, RawDoc, Seed, today_iso

# A probe returns a list of hit dicts. For holehe: {"service", "url", "email"}. For
# maigret: {"site", "url", "username"}. The collector turns each into one RawDoc.
HoleheProbeFn = Callable[[str, float], list]   # (email, timeout) -> hits
MaigretProbeFn = Callable[[str, float, int], list]  # (username, timeout, top_sites) -> hits

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Transliterate German umlauts so a derived local-part/handle is a plain registerable
# string (Tom Müller -> tommueller), same table the graph uses for lookalike addresses.
_UMLAUT = str.maketrans({"ü": "ue", "ö": "oe", "ä": "ae", "ß": "ss",
                         "Ü": "ue", "Ö": "oe", "Ä": "ae"})

CACHE_DIR = Path("runs/osint_cache")


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _name_parts(name: str) -> list[str]:
    cleaned = name.strip().translate(_UMLAUT)
    return [re.sub(r"[^a-z0-9]", "", p.lower()) for p in cleaned.split() if p.strip()]


def _company_domain(seed: Seed) -> Optional[str]:
    """The founder's real work-email domain (e.g. revel8.ai), discovered from the seed.

    Prefer an explicit `seed.domains` entry; otherwise find a host in the seed's known
    URLs that carries the company slug (revel8.ai shows up in `unlock_urls`). We need the
    REAL domain here — a lookalike can't receive the founder's real registrations, so it
    is useless for probing."""
    slug = re.sub(r"[^a-z0-9]", "", seed.company.lower())
    for dom in seed.domains:
        host = dom.lower().replace("https://", "").replace("http://", "").split("/")[0]
        host = host[4:] if host.startswith("www.") else host
        if host:
            return host
    for url in (*seed.urls, *seed.unlock_urls):
        host = url.lower().replace("https://", "").replace("http://", "").split("/")[0]
        host = host[4:] if host.startswith("www.") else host
        if slug and slug in host.replace(".", ""):
            return host
    return None


def _candidate_emails(seed: Seed, *, cap: int = 4) -> list[str]:
    """The <=cap most likely work-email patterns for the founder at the company domain."""
    domain = _company_domain(seed)
    parts = _name_parts(seed.name)
    if not domain or not parts:
        return []
    first = parts[0]
    last = parts[-1]
    locals_: list[str] = [first]
    if last != first:
        locals_ += [f"{first}.{last}", f"{first[0]}{last}", f"{first}{last}"]
    out: list[str] = []
    seen: set[str] = set()
    for lp in locals_:
        email = f"{lp}@{domain}"
        if email not in seen:
            seen.add(email)
            out.append(email)
        if len(out) >= cap:
            break
    return out


def _candidate_usernames(seed: Seed, extra: tuple[str, ...] = (), *, cap: int = 3) -> list[str]:
    """The <=cap most likely handles for the founder, from the name (+ any passed-in
    handles already known, e.g. a LinkedIn slug lifted from the dossier)."""
    parts = _name_parts(seed.name)
    cands: list[str] = []
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        cands += [f"{first}-{last}", f"{first[0]}{last}", f"{first}{last}"]
    elif parts:
        cands.append(parts[0])
    cands = [*extra, *cands]
    out: list[str] = []
    seen: set[str] = set()
    for u in cands:
        u = re.sub(r"[^a-z0-9._-]", "", u.lower())
        if u and u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= cap:
            break
    return out


def _cache_path(tool: str, target_id: str) -> Path:
    return CACHE_DIR / f"{tool}_{target_id}.json"


def _load_cache(tool: str, target_id: str) -> Optional[dict]:
    path = _cache_path(tool, target_id)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("hits"), list):
            return data
    except (OSError, ValueError):
        return None
    return None


def _save_cache(tool: str, target_id: str, probes: list[str], hits: list[dict]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(tool, target_id).open("w", encoding="utf-8") as fh:
            json.dump(
                {"tool": tool, "target_id": target_id, "probes": probes,
                 "hits": hits, "cached_at": today_iso()},
                fh, indent=2, ensure_ascii=False,
            )
    except OSError:
        pass  # caching is a nicety; failing to write it must not break the run


def _console_script(name: str) -> Optional[str]:
    """Resolve a console script even when the active venv's bin dir isn't on PATH
    (we're usually invoked as `.venv/bin/python`, whose siblings include the scripts)."""
    sibling = Path(sys.executable).parent / name
    if sibling.exists():
        return str(sibling)
    return shutil.which(name)


# --------------------------------------------------------------------------- #
# holehe
# --------------------------------------------------------------------------- #
class HoleheCollector:
    """Email-registration footprint via holehe. One RawDoc per positive hit."""

    source_type = "holehe"

    def __init__(
        self,
        probe: Optional[HoleheProbeFn] = None,
        *,
        max_emails: int = 4,
        timeout: float = 120.0,
        use_cache: bool = True,
    ):
        self._probe = probe or holehe_probe
        self._max_emails = max_emails
        self._timeout = timeout
        self._use_cache = use_cache

    def collect(self, seed: Seed) -> list[RawDoc]:
        if self._use_cache:
            cached = _load_cache("holehe", seed.target_id)
            if cached is not None:
                return self._docs(seed, cached["hits"])

        emails = _candidate_emails(seed, cap=self._max_emails)
        hits: list[dict] = []
        seen: set[str] = set()
        for email in emails:
            try:
                for hit in self._probe(email, self._timeout):
                    service = str(hit.get("service", "")).strip().lower()
                    if not service or service in seen:
                        continue
                    seen.add(service)
                    hits.append({
                        "service": service,
                        "url": str(hit.get("url") or f"https://{service}"),
                        "email": email,
                    })
            except Exception:
                continue  # one bad probe must not sink the rest / the run
        _save_cache("holehe", seed.target_id, emails, hits)
        return self._docs(seed, hits)

    def _docs(self, seed: Seed, hits: list[dict]) -> list[RawDoc]:
        docs: list[RawDoc] = []
        for hit in hits:
            service = str(hit.get("service", "")).strip()
            if not service:
                continue
            url = str(hit.get("url") or f"https://{service}")
            if not url.startswith("http"):
                url = f"https://{service}"
            docs.append(RawDoc(
                url=url,
                text=f"{seed.name}'s email is registered on {service}.",
                source_type=self.source_type,
                title=f"Email footprint: {service}",
                meta={"service": service, "email": hit.get("email", ""), "via": "holehe"},
            ))
        return docs


def holehe_probe(email: str, timeout: float = 120.0) -> list:
    """Default holehe transport: run the CLI with `--only-used` and parse the `[+]` lines.

    `--only-used` keeps output to services where the email IS registered; `--no-clear`
    stops holehe clearing the screen. Any failure → []."""
    exe = _console_script("holehe")
    if exe is None:
        return []
    try:
        proc = subprocess.run(
            [exe, "--only-used", "--no-clear", email],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0 and not proc.stdout:
        return []
    hits: list[dict] = []
    seen: set[str] = set()
    for line in _ANSI_RE.sub("", proc.stdout or "").splitlines():
        line = line.strip()
        # A service hit is "[+] <domain>"; the legend line "[+] Used" has no dot.
        m = re.match(r"\[\+\]\s+([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})\b", line, re.I)
        if not m:
            continue
        service = m.group(1).lower()
        if service in seen:
            continue
        seen.add(service)
        hits.append({"service": service, "url": f"https://{service}"})
    return hits


def holehe_available() -> bool:
    """True when holehe is usable: the console script resolves, or the module imports."""
    if _console_script("holehe") is not None:
        return True
    try:
        import importlib.util

        return importlib.util.find_spec("holehe") is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# maigret
# --------------------------------------------------------------------------- #
class MaigretCollector:
    """Username footprint via maigret. One RawDoc per found account."""

    source_type = "maigret"

    def __init__(
        self,
        probe: Optional[MaigretProbeFn] = None,
        *,
        max_usernames: int = 3,
        top_sites: int = 500,
        timeout: float = 240.0,
        extra_usernames: tuple[str, ...] = (),
        use_cache: bool = True,
    ):
        self._probe = probe or maigret_probe
        self._max_usernames = max_usernames
        self._top_sites = top_sites
        self._timeout = timeout
        self._extra = extra_usernames
        self._use_cache = use_cache

    def collect(self, seed: Seed) -> list[RawDoc]:
        if self._use_cache:
            cached = _load_cache("maigret", seed.target_id)
            if cached is not None:
                return self._docs(seed, cached["hits"])

        usernames = _candidate_usernames(seed, self._extra, cap=self._max_usernames)
        hits: list[dict] = []
        seen: set[str] = set()
        for username in usernames:
            try:
                for hit in self._probe(username, self._timeout, self._top_sites):
                    url = str(hit.get("url", "")).strip()
                    site = str(hit.get("site", "")).strip()
                    key = (url or site).lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    hits.append({"site": site, "url": url, "username": username})
            except Exception:
                continue
        _save_cache("maigret", seed.target_id, usernames, hits)
        return self._docs(seed, hits)

    def _docs(self, seed: Seed, hits: list[dict]) -> list[RawDoc]:
        from urllib.parse import urlparse

        docs: list[RawDoc] = []
        for hit in hits:
            site = str(hit.get("site", "")).strip()
            url = str(hit.get("url", "")).strip()
            if not site and not url:
                continue
            if not url.startswith("http"):
                url = f"https://{site}" if site else ""
            if not url:
                continue
            # Drop site-root "Claimed" hits (e.g. Discord -> https://discord.com): a real
            # profile carries the handle in a path or query, so a bare root is a maigret
            # false positive, not a per-user account.
            parsed = urlparse(url)
            if not parsed.path.strip("/") and not parsed.query:
                continue
            label = site or url
            docs.append(RawDoc(
                url=url,
                text=f"{seed.name} has an account on {label} ({url}).",
                source_type=self.source_type,
                title=f"Account footprint: {label}",
                meta={"site": site, "username": hit.get("username", ""), "via": "maigret"},
            ))
        return docs


def maigret_probe(username: str, timeout: float = 240.0, top_sites: int = 500) -> list:
    """Default maigret transport: write a `--json simple` report to a temp folder, then
    read the claimed accounts out of it. Capped to the top-N sites for runtime. Any
    failure (missing tool, timeout, bad JSON) → []."""
    import tempfile

    exe = _console_script("maigret")
    if exe is None:
        return []
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            subprocess.run(
                [exe, username, "--json", "simple", "--folderoutput", out_dir,
                 "--top-sites", str(top_sites), "--timeout", "10", "--no-progressbar",
                 "--no-recursion", "--no-color"],
                capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        report = _find_report(out_dir, username)
        if report is None:
            return []
        try:
            with report.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
    return _parse_maigret_simple(data)


def _find_report(out_dir: str, username: str) -> Optional[Path]:
    folder = Path(out_dir)
    candidates = sorted(folder.glob(f"report_{username}_simple.json")) or \
        sorted(folder.glob("*_simple.json")) or sorted(folder.glob("*.json"))
    return candidates[0] if candidates else None


def _parse_maigret_simple(data: object) -> list:
    """The `simple` JSON maps site name -> record; a claimed account has
    status.status == "Claimed" and a user URL. Be defensive about the shape."""
    hits: list[dict] = []
    if not isinstance(data, dict):
        return hits
    for site, record in data.items():
        if not isinstance(record, dict):
            continue
        status = record.get("status")
        state = ""
        if isinstance(status, dict):
            state = str(status.get("status", "")).strip().lower()
        elif isinstance(status, str):
            state = status.strip().lower()
        url = record.get("url_user") or record.get("url") or ""
        if state == "claimed" and url:
            hits.append({"site": str(site), "url": str(url)})
    return hits


def maigret_available() -> bool:
    """True when maigret is usable: the console script resolves, or the module imports."""
    if _console_script("maigret") is not None:
        return True
    try:
        import importlib.util

        return importlib.util.find_spec("maigret") is not None
    except Exception:
        return False


# Keep the protocol honest at import time.
_h: type[Collector] = HoleheCollector
_m: type[Collector] = MaigretCollector

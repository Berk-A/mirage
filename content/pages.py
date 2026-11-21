"""HTML builders for the two things the jury renders and rates: the email body and the
landing page. The API requires self-contained HTML — inline styles only, no scripts,
images only from uploaded assets — so everything here is inline-styled and script-free.
"""
from __future__ import annotations

import html as _html
from typing import Optional

from content.branding import company_from_address
from core.models import Dossier, MoveSpec, RenderedPage, Sender

_FIELD_LABELS = {
    "email": "Email", "username": "Username", "password": "Password",
    "otp": "One-time code", "code": "Verification code", "pin": "PIN",
}


def _field_input(name: str) -> str:
    label = _FIELD_LABELS.get(name, name.replace("_", " ").title())
    itype = "password" if name in ("password", "pin") else (
        "email" if name == "email" else "text")
    return (
        f'<label style="display:block;margin:14px 0 6px;font-size:13px;color:#333;">'
        f'{_html.escape(label)}</label>'
        f'<input type="{itype}" name="{_html.escape(name)}" '
        f'style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid '
        f'#ccc;border-radius:6px;font-size:14px;">'
    )


def build_login_page(spec: MoveSpec, dossier: Dossier,
                     fields: tuple[str, ...] = ("email", "password"), *,
                     logo_asset_id: Optional[str] = None) -> RenderedPage:
    """A branded, credible sign-in page for a tool the target actually uses — a wordmark
    (or real logo asset), a brand-colour bar, and the fields. No scripts; the form action
    is inert (the API records only field names, never values)."""
    vendor = dossier.vendors[0].name if dossier.vendors else "Account"
    title = spec.subject or f"{vendor}: sign in"
    inputs = "".join(_field_input(f) for f in fields)
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_html.escape(title)}</title></head>"
        '<body style="margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,'
        'Roboto,Helvetica,Arial,sans-serif;">'
        '<div style="max-width:380px;margin:60px auto;background:#fff;border:1px solid '
        '#e3e5e8;border-radius:10px;overflow:hidden;">'
        f'<div style="height:4px;background:{_ACCENT};"></div>'
        '<div style="padding:30px 32px;">'
        f'<div style="text-align:center;margin:0 0 14px;">{_wordmark(vendor, logo_asset_id)}</div>'
        f'<h1 style="font-size:18px;margin:0 0 4px;color:#1a1a1a;text-align:center;">'
        f'{_html.escape(vendor)}</h1>'
        '<p style="font-size:13px;color:#666;margin:0 0 20px;text-align:center;">'
        'Sign in to continue</p>'
        f'<form>{inputs}'
        '<button type="submit" style="margin-top:22px;width:100%;padding:11px;'
        f'background:{_ACCENT};color:#fff;border:0;border-radius:6px;font-size:14px;'
        'cursor:pointer;">Sign in</button></form>'
        '<p style="font-size:11px;color:#9aa0a6;margin:20px 0 0;text-align:center;">'
        'Having trouble? Contact your administrator.</p>'
        '</div></div></body></html>'
    )
    return RenderedPage(url=spec.url or "", title=title, fields=tuple(fields), html=html)


_SIGNOFFS = frozenset({
    "best", "best regards", "regards", "kind regards", "warm regards", "thanks",
    "thank you", "many thanks", "cheers", "sincerely", "yours", "yours sincerely",
})
_ACCENT = "#2457d6"


def _company_name(sender: Sender, dossier: Dossier) -> str:
    """The org the signature/branding speaks for — a `company` in the dossier's raw bag if
    present, else derived from the sender's email domain (whose brand the email carries)."""
    raw = getattr(dossier, "raw", {}) or {}
    if isinstance(raw, dict) and raw.get("company"):
        return str(raw["company"])
    return company_from_address(sender.address or "").title() or "Team"


def _wordmark(company: str, logo_asset_id: Optional[str]) -> str:
    """A real logo (uploaded asset) when we have one, else an initials badge in the brand
    colour — a credible 'logo or similar' so the header never looks unbranded."""
    if logo_asset_id:
        return (f'<img src="asset://{_html.escape(logo_asset_id)}" width="34" height="34" '
                f'alt="{_html.escape(company)}" style="display:inline-block;'
                f'vertical-align:middle;border-radius:7px;">')
    initials = ("".join(w[0] for w in company.split()[:2]) or company[:2]).upper()
    return (f'<span style="display:inline-block;width:34px;height:34px;line-height:34px;'
            f'text-align:center;background:{_ACCENT};color:#fff;border-radius:7px;'
            f'font-weight:700;font-size:14px;vertical-align:middle;">'
            f'{_html.escape(initials)}</span>')


def _body_paragraphs(body: str) -> list[str]:
    """Split into paragraphs and drop a trailing sign-off block — we append a branded
    signature instead, so the model's 'Best, Julius' tail would just duplicate it."""
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    if paras:
        head = paras[-1].splitlines()[0].strip().lower().rstrip(",.")
        if head in _SIGNOFFS and len(paras[-1].splitlines()) <= 2:
            paras = paras[:-1]
    return paras


def build_email_html(body: str, sender: Sender, dossier: Dossier,
                     subject: Optional[str] = None, *,
                     logo_asset_id: Optional[str] = None) -> str:
    """Render the body as a clean, credible, inline-styled email: a branded header (real
    logo asset or a wordmark badge), the message, a proper signature, and a confidentiality
    footer. Restrained on purpose — professional, not a glossy marketing blast."""
    company = _company_name(sender, dossier)
    rendered = "".join(
        f'<p style="margin:0 0 14px;color:#1a1a1a;">'
        f'{_html.escape(p).replace(chr(10), "<br>")}</p>'
        for p in _body_paragraphs(body)
    )
    header = (
        f'<div style="border-bottom:1px solid #e8eaed;padding-bottom:12px;'
        f'margin-bottom:18px;">{_wordmark(company, logo_asset_id)}'
        f'<span style="font-weight:600;font-size:15px;color:#1a1a1a;margin-left:10px;'
        f'vertical-align:middle;">{_html.escape(company)}</span></div>'
    )
    addr = _html.escape(sender.address) if sender.address else ""
    contact = (f'<div style="color:#8a8f98;font-size:12px;margin-top:2px;">{addr}</div>'
               if addr else "")
    signature = (
        f'<div style="margin-top:20px;">'
        f'<div style="font-weight:600;color:#1a1a1a;">{_html.escape(sender.name)}</div>'
        f'<div style="color:#555;font-size:13px;">{_html.escape(company)}</div>'
        f'{contact}</div>'
    )
    recipient = _html.escape(dossier.display_name or "")
    footer = (
        f'<div style="margin-top:22px;border-top:1px solid #ededed;padding-top:10px;'
        f'color:#9aa0a6;font-size:11px;line-height:1.5;">{_html.escape(company)} · This '
        f'email and any attachments are confidential and intended only for '
        f'{recipient or "the named recipient"}. If you received it in error, please let '
        f'us know and delete it.</div>'
    )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        'sans-serif;font-size:14px;line-height:1.55;color:#1a1a1a;max-width:600px;">'
        f"{header}{rendered}{signature}{footer}</div>"
    )

"""HTML builders for the two things the jury renders and rates: the email body and the
landing page. The API requires self-contained HTML — inline styles only, no scripts,
images only from uploaded assets — so everything here is inline-styled and script-free.
"""
from __future__ import annotations

import html as _html
from typing import Optional

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
                     fields: tuple[str, ...] = ("email", "password")) -> RenderedPage:
    """A plain, credible sign-in page for a tool the target uses. No scripts; the form
    action is inert (the API records only field names, never values)."""
    vendor = dossier.vendors[0].name if dossier.vendors else "Account"
    title = spec.subject or f"{vendor}: sign in"
    inputs = "".join(_field_input(f) for f in fields)
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_html.escape(title)}</title></head>"
        '<body style="margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,'
        'Roboto,Helvetica,Arial,sans-serif;">'
        '<div style="max-width:380px;margin:64px auto;background:#fff;border:1px solid '
        '#e3e5e8;border-radius:10px;padding:32px;">'
        f'<h1 style="font-size:18px;margin:0 0 4px;color:#1a1a1a;">{_html.escape(vendor)}</h1>'
        '<p style="font-size:13px;color:#666;margin:0 0 20px;">Sign in to continue</p>'
        f'<form>{inputs}'
        '<button type="submit" style="margin-top:22px;width:100%;padding:11px;'
        'background:#2457d6;color:#fff;border:0;border-radius:6px;font-size:14px;'
        'cursor:pointer;">Sign in</button></form>'
        '<p style="font-size:11px;color:#9aa0a6;margin:20px 0 0;text-align:center;">'
        'Having trouble? Contact your administrator.</p>'
        '</div></body></html>'
    )
    return RenderedPage(url=spec.url or "", title=title, fields=tuple(fields), html=html)


def build_email_html(body: str, sender: Sender, dossier: Dossier,
                     subject: Optional[str] = None) -> str:
    """Wrap a plain-text body in a simple, clean, inline-styled email shell with a
    signature. Deliberately plain — a glossy template on a colleague's two-line note
    scores worse than clean plain text."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    rendered = "".join(
        f'<p style="margin:0 0 14px;">{_html.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )
    sig = _html.escape(sender.name)
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        'sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px;">'
        f"{rendered}"
        f'<div style="margin-top:18px;color:#444;">{sig}</div>'
        '</div>'
    )

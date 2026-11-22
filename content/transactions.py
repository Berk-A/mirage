"""Transaction landing pages — the business-normal surfaces where the ask completes.

Doctrine (docs/ACTION_SEQUENCE.md): the win is not the page, it is the TRANSACTION the
page completes. These builders render the page a fictional-org portal would really show:
a vendor/RFP registration, an event roundtable signup, a design-partner onboarding, a
technical evaluation portal, a candidate profile. Each carries the fields a real portal
asks for — always including one SECRET (password), so a submit is a credentials incident;
`tech_eval` additionally carries an internal free-text field, so a submit there is also a
disclosure incident. `build_proof_page` renders the informational org/team site forged on
demand to answer a verification demand ("send me a link to your site/team page").

HTML follows the API rules: self-contained, inline styles, no scripts, images only from
uploaded assets.
"""
from __future__ import annotations

import html as _html
from typing import Optional

from core.models import PretextWorld, RenderedPage

_ACCENT = "#2457d6"

# Fields per transaction kind. Secret fields (password) make a submit a CREDENTIALS
# incident; the tech_eval internal free-text field makes it a DISCLOSURE incident too
# (reader._classify_submit: internal field with a typed value).
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "rfp_portal": ("company", "name", "email", "password"),
    "event_registration": ("name", "email", "password"),
    "beta_onboarding": ("company", "name", "email", "password"),
    "tech_eval": ("company", "email", "password", "infrastructure_notes"),
    "candidate_portal": ("name", "email", "password"),
}
_FIELD_LABELS = {
    "company": "Company name", "name": "Your name", "email": "Work email",
    "password": "Choose a password",
    "infrastructure_notes": "Your current infrastructure / stack notes",
}


def _input(name: str) -> str:
    label = _FIELD_LABELS.get(name, name.replace("_", " ").title())
    if name == "password":
        itype = "password"
    elif name == "email":
        itype = "email"
    else:
        itype = "text"
    if name == "infrastructure_notes":
        return (
            f'<label style="display:block;margin:14px 0 6px;font-size:13px;color:#333;">'
            f'{_html.escape(label)}</label>'
            f'<textarea name="{_html.escape(name)}" rows="4" '
            'style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid '
            '#ccc;border-radius:6px;font-size:14px;"></textarea>'
        )
    return (
        f'<label style="display:block;margin:14px 0 6px;font-size:13px;color:#333;">'
        f'{_html.escape(label)}</label>'
        f'<input type="{itype}" name="{_html.escape(name)}" '
        'style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid '
        '#ccc;border-radius:6px;font-size:14px;">'
    )


def _wordmark(org: str, logo_asset_id: Optional[str]) -> str:
    if logo_asset_id:
        return (f'<img src="asset://{_html.escape(logo_asset_id)}" width="36" height="36" '
                f'alt="{_html.escape(org)}" style="display:inline-block;vertical-align:middle;'
                'border-radius:8px;">')
    initials = ("".join(w[0] for w in org.split()[:2]) or org[:2]).upper()
    return (f'<span style="display:inline-block;width:36px;height:36px;line-height:36px;'
            f'text-align:center;background:{_ACCENT};color:#fff;border-radius:8px;'
            f'font-weight:700;font-size:14px;vertical-align:middle;">'
            f'{_html.escape(initials)}</span>')


def build_transaction_page(world: PretextWorld, *,
                           logo_asset_id: Optional[str] = None) -> RenderedPage:
    """The registration page for the world's transaction — what the target sees when
    they open the link. Reads like the portal it claims to be."""
    fields = KIND_FIELDS.get(world.kind, KIND_FIELDS["rfp_portal"])
    title = f"{world.org} — registration"
    inputs = "".join(_input(f) for f in fields)
    facts = "".join(
        f'<li style="margin:0 0 8px;color:#444;">{_html.escape(f)}</li>'
        for f in world.facts[:5]
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_html.escape(title)}</title></head>"
        '<body style="margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,'
        'Roboto,Helvetica,Arial,sans-serif;">'
        '<div style="max-width:560px;margin:48px auto;background:#fff;border:1px solid '
        '#e3e5e8;border-radius:10px;overflow:hidden;">'
        f'<div style="height:4px;background:{_ACCENT};"></div>'
        '<div style="padding:30px 34px;">'
        f'<div style="margin:0 0 16px;">{_wordmark(world.org, logo_asset_id)}'
        f'<span style="font-weight:600;font-size:16px;color:#1a1a1a;margin-left:10px;'
        f'vertical-align:middle;">{_html.escape(world.org)}</span></div>'
        f'<h1 style="font-size:18px;margin:0 0 6px;color:#1a1a1a;">'
        f'{_html.escape(world.transaction)}</h1>'
        f'<p style="font-size:13px;color:#666;margin:0 0 6px;">'
        f'Reference {_html.escape(world.reference)} · {_html.escape(world.deadline)}</p>'
        f'<ul style="font-size:13px;line-height:1.5;padding-left:18px;margin:12px 0 4px;">'
        f'{facts}</ul>'
        f'<form style="margin-top:16px;">{inputs}'
        f'<button type="submit" style="margin-top:22px;width:100%;padding:11px;'
        f'background:{_ACCENT};color:#fff;border:0;border-radius:6px;font-size:14px;'
        'cursor:pointer;">Register</button></form>'
        f'<p style="font-size:11px;color:#9aa0a6;margin:18px 0 0;">'
        f'{_html.escape(world.org)} · {_html.escape(world.city)} · '
        f'Contact: {_html.escape(world.persona_name)} '
        f'({_html.escape(world.persona_address)})</p>'
        '</div></div></body></html>'
    )
    return RenderedPage(url=world.registration_url, title=title, fields=tuple(fields),
                        html=html)


def build_proof_page(world: PretextWorld, *,
                     logo_asset_id: Optional[str] = None) -> RenderedPage:
    """The informational artifact forged on demand to satisfy a verification demand —
    an org/about page that corroborates the world (no fields; it only needs to LOOK real
    and be consistent with everything claimed so far)."""
    title = f"{world.org} — about"
    facts = "".join(
        f'<li style="margin:0 0 10px;color:#333;">{_html.escape(f)}</li>'
        for f in world.facts
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_html.escape(title)}</title></head>"
        '<body style="margin:0;background:#fff;font-family:-apple-system,Segoe UI,'
        'Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;">'
        f'<div style="border-bottom:1px solid #e8eaed;">'
        f'<div style="max-width:760px;margin:0 auto;padding:18px 24px;">'
        f'{_wordmark(world.org, logo_asset_id)}'
        f'<span style="font-weight:600;font-size:17px;margin-left:10px;vertical-align:middle;">'
        f'{_html.escape(world.org)}</span></div></div>'
        '<div style="max-width:760px;margin:0 auto;padding:34px 24px;">'
        f'<h1 style="font-size:26px;margin:0 0 6px;">{_html.escape(world.org)}</h1>'
        f'<p style="color:#666;margin:0 0 22px;">{_html.escape(world.city)} · '
        f'{_html.escape(world.domain)}</p>'
        f'<h2 style="font-size:16px;margin:0 0 10px;">What we do</h2>'
        f'<ul style="font-size:14px;line-height:1.6;padding-left:20px;margin:0 0 22px;">'
        f'{facts}</ul>'
        f'<h2 style="font-size:16px;margin:0 0 10px;">Contact</h2>'
        f'<p style="font-size:14px;color:#333;">{_html.escape(world.persona_name)}, '
        f'{_html.escape(world.persona_role)} — {_html.escape(world.persona_address)}</p>'
        '</div>'
        f'<div style="border-top:1px solid #ededed;margin-top:20px;">'
        f'<div style="max-width:760px;margin:0 auto;padding:14px 24px;color:#9aa0a6;'
        f'font-size:11px;">© 2026 {_html.escape(world.org)} · {_html.escape(world.city)}'
        '</div></div></body></html>'
    )
    return RenderedPage(url=world.site_url, title=title, fields=(), html=html)

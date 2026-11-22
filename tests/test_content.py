"""Content studio: cascade behaviour with a fake LLM (no served model, no network)."""
from content.llm import FakeLLM, LLM, OpenAICompatLLM
from content.pages import build_email_html, build_login_page
from content.studio import Critic, Humanizer, StudioRenderer, Writer
from core.fakes import FakeDossierProvider
from core.interfaces import Renderer
from core.models import Claim, MoveSpec, Objective, Sender

DOSSIER = FakeDossierProvider().get_dossier("tom")
SENDER = Sender(name="Lena Hofer", address="lena.hofer@eventcrew-muc.de")


def spec(objective=Objective.DISCLOSURE, channel="email", url=None, subject="Thursday talk"):
    return MoveSpec(objective=objective, channel=channel, sender=SENDER,
                    tactic="pretext_question", ask="confirm the room for Thursday",
                    claims=(Claim("You have a talk on Thursday"),), cta="confirm the room",
                    tone="professional", subject=subject, url=url)


def test_protocol_conformance():
    assert isinstance(FakeLLM(), LLM)
    assert isinstance(OpenAICompatLLM(), LLM)
    assert isinstance(StudioRenderer(FakeLLM()), Renderer)


def test_writer_returns_model_output():
    w = Writer(FakeLLM(responses=["Hi Tom, quick one — which room on Thursday?"]))
    out = w.write(spec(), DOSSIER)
    assert "Thursday" in out


def test_writer_falls_back_when_model_empty():
    out = Writer(FakeLLM(responses=[""])).write(spec(), DOSSIER)
    assert out and "confirm the room" in out.lower()


def test_renderer_exposes_model_fallback_and_error():
    class BrokenLLM:
        def complete(self, *args, **kwargs):
            raise TimeoutError("do not expose this message")

    renderer = StudioRenderer(BrokenLLM())
    message = renderer.render(spec(), DOSSIER)
    assert message.body
    assert renderer.last_fell_back is True
    assert renderer.last_model_error == "TimeoutError"


def test_critic_flags_leaks_artifacts_and_links():
    c = Critic()
    assert c.review("Hi Tom, which room on Thursday? Thanks, Lena", spec(), DOSSIER).ok
    assert not c.review("As an AI, I can help with that.", spec(), DOSSIER).ok
    assert not c.review("Hi [name], see {placeholder}", spec(), DOSSIER).ok
    # a link we never registered
    bad = c.review("Please visit http://evil.example/login now", spec(), DOSSIER)
    assert not bad.ok and any("unexpected link" in i for i in bad.issues)


def test_critic_allows_the_registered_url():
    s = spec(objective=Objective.CREDENTIALS,
             url="https://notion-signin.example-portal-login.de/auth")
    body = "Hi Tom, please sign in here: https://notion-signin.example-portal-login.de/auth"
    assert Critic().review(body, s, DOSSIER).ok


def test_humanizer_strips_stock_opener_and_chat_signoff():
    h = Humanizer()
    out = h.humanize("I hope this email finds you well. Quick question about Thursday.",
                     channel="email")
    assert not out.lower().startswith("i hope this email")
    chat = h.humanize("hey, got a sec?\nBest regards,\nLena", channel="slack")
    assert "best regards" not in chat.lower()


def test_renderer_regenerates_on_leak_then_cleans():
    llm = FakeLLM(responses=[
        "As an AI I'd be happy to help. Which room on Thursday?",   # rejected
        "Hi Tom, quick one — which room is the Thursday talk in? Thanks, Lena",  # accepted
    ])
    r = StudioRenderer(llm)
    msg = r.render(spec(), DOSSIER)
    assert "as an ai" not in msg.body.lower()
    assert len(llm.calls) == 2  # one write + one rewrite


def test_email_gets_html_and_credentials_get_a_page():
    llm = FakeLLM(responses=["Hi Tom, please confirm access here."])
    s = spec(objective=Objective.CREDENTIALS, channel="email",
             url="https://notion-signin.example-portal-login.de/auth")
    msg = StudioRenderer(llm).render(s, DOSSIER)
    assert msg.html and "<div" in msg.html and "<script" not in msg.html
    assert msg.page is not None
    assert msg.page.url == s.url and "password" in msg.page.fields


def test_non_layout_channel_has_no_html():
    llm = FakeLLM(responses=["hey, which room thursday?"])
    msg = StudioRenderer(llm).render(spec(channel="slack"), DOSSIER)
    assert msg.html is None


def test_login_page_is_script_free_and_has_fields():
    page = build_login_page(spec(url="https://x.example-portal-login.de/auth"), DOSSIER)
    assert "<script" not in page.html.lower()
    assert page.fields == ("email", "password")


def test_email_html_escapes_body():
    html = build_email_html("Hi <b>Tom</b> & team", SENDER, DOSSIER)
    assert "&lt;b&gt;" in html and "&amp;" in html


# --------------------------------------------------------------------------- #
# Branded email + landing page (credibility: logo/wordmark, signature, footer)
# --------------------------------------------------------------------------- #
def test_email_html_is_branded_with_signature_and_footer():
    html = build_email_html("Hi Tom,\n\nQuick note about the talk.\n\nBest,\nLena",
                            SENDER, DOSSIER)
    assert "Eventcrew" in html                 # wordmark/company derived from sender domain
    assert "Lena Hofer" in html                # branded signature block
    assert "confidential" in html.lower()      # confidentiality footer
    assert "Best,\nLena" not in html           # trailing sign-off dropped (sig replaces it)


def test_email_embeds_real_logo_asset_when_provided():
    html = build_email_html("Hi", SENDER, DOSSIER, logo_asset_id="a_9")
    assert "asset://a_9" in html               # real uploaded logo, not just the wordmark


def test_login_page_is_branded():
    from core.models import MoveSpec as MS, Objective as Obj
    spec = MS(objective=Obj.CREDENTIALS, channel="email",
              sender=SENDER, url="https://stackit-portal.io/auth", subject="STACKIT: sign in")
    page = build_login_page(spec, DOSSIER, logo_asset_id="a_7")
    assert "asset://a_7" in page.html          # vendor logo on the page
    assert page.fields == ("email", "password")

"""LLM-based OSINT fact extraction: parses the model's JSON into sourced Facts, and is
safe (short docs / bad JSON / a dead model all yield nothing, so the pipeline is unchanged)."""
from content.llm import FakeLLM
from research.llm_extract import extract_facts
from research.sources import RawDoc, Seed

SEED = Seed(target_id="tom", name="Tom Müller", role="Co-Founder", company="revel8")
LONG = ("In a recent interview Tom talked about where revel8 is heading and what the team is "
        "building this year, covering the product direction and some of the hiring plans. " * 3)


def test_llm_extract_parses_sourced_facts():
    doc = RawDoc(url="https://ex/interview", text=LONG, source_type="web",
                 published_date="2026-10-01")
    llm = FakeLLM(responses=['{"facts":[{"claim":"Tom says revel8 is focused on agentic '
                             'security","predicate":"said","object":"agentic security",'
                             '"confidence":0.8},{"claim":"revel8 is hiring a head of ML",'
                             '"predicate":"hiring","object":"head of ML","confidence":0.7}]}'])
    facts = extract_facts(doc, SEED, llm)
    assert len(facts) == 2
    assert facts[0].subject == "tom" and facts[0].source_url == "https://ex/interview"
    assert facts[0].confidence == 0.8 and facts[0].event_date == "2026-10-01"
    assert facts[0].id.startswith("llm_")


def test_llm_extract_skips_short_text():
    assert extract_facts(RawDoc(url="x", text="hi"), SEED, FakeLLM(responses=["{}"])) == []


def test_llm_extract_bad_json_is_safe():
    doc = RawDoc(url="x", text="a" * 300)
    assert extract_facts(doc, SEED, FakeLLM(responses=["sorry, no json here"])) == []


def test_llm_extract_dead_model_is_safe():
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("down")
    assert extract_facts(RawDoc(url="x", text="a" * 300), SEED, Boom()) == []

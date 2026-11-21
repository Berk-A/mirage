from core.models import Scenario, Target
from research.collectors.brave import BraveSearchCollector
from research.seeds import seeds_from_scenario


def test_seeds_are_built_from_the_api_scenario_roster():
    scenario = Scenario(
        id="eval", kind="eval", company="Example Co",
        targets=(Target("a", "Ava Chen", "CTO"), Target("b", "Ben Rao", "COO")),
    )
    seeds = seeds_from_scenario(scenario)
    assert [seed.target_id for seed in seeds] == ["a", "b"]
    assert seeds[0].company == "Example Co"
    assert seeds[0].colleagues == ("Ben Rao",)
    assert seeds[0].aliases == ("Ava", "Chen")


def test_brave_search_results_preserve_source_and_date_and_dedupe_urls():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"web": {"results": [{
                "url": "https://news.example/story",
                "title": "Ava Chen to speak at Example Summit",
                "description": "Ava Chen is listed as a speaker.",
                "page_age": "2026-10-10T09:00:00Z",
            }]}}

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    session = Session()
    collector = BraveSearchCollector("search-key", session=session)
    seed = seeds_from_scenario(Scenario(
        id="eval", company="Example Co", targets=(Target("a", "Ava Chen"),)
    ))[0]
    docs = collector.collect(seed)
    assert len(session.calls) == 4
    assert session.calls[0][1]["headers"]["X-Subscription-Token"] == "search-key"
    assert len(docs) == 1
    assert docs[0].url == "https://news.example/story"
    assert docs[0].published_date == "2026-10-10"
    assert docs[0].meta["via"] == "brave_search"

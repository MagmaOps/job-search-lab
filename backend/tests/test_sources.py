from pathlib import Path

from jobsearch.sources import get_source, source_names
from jobsearch.sources.rss import RssSource

FIXTURES = Path(__file__).parent / "fixtures"


def test_registry_has_expected_sources():
    names = source_names()
    for expected in ("rss", "remoteok", "remotive", "arbeitnow"):
        assert expected in names


def test_rss_parser_splits_company_and_strips_html():
    content = (FIXTURES / "wwr_devops.rss").read_text(encoding="utf-8")
    jobs = RssSource().parse_content(content, feed_url="wwr")
    assert len(jobs) == 2

    first = jobs[0]
    assert first.company == "Acme Corp"
    assert first.title == "Senior DevOps Engineer"
    assert "<" not in (first.description or "")
    assert "Kubernetes" in (first.description or "")
    assert first.url.startswith("https://weworkremotely.com/")

    second = jobs[1]
    assert second.company == "Globex"
    assert second.location == "Europe only"


def test_get_source_unknown_raises():
    try:
        get_source("does-not-exist")
        assert False, "expected KeyError"
    except KeyError:
        pass

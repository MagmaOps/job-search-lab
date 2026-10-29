from pathlib import Path

from jobsearch.sources import get_source, source_names
from jobsearch.sources.base import format_salary, normalize_work_type
from jobsearch.sources.rss import RssSource

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_work_type():
    assert normalize_work_type("Fully remote role") == "remote"
    assert normalize_work_type("Hybrid (2 days office)") == "hybrid"
    assert normalize_work_type("On-site in Berlin") == "onsite"
    assert normalize_work_type(None) is None
    # An explicit remote flag wins even when the text is silent.
    assert normalize_work_type("Europe only", remote_flag=True) == "remote"
    # Hybrid in text beats a remote flag (more specific).
    assert normalize_work_type("Hybrid role", remote_flag=True) == "hybrid"


def test_format_salary():
    assert format_salary(90000, 120000, currency="USD", period="year") == "USD 90,000 – 120,000/year"
    assert format_salary(100000, 100000) == "100,000"  # equal min/max collapses
    assert format_salary(None, 80000) == "80,000"
    assert format_salary(None, None) is None
    assert format_salary(raw="Competitive, DOE") == "Competitive, DOE"
    assert format_salary("not-a-number", None) is None  # bad field ignored, not misleading


def test_rss_parser_sets_remote_work_type():
    content = (FIXTURES / "wwr_devops.rss").read_text(encoding="utf-8")
    jobs = RssSource().parse_content(content, feed_url="wwr")
    assert all(j.work_type == "remote" for j in jobs)


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

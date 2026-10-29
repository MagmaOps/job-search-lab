from jobsearch.services.collect_service import filter_relevant
from jobsearch.sources.base import RawJob


def _job(title: str) -> RawJob:
    return RawJob(title=title, source="remoteok")


def test_keeps_devops_family_titles_even_without_keyword():
    jobs = [
        _job("Senior DevOps Engineer"),
        _job("Site Reliability Engineer"),
        _job("Platform Engineer"),
        _job("Kubernetes Infrastructure Engineer"),
        _job("Cloud Operations Specialist"),
    ]
    kept = filter_relevant(jobs, keywords="DevOps Engineer")
    assert len(kept) == len(jobs)


def test_drops_unrelated_titles_from_loose_tagging():
    jobs = [
        _job("Senior DevOps Engineer"),   # keep
        _job("Freelance Copywriter"),     # drop
        _job("Manufacturing Manager"),    # drop
        _job("Borracheiro"),              # drop
        _job("Roupeiro I Gramado RS"),    # drop
    ]
    kept = filter_relevant(jobs, keywords="DevOps Engineer")
    titles = {j.title for j in kept}
    assert titles == {"Senior DevOps Engineer"}


def test_query_keyword_widens_match_beyond_devops_vocab():
    jobs = [_job("Senior Golang Backend Engineer"), _job("Marketing Lead")]
    # A query explicitly searching "golang" keeps the Go role even though it is not in the
    # built-in DevOps vocabulary.
    kept = filter_relevant(jobs, keywords="golang")
    assert [j.title for j in kept] == ["Senior Golang Backend Engineer"]


def test_untitled_job_dropped():
    assert filter_relevant([RawJob(title="", source="x")], keywords="devops") == []

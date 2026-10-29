from jobsearch.dedup import content_hash, fingerprint, normalize_url


def test_normalize_strips_tracking_and_fragment():
    a = normalize_url("https://Example.com/jobs/123?utm_source=x&ref=y#apply")
    b = normalize_url("http://example.com/jobs/123/")
    assert a == "https://example.com/jobs/123"
    assert b == "http://example.com/jobs/123"


def test_normalize_sorts_and_keeps_real_params():
    url = normalize_url("https://x.io/j?b=2&a=1&utm_campaign=z")
    assert url == "https://x.io/j?a=1&b=2"


def test_normalize_handles_default_ports_and_none():
    assert normalize_url("https://x.io:443/a") == "https://x.io/a"
    assert normalize_url(None) is None
    assert normalize_url("not-a-url") is None


def test_fingerprint_is_case_and_space_insensitive():
    f1 = fingerprint("remoteok", "ACME  Inc", "DevOps  Engineer", "Remote")
    f2 = fingerprint("remoteok", "acme inc", "devops engineer", "remote")
    assert f1 == f2


def test_fingerprint_differs_on_company():
    assert fingerprint("x", "A", "T", "L") != fingerprint("x", "B", "T", "L")


def test_content_hash_detects_change():
    h1 = content_hash("Title", "desc one")
    h2 = content_hash("Title", "desc two")
    assert h1 != h2
    assert h1 == content_hash("Title", "desc one")

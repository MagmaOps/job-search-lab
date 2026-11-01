from fastapi.testclient import TestClient

from jobsearch.api import app


def test_version_endpoint_reports_app_version():
    r = TestClient(app).get("/version")
    assert r.status_code == 200
    assert r.json() == {"version": app.version}

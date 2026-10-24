"""Access control: token cookie, cross-site refusal, Host check, required header, data-folder permissions."""

import os

import pytest
from fastapi.testclient import TestClient

from pixsift.api import create_app
from pixsift.config import Settings

TOKEN = "s3cret-token"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", token=TOKEN))


def test_api_requires_the_access_cookie(app):
    anon = TestClient(app)
    assert anon.get("/api/health").status_code == 401
    assert anon.get("/api/images").status_code == 401
    assert anon.get("/api/images/1/thumb").status_code == 401
    wrong = TestClient(app, cookies={"pixsift_token": "guess"})
    assert wrong.get("/api/health").status_code == 401


def test_token_link_sets_strict_httponly_cookie(app):
    c = TestClient(app, follow_redirects=False)
    r = c.get(f"/?token={TOKEN}")
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/health").status_code == 200  # cookie now held by the client
    assert TestClient(app, follow_redirects=False).get("/?token=nope").status_code == 401


def test_cross_site_browser_requests_are_refused(app):
    c = TestClient(app, cookies={"pixsift_token": TOKEN})
    for site in ("cross-site", "same-site"):
        assert c.get("/api/images/1/preview", headers={"Sec-Fetch-Site": site}).status_code == 403
        # A link from another site can't plant a token either.
        assert c.get(f"/?token={TOKEN}", headers={"Sec-Fetch-Site": site}).status_code == 403
    assert c.get("/api/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_foreign_host_header_is_refused(app):
    c = TestClient(app, cookies={"pixsift_token": TOKEN})
    assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_actions_need_the_ui_header_even_with_cookie(app):
    c = TestClient(app, cookies={"pixsift_token": TOKEN})
    assert c.post("/api/analyze").status_code == 403


def test_oversized_face_lists_are_rejected(app):
    c = TestClient(app, cookies={"pixsift_token": TOKEN})
    r = c.post("/api/faces/assign", json={"face_ids": list(range(6000)), "name": "x"}, headers={"X-PixSift": "1"})
    assert r.status_code == 422


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_data_folder_is_owner_only(app):
    assert (app.state.settings.data_dir.stat().st_mode & 0o077) == 0

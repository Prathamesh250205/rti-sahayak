"""Self-check for web/api/auth.py's OAuth linking and account settings.

No network: the provider HTTP calls are stubbed. Uses a throwaway SQLite
file, never data/users.db. Run: python -m tools.auth_selfcheck
"""
import os
import tempfile
import urllib.parse
from pathlib import Path

os.environ["USERS_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "users.db")
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"):
    os.environ[k] = "test-" + k.lower()

from fastapi.testclient import TestClient  # noqa: E402

import web.api.auth as auth  # noqa: E402
from web.main import app  # noqa: E402

PROFILE = {}


def fake_http(url, data=None, token=None):
    if data:  # token exchange
        return {"access_token": "tok"}
    if "openidconnect" in url:
        return {"email": PROFILE["email"], "email_verified": PROFILE["verified"], "name": "Gita G"}
    if url.endswith("/user"):
        return {"name": None, "login": "gitauser"}
    return [{"email": PROFILE["email"], "primary": True, "verified": PROFILE["verified"]}]


auth._http_json = fake_http


def oauth(client, provider, email, verified=True, tamper=False):
    PROFILE.update(email=email, verified=verified)
    start = client.get(f"/auth/{provider}/start?next=/draft", follow_redirects=False)
    assert start.status_code == 303, start.status_code
    state = urllib.parse.parse_qs(urllib.parse.urlparse(start.headers["location"]).query)["state"][0]
    return client.get(f"/auth/{provider}/callback?code=c&state={state + ('x' if tamper else '')}", follow_redirects=False)


def signup(client, email, pw="Passw0rd!x"):
    return client.post("/signup", data={"name": "Pat", "email": email, "password": pw, "confirm": pw, "agree": "1"},
                       follow_redirects=False)


def main():
    page = TestClient(app).get("/login").text
    assert "Continue with Google" in page and "Continue with GitHub" in page

    # New Google user lands where `next` said, signed in.
    c = TestClient(app)
    r = oauth(c, "google", "new@example.com")
    assert r.status_code == 303 and r.headers["location"] == "/draft", r.headers
    assert 'class="acct-avatar"' in c.get("/").text

    # Tampered state is rejected.
    assert oauth(TestClient(app), "google", "new@example.com", tamper=True).status_code == 400

    # GitHub account without a verified email is refused.
    assert oauth(TestClient(app), "github", "nope@example.com", verified=False).status_code == 400

    # Pre-hijack defence: a squatter registers the victim's email with a
    # password; the real owner then signs in with Google -> the squatter's
    # password and session stop working.
    squatter = TestClient(app)
    assert signup(squatter, "victim@example.com").status_code == 303
    assert oauth(TestClient(app), "google", "victim@example.com").status_code == 303
    assert 'class="acct-avatar"' not in squatter.get("/").text, "squatter session survived"
    login = TestClient(app).post("/login", data={"email": "victim@example.com", "password": "Passw0rd!x"},
                                 follow_redirects=False)
    assert login.status_code == 401, "squatter password survived"

    # Account settings: rename, wrong current password, change password.
    me, other = TestClient(app), TestClient(app)
    signup(me, "me@example.com")
    other.post("/login", data={"email": "me@example.com", "password": "Passw0rd!x"})
    assert "Name updated" in me.post("/account/profile", data={"name": "Pat Renamed"}).text
    bad = me.post("/account/password", data={"current": "nope", "password": "N3w-pass!!", "confirm": "N3w-pass!!"})
    assert bad.status_code == 400 and "incorrect" in bad.text
    ok = me.post("/account/password", data={"current": "Passw0rd!x", "password": "N3w-pass!!", "confirm": "N3w-pass!!"})
    assert "Password changed" in ok.text
    assert "Pat Renamed" in me.get("/account").text, "changer got logged out"
    assert me.get("/account", follow_redirects=False).status_code == 200
    assert other.get("/account", follow_redirects=False).status_code == 303, "other device stayed signed in"

    # Delete needs the exact email; then the account is gone.
    assert me.post("/account/delete", data={"confirm_email": "wrong@example.com"}).status_code == 400
    me.post("/account/delete", data={"confirm_email": "ME@example.com"})
    assert me.get("/account", follow_redirects=False).status_code == 303
    assert TestClient(app).post("/login", data={"email": "me@example.com", "password": "N3w-pass!!"},
                                follow_redirects=False).status_code == 401
    print("auth self-check: all passed")


if __name__ == "__main__":
    main()

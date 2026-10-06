"""Optional accounts: email + password, Google / GitHub sign-in, forgot and
reset password, and an account settings page. Every tool still works
signed out - an account only puts a name in the nav for now.

Storage is Postgres when DATABASE_URL is set (required on Vercel, where
each instance's disk is temporary), SQLite otherwise (local dev). The rest
is stdlib: hashlib.scrypt for passwords, urllib for the OAuth calls, an
HMAC-signed cookie for the session. The cookie
signature covers the password hash's salt, so changing or resetting a
password logs out every old session.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from web.rate_limit import is_rate_limited

ON_VERCEL = bool(os.getenv("VERCEL"))
# Vercel's Neon integration sets DATABASE_URL (and POSTGRES_URL).
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
DB_PATH = Path(os.getenv("USERS_DB_PATH") or ("/tmp/users.db" if ON_VERCEL else
               Path(__file__).resolve().parents[2] / "data" / "users.db"))
if ON_VERCEL and not DATABASE_URL:
    print("[auth] ERROR: no DATABASE_URL - accounts live in this instance's /tmp and will "
          "vanish. Add a Postgres database (Vercel > Storage > Neon).", file=sys.stderr)
# A random fallback means sessions only work on the instance that issued
# them - fine for local dev, broken on Vercel (many instances).
SECRET = (os.getenv("SESSION_SECRET") or secrets.token_hex(32)).encode()
if ON_VERCEL and not os.getenv("SESSION_SECRET"):
    print("[auth] ERROR: SESSION_SECRET is not set - logins will randomly drop.", file=sys.stderr)
COOKIE = "rti_session"
STATE_COOKIE = "rti_oauth_state"
SESSION_DAYS_REMEMBER = 30
SESSION_HOURS_DEFAULT = 12
RESET_TTL_SECONDS = 3600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A provider's button only shows once both its env vars are set.
PROVIDERS = {
    "google": {
        "label": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "label": "GitHub",
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}

router = APIRouter()


if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row
    IntegrityError = psycopg.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


class _Pg:
    """A psycopg connection that takes the sqlite-style "?" placeholders
    used throughout this module. Commits and closes on leaving `with`."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        return self._conn.execute(sql.replace("?", "%s"), params)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


_schema_ready = False


def _db():
    # Emails are stored lowercased, so plain "=" lookups are case-insensitive
    # on both backends. verified = the owner proved the address (OAuth or a
    # reset link).
    global _schema_ready
    if DATABASE_URL:
        # prepare_threshold=None: Neon's pooled (PgBouncer) URL rejects prepared statements.
        conn = _Pg(psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None))
        pk = "SERIAL PRIMARY KEY"
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn, pk = sqlite3.connect(DB_PATH), "INTEGER PRIMARY KEY"
        conn.row_factory = sqlite3.Row
    if not _schema_ready:
        with conn:
            conn.execute(f"CREATE TABLE IF NOT EXISTS users (id {pk}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,"
                         " pw TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, verified INTEGER NOT NULL DEFAULT 0)")
            conn.execute("CREATE TABLE IF NOT EXISTS resets (token_hash TEXT PRIMARY KEY,"
                         " user_id INTEGER NOT NULL, expires DOUBLE PRECISION NOT NULL)")
        _schema_ready = True
        return _db()  # the psycopg connection closed on leaving `with`
    return conn


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)), stored)


def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()


def _session_value(user: sqlite3.Row, expires: int) -> str:
    payload = f"{user['id']}:{expires}"
    return f"{payload}:{_sign(payload + ':' + user['pw'][:32])}"


def _session_expiry(request: Request) -> int:
    try:
        return int(request.cookies.get(COOKIE, "").split(":")[1])
    except (IndexError, ValueError):
        return int(time.time()) + SESSION_HOURS_DEFAULT * 3600


def current_user(request: Request):
    """The signed-in user row, or None. Exposed to every template. Cached
    per request - a page asks several times and each ask is a DB round trip."""
    if not hasattr(request.state, "auth_user"):
        request.state.auth_user = _load_user(request)
    return request.state.auth_user


def _load_user(request: Request):
    raw = request.cookies.get(COOKIE, "")
    try:
        user_id, expires, sig = raw.split(":")
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    with _db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and hmac.compare_digest(sig, _sign(f"{user_id}:{expires}:{user['pw'][:32]}")):
        return user
    return None


def oauth_providers() -> list[tuple[str, str]]:
    """(key, label) for each provider with credentials set. Exposed to templates."""
    return [(key, p["label"]) for key, p in PROVIDERS.items()
            if os.getenv(f"{key.upper()}_CLIENT_ID") and os.getenv(f"{key.upper()}_CLIENT_SECRET")]


def _safe_next(next_url: str) -> str:
    # Only same-site paths - never "//evil.com" or "https://..." (open redirect).
    return next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"


def _base_url(request: Request) -> str:
    # A configured URL, not the request's Host header, so a forged Host can't
    # point an emailed link or an OAuth redirect at someone else's site.
    # Vercel provides its production domain automatically.
    vercel = os.getenv("VERCEL_PROJECT_PRODUCTION_URL")
    return (os.getenv("PUBLIC_BASE_URL") or (vercel and f"https://{vercel}") or str(request.base_url)).rstrip("/")


def _secure_cookies() -> bool:
    flag = os.getenv("COOKIE_SECURE", "").lower()
    return flag in ("1", "true") or (not flag and ON_VERCEL)  # Vercel is always HTTPS


def _render(request: Request, mode: str, status_code: int = 200, **ctx):
    from web.main import templates  # deferred: web.main imports this module
    return templates.TemplateResponse(request, "auth.html", {"mode": mode, **ctx}, status_code=status_code)


def _set_session(response, user: sqlite3.Row, expires: int, persistent: bool):
    response.set_cookie(
        COOKIE, _session_value(user, expires),
        max_age=max(expires - int(time.time()), 0) if persistent else None,
        httponly=True, samesite="lax",
        secure=_secure_cookies(),
    )
    return response


def _signed_in(user: sqlite3.Row, next_url: str, remember: bool) -> RedirectResponse:
    lifetime = SESSION_DAYS_REMEMBER * 86400 if remember else SESSION_HOURS_DEFAULT * 3600
    response = RedirectResponse(_safe_next(next_url), status_code=303)
    return _set_session(response, user, int(time.time()) + lifetime, remember)


def _throttled(request: Request) -> bool:
    # Same limiter as /api/draft, but its own key space so login attempts
    # never eat into anyone's draft quota.
    return is_rate_limited("auth:" + (request.client.host if request.client else "unknown"))


def _send_reset_email(to: str, link: str) -> None:
    if not os.getenv("SMTP_HOST"):
        # No mail server configured (local dev / demo): the link goes to the
        # server log only - never back into the HTTP response.
        print(f"[auth] Password reset link for {to}: {link}", file=sys.stderr)
        return
    msg = EmailMessage()
    msg["Subject"] = "Reset your RTI Sahayak password"
    msg["From"] = os.getenv("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = to
    msg.set_content(
        f"Someone asked to reset the password for this email on RTI Sahayak.\n\n"
        f"Reset it here (valid for 1 hour): {link}\n\n"
        f"If it wasn't you, ignore this email - your password stays the same."
    )
    port = int(os.getenv("SMTP_PORT", "587"))
    # 465 = implicit TLS (e.g. Gmail's SSL port); anything else = STARTTLS.
    smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_cls(os.environ["SMTP_HOST"], port, timeout=15) as smtp:
        if port != 465:
            smtp.starttls()
        if os.getenv("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


# ---------- Email + password ----------

@router.get("/login")
def login_page(request: Request, next: str = "/"):
    if current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render(request, "login", next=next)


@router.post("/login")
def login(request: Request, email: str = Form(""), password: str = Form(""),
          remember: str = Form(""), next: str = Form("/")):
    if _throttled(request):
        return _render(request, "login", 429, next=next, email=email,
                       error="Too many attempts. Wait a few minutes and try again.")
    with _db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if not user or not verify_password(password, user["pw"]):
        return _render(request, "login", 401, next=next, email=email,
                       error="That email and password don't match an account.")
    return _signed_in(user, next, bool(remember))


def _password_error(password: str, confirm: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "Passwords don't match."
    return None


@router.get("/signup")
def signup_page(request: Request, next: str = "/"):
    return _render(request, "signup", next=next)


@router.post("/signup")
def signup(request: Request, name: str = Form(""), email: str = Form(""), password: str = Form(""),
           confirm: str = Form(""), agree: str = Form(""), next: str = Form("/")):
    name, email = name.strip(), email.strip().lower()
    error = None
    if _throttled(request):
        error = "Too many attempts. Wait a few minutes and try again."
    elif not 1 <= len(name) <= 80:
        error = "Enter your name."
    elif not EMAIL_RE.match(email):
        error = "Enter a valid email address."
    elif not agree:
        error = "Please accept the Terms and Privacy Policy."
    error = error or _password_error(password, confirm)
    if error:
        return _render(request, "signup", 400, next=next, name=name, email=email, error=error)
    try:
        with _db() as conn:
            conn.execute("INSERT INTO users (name, email, pw, created) VALUES (?, ?, ?, ?)",
                         (name, email, hash_password(password), time.time()))
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    except IntegrityError:
        return _render(request, "signup", 409, next=next, name=name, email=email,
                       error="An account with this email already exists. Try signing in.")
    return _signed_in(user, next, remember=True)


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response


# ---------- Forgot / reset password ----------

@router.get("/forgot-password")
def forgot_page(request: Request):
    return _render(request, "forgot")


@router.post("/forgot-password")
def forgot(request: Request, email: str = Form("")):
    email = email.strip().lower()
    if _throttled(request):
        return _render(request, "forgot", 429, email=email,
                       error="Too many attempts. Wait a few minutes and try again.")
    with _db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO resets VALUES (?, ?, ?)",
                         (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + RESET_TTL_SECONDS))
    if user:
        try:
            _send_reset_email(user["email"], f"{_base_url(request)}/reset-password?token={token}")
        except (OSError, smtplib.SMTPException, KeyError) as e:
            print(f"[auth] ERROR: reset email failed: {type(e).__name__}: {e}", file=sys.stderr)
    # Same answer whether or not the account exists - no email enumeration.
    return _render(request, "forgot", sent=True, email=email)


def _reset_user_id(conn, token: str):
    row = conn.execute("SELECT user_id FROM resets WHERE token_hash = ? AND expires > ?",
                       (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return row["user_id"] if row else None


@router.get("/reset-password")
def reset_page(request: Request, token: str = ""):
    with _db() as conn:
        valid = bool(token) and _reset_user_id(conn, token) is not None
    return _render(request, "reset", token=token, invalid=not valid)


@router.post("/reset-password")
def reset(request: Request, token: str = Form(""), password: str = Form(""), confirm: str = Form("")):
    error = _password_error(password, confirm)
    if error:
        return _render(request, "reset", 400, token=token, error=error)
    with _db() as conn:
        user_id = _reset_user_id(conn, token)
        if user_id is None:
            return _render(request, "reset", 400, token=token, invalid=True)
        # Following the emailed link proves ownership of the address.
        conn.execute("UPDATE users SET pw = ?, verified = 1 WHERE id = ?", (hash_password(password), user_id))
        # One use only, and any other outstanding links for this user die too.
        conn.execute("DELETE FROM resets WHERE user_id = ?", (user_id,))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _signed_in(user, "/", remember=False)


# ---------- Google / GitHub sign-in ----------

def _http_json(url: str, data: dict | None = None, token: str | None = None):
    headers = {"Accept": "application/json", "User-Agent": "rti-sahayak"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data).encode() if data else None
    with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=15) as resp:
        return json.load(resp)


def _oauth_profile(provider: str, token: str) -> tuple[str | None, str]:
    """(verified email or None, display name) from the provider's API."""
    if provider == "google":
        info = _http_json("https://openidconnect.googleapis.com/v1/userinfo", token=token)
        email = info.get("email") if info.get("email_verified") else None
        return email, info.get("name") or (email or "").split("@")[0]
    info = _http_json("https://api.github.com/user", token=token)
    emails = _http_json("https://api.github.com/user/emails", token=token)
    email = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
    return email, info.get("name") or info.get("login") or ""


@router.get("/auth/{provider}/start")
def oauth_start(request: Request, provider: str, next: str = "/"):
    if provider not in dict(oauth_providers()):
        return RedirectResponse("/login", status_code=303)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": os.environ[f"{provider.upper()}_CLIENT_ID"],
        "redirect_uri": f"{_base_url(request)}/auth/{provider}/callback",
        "response_type": "code",
        "scope": PROVIDERS[provider]["scope"],
        "state": state,
    }
    response = RedirectResponse(f"{PROVIDERS[provider]['authorize']}?{urllib.parse.urlencode(params)}", status_code=303)
    # The state rides in a signed, short-lived cookie (CSRF protection for
    # the callback) along with where to go afterwards.
    payload = f"{state}|{_safe_next(next)}"
    response.set_cookie(STATE_COOKIE, f"{_sign(payload)}|{payload}", max_age=600, httponly=True, samesite="lax",
                        secure=_secure_cookies())
    return response


@router.get("/auth/{provider}/callback")
def oauth_callback(request: Request, provider: str, code: str = "", state: str = ""):
    sig, _, payload = request.cookies.get(STATE_COOKIE, "").partition("|")
    expected_state, _, next_url = payload.partition("|")
    if (provider not in dict(oauth_providers()) or not code or not state
            or not hmac.compare_digest(sig, _sign(payload)) or not hmac.compare_digest(state, expected_state)):
        return _render(request, "login", 400, next="/", error="Sign-in was cancelled or expired. Please try again.")
    label = PROVIDERS[provider]["label"]
    try:
        token = _http_json(PROVIDERS[provider]["token"], {
            "client_id": os.environ[f"{provider.upper()}_CLIENT_ID"],
            "client_secret": os.environ[f"{provider.upper()}_CLIENT_SECRET"],
            "code": code,
            "redirect_uri": f"{_base_url(request)}/auth/{provider}/callback",
            "grant_type": "authorization_code",
        })["access_token"]
        email, name = _oauth_profile(provider, token)
    except (OSError, ValueError, KeyError) as e:
        print(f"[auth] ERROR: {provider} sign-in failed: {type(e).__name__}: {e}", file=sys.stderr)
        return _render(request, "login", 502, next=next_url, error=f"Couldn't reach {label}. Please try again.")
    if not email:
        return _render(request, "login", 400, next=next_url,
                       error=f"Your {label} account has no verified email address.")
    email = email.lower()
    with _db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            # Random password nobody knows - they can set a real one any
            # time via "Forgot password".
            conn.execute("INSERT INTO users (name, email, pw, created, verified) VALUES (?, ?, ?, ?, 1)",
                         ((name or email.split("@")[0])[:80], email, hash_password(secrets.token_urlsafe(32)), time.time()))
        elif not user["verified"]:
            # Someone created this account with a password but never proved
            # they own the email. Kill that password (and its sessions) so a
            # squatter who pre-registered the victim's address can't keep access.
            conn.execute("UPDATE users SET pw = ?, verified = 1 WHERE id = ?",
                         (hash_password(secrets.token_urlsafe(32)), user["id"]))
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    response = _signed_in(user, next_url, remember=True)
    response.delete_cookie(STATE_COOKIE)
    return response


# ---------- Account settings ----------

def _account(request: Request, user, status_code: int = 200, **ctx):
    from web.main import templates
    request.state.auth_user = user  # the nav must show the just-saved name
    return templates.TemplateResponse(request, "account.html", {"user": user, **ctx}, status_code=status_code)


@router.get("/account")
def account_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?next=/account", status_code=303)
    return _account(request, user)


@router.post("/account/profile")
def account_profile(request: Request, name: str = Form("")):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?next=/account", status_code=303)
    name = name.strip()
    if not 1 <= len(name) <= 80:
        return _account(request, user, 400, profile_error="Enter your name (up to 80 characters).")
    with _db() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user["id"]))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return _account(request, user, profile_ok="Name updated.")


@router.post("/account/password")
def account_password(request: Request, current: str = Form(""), password: str = Form(""), confirm: str = Form("")):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login?next=/account", status_code=303)
    if _throttled(request):
        error = "Too many attempts. Wait a few minutes and try again."
    elif not verify_password(current, user["pw"]):
        error = "Your current password is incorrect."
    else:
        error = _password_error(password, confirm)
    if error:
        return _account(request, user, 400, password_error=error)
    with _db() as conn:
        conn.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_password(password), user["id"]))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    # New salt = every other session is now invalid; re-sign this one so
    # the person changing it stays logged in, with the same expiry.
    expires = _session_expiry(request)
    response = _account(request, user, password_ok="Password changed. Other devices have been signed out.")
    return _set_session(response, user, expires, persistent=True)


@router.post("/account/delete")
def account_delete(request: Request, confirm_email: str = Form("")):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if confirm_email.strip().lower() != user["email"].lower():
        return _account(request, user, 400, delete_error="Type your email exactly to confirm.")
    with _db() as conn:
        conn.execute("DELETE FROM resets WHERE user_id = ?", (user["id"],))
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response

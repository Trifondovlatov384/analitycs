from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import timedelta
from urllib.parse import quote, unquote

from flask import Flask, jsonify, redirect, request, session

SESSION_FLAG = "dash_authenticated"
SESSION_USER = "dash_username"

# Accounts come only from the environment: DASH_AUTH_USERS="user1:pass1,user2:pass2"
# (or DASH_AUTH_USER + DASH_AUTH_PASSWORD). No passwords live in the repository.
_DEFAULT_USERS: dict[str, str] = {}

PUBLIC_PATHS = frozenset({"/login", "/logout", "/robots.txt", "/favicon.ico"})
PUBLIC_PREFIXES = ("/assets/", "/css/", "/_favicon")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <meta name="googlebot" content="noindex, nofollow, noarchive">
  <title>Вход — Аналитика сделок</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
  <link rel="stylesheet" href="/css/app.css?v=6">
</head>
<body class="login-body">
  <main class="login-card">
    <div class="brand brand--login"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span class="brand-name">Сделки · аналитика</span></div>
    <p class="login-kicker">Закрытый доступ</p>
    <h1 class="login-title">Аналитика сделок</h1>
    <p class="login-subtitle">Войдите, чтобы открыть дашборд</p>
    {error}
    <form method="post" action="/login" class="login-form" autocomplete="on">
      <input type="hidden" name="next" value="{next}">
      <label class="login-label" for="username">Логин</label>
      <input class="login-input" id="username" name="username" type="text" required autofocus autocomplete="username">
      <label class="login-label" for="password">Пароль</label>
      <input class="login-input" id="password" name="password" type="password" required autocomplete="current-password">
      <button class="login-submit" type="submit">Войти</button>
    </form>
  </main>
</body>
</html>
"""


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def load_auth_users() -> dict[str, str]:
    raw = (os.environ.get("DASH_AUTH_USERS") or "").strip()
    if raw:
        users: dict[str, str] = {}
        for part in raw.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            user, password = part.split(":", 1)
            user = user.strip()
            password = password.strip()
            if user and password:
                users[user] = password
        if users:
            return users

    users = dict(_DEFAULT_USERS)
    single_user = (os.environ.get("DASH_AUTH_USER") or "").strip()
    single_pass = os.environ.get("DASH_AUTH_PASSWORD")
    if single_user and single_pass is not None and str(single_pass) != "":
        users[single_user] = str(single_pass)
    return users


_FAILED: dict[str, list[float]] = {}
_WINDOW_S = 15 * 60
_MAX_FAILS = 10


def _too_many_attempts(key: str) -> bool:
    now = time.time()
    hits = [t for t in _FAILED.get(key, []) if now - t < _WINDOW_S]
    _FAILED[key] = hits
    return len(hits) >= _MAX_FAILS


def _note_failure(key: str) -> None:
    _FAILED.setdefault(key, []).append(time.time())


def credentials_ok(username: str, password: str) -> bool:
    users = load_auth_users()
    expected = users.get(username)
    if expected is None:
        # Constant-time-ish miss: compare against dummy digest
        hmac.compare_digest(_digest(password), _digest(""))
        return False
    return hmac.compare_digest(_digest(password), _digest(expected))


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return path.startswith(PUBLIC_PREFIXES)


def _safe_next(raw: str | None) -> str:
    value = unquote(raw or "").strip() or "/"
    if not value.startswith("/") or value.startswith("//") or value.startswith("/login"):
        return "/"
    if value.startswith("/_dash") or value.startswith("/api/"):
        return "/"
    return value


def protect_flask_app(flask_app: Flask) -> None:
    flask_app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("VERCEL") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_NAME="analitycs_session",
    )

    @flask_app.before_request
    def require_login():
        if _is_public(request.path):
            return None
        if session.get(SESSION_FLAG):
            return None
        if request.path.startswith("/api/") or request.path.startswith("/js/"):
            return jsonify({"error": "unauthorized"}), 401
        nxt = quote(request.full_path if request.query_string else request.path, safe="/")
        return redirect(f"/login?next={nxt}")

    @flask_app.after_request
    def noindex_headers(resp):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return resp

    @flask_app.route("/robots.txt")
    def robots_txt():
        body = "User-agent: *\nDisallow: /\n"
        return body, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @flask_app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get(SESSION_FLAG):
            return redirect(_safe_next(request.values.get("next")))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            client = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
            if _too_many_attempts(client):
                error = '<p class="login-error">Слишком много попыток. Попробуйте через 15 минут</p>'
            elif not load_auth_users():
                error = '<p class="login-error">Доступ не настроен: задайте DASH_AUTH_USERS</p>'
            elif credentials_ok(username, password):
                session.clear()
                session.permanent = True
                session[SESSION_FLAG] = True
                session[SESSION_USER] = username
                return redirect(_safe_next(request.form.get("next") or request.args.get("next")))
            else:
                _note_failure(client)
                error = '<p class="login-error">Неверный логин или пароль</p>'
        nxt = _safe_next(request.values.get("next"))
        html = LOGIN_HTML.replace("{error}", error).replace("{next}", nxt.replace('"', "&quot;"))
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @flask_app.route("/logout")
    def logout():
        session.clear()
        return redirect("/login")

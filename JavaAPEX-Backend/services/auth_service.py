import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import os
from urllib.parse import urlsplit


def _get_github_session():
    """Create a requests session with proxy disabled for GitHub API calls."""
    session = requests.Session()
    # Disable proxy for GitHub
    session.proxies = {'http': None, 'https': None}
    session.trust_env = False
    return session


router = APIRouter()

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI", "").strip()
print(f"[AUTH_SERVICE] GITHUB_REDIRECT_URI override: {REDIRECT_URI or '[auto]'}")


def _origin_from_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_frontend_origin(request: Request) -> str:
    configured_origin = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/")
    if configured_origin:
        return configured_origin

    for header in ("origin", "referer"):
        candidate = request.headers.get(header, "").strip()
        if not candidate:
            continue
        origin = _origin_from_url(candidate)
        if origin:
            return origin

    return str(request.base_url).rstrip("/")


def resolve_redirect_uri(request: Request) -> str:
    if REDIRECT_URI:
        return REDIRECT_URI
    return f"{resolve_frontend_origin(request)}/auth/callback"


def oauth_not_configured_response() -> JSONResponse:
    return JSONResponse(
        {"error": "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET."},
        status_code=500,
    )

@router.get("/auth/github/login")
def github_login(request: Request):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        return oauth_not_configured_response()

    redirect_uri = resolve_redirect_uri(request)
    print(f"[AUTH_SERVICE] /auth/github/login using redirect_uri: {redirect_uri}")
    github_auth_url = (
        f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}&scope=repo,user"
    )
    return RedirectResponse(github_auth_url)

@router.get("/auth/github/callback")
def github_callback(code: str, request: Request):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        return oauth_not_configured_response()

    redirect_uri = resolve_redirect_uri(request)
    session = _get_github_session()
    
    token_resp = session.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    token_json = token_resp.json()
    access_token = token_json.get("access_token")
    if not access_token:
        return JSONResponse({"error": "Failed to get access token"}, status_code=400)
    
    user_resp = session.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {access_token}"},
        timeout=30,
    )
    user_info = user_resp.json()
    return {"access_token": access_token, "user": user_info}

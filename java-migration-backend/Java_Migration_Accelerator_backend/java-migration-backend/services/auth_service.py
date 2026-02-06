import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
import os

router = APIRouter()

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "Ov23livUCegqUQNlmOgt")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "1c9570628d5ef5a79837d2eb27f648489d003ed3")
REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI", "http://localhost:8001/auth/callback")
print(f"[AUTH_SERVICE] GITHUB_REDIRECT_URI in use: {REDIRECT_URI}")

@router.get("/auth/github/login")
def github_login():
    print(f"[AUTH_SERVICE] /auth/github/login using redirect_uri: {REDIRECT_URI}")
    github_auth_url = (
        f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&scope=repo,user"
    )
    return RedirectResponse(github_auth_url)

@router.get("/auth/github/callback")
def github_callback(code: str):
    token_resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    token_json = token_resp.json()
    access_token = token_json.get("access_token")
    if not access_token:
        return JSONResponse({"error": "Failed to get access token"}, status_code=400)
    user_resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {access_token}"}
    )
    user_info = user_resp.json()
    return {"access_token": access_token, "user": user_info}

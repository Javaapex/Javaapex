"""Standalone test: proves the Ford LLM 429 rotation + cooldown fix works.

Simulates the exact scenario from the logs:
  - gemini-3.5-flash is spend-capped (HTTP 429)
  - gemini-3.1-pro works (HTTP 200)

Verifies:
  1. On 429 we do NOT retry the same capped model 5x — we rotate immediately.
  2. The capped model is put on cooldown.
  3. A SECOND call skips the capped model entirely (no more hammering).
  4. extra_body.models never routes back to a cooling model.
"""
import asyncio
import time

import httpx

from services import ford_llm_service as mod


def build_service():
    svc = mod.FordLLMService.__new__(mod.FordLLMService)
    svc.enabled = True
    svc.api_endpoint = "https://fake/chat/completions"
    svc.api_key = "fake"
    svc.auth_type = "bearer"
    svc.model = "gemini-3.5-flash"
    svc.extra_models = ["gemini-3.5-flash", "gemini-3.1-pro"]
    svc.fallback_models = ["gemini-3.1-pro", "gemini-3.5-flash"]
    svc.timeout = 5
    svc.max_retries = 5
    svc.temperature = 0.1
    svc.max_tokens = 256
    svc.proxy_url = ""
    svc.verify_ssl = False
    svc._oauth_token = None
    svc._oauth_token_expiry = 0.0
    svc._model_cooldowns = {}

    async def _fake_token():
        return "fake-token"

    svc._get_auth_token = _fake_token
    return svc


calls = []


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("POST", "https://fake"),
                response=self,
            )


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        primary = json["model"]
        routed = json.get("extra_body", {}).get("models", [primary])
        calls.append((primary, routed))
        if primary == "gemini-3.5-flash":
            return FakeResponse(
                429,
                text='{"error":{"message":"Too much spend: model '
                'gemini-3.5-flash is limited to $5 per 600 seconds"}}',
            )
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "OK from " + primary}}], "usage": {}},
        )


async def main():
    mod.httpx.AsyncClient = FakeClient  # patch network
    svc = build_service()

    ok = True

    print("=== Call #1 (cold start) ===")
    r = await svc.chat_completion([{"role": "user", "content": "hi"}])
    print("  RESULT:", r["model"], "->", r["text"])
    print("  gateway calls:", calls)
    # gemini-3.5-flash should be tried once (429) then rotate to gemini-3.1-pro
    flash_attempts = sum(1 for c in calls if c[0] == "gemini-3.5-flash")
    print(f"  gemini-3.5-flash attempts: {flash_attempts} (expected 1, NOT 5)")
    if flash_attempts != 1:
        ok = False
        print("  FAIL: capped model was retried more than once")
    if r["model"] != "gemini-3.1-pro":
        ok = False
        print("  FAIL: did not rotate to working fallback")
    cd = {k: round(v - time.time()) for k, v in svc._model_cooldowns.items()}
    print("  cooldowns:", cd)
    if "gemini-3.5-flash" not in svc._model_cooldowns:
        ok = False
        print("  FAIL: capped model was not put on cooldown")

    calls.clear()
    print("\n=== Call #2 (should SKIP capped model entirely) ===")
    r = await svc.chat_completion([{"role": "user", "content": "again"}])
    print("  RESULT:", r["model"], "->", r["text"])
    print("  gateway calls:", calls)
    hit_capped = any(
        "gemini-3.5-flash" in routed or primary == "gemini-3.5-flash"
        for primary, routed in calls
    )
    if hit_capped:
        ok = False
        print("  FAIL: capped model was contacted again while on cooldown")
    else:
        print("  PASS: capped model fully skipped (no more hammering)")

    print("\n" + ("ALL CHECKS PASSED ✅" if ok else "SOME CHECKS FAILED ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

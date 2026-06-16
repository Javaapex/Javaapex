"""Quick test: hit the strategy streaming endpoint and print the response."""
import httpx, json, sys

payload = {
    "question": "can you list the vulnerabilities that might require attention?",
    "repo_url": "https://github.com/example/pinnacle-middleware",
    "analysis": {
        "name": "pinnacle-middleware",
        "risk_level": "medium",
        "java_version": "8",
        "build_tool": "Maven",
        "dependencies": [
            {"name": "log4j-core", "version": "2.14.1", "risk": "high", "reason": "CVE-2021-44228 Log4Shell"},
            {"name": "spring-core", "version": "5.3.9", "risk": "low"},
            {"name": "commons-collections", "version": "3.2.1", "risk": "high", "reason": "Deserialization vulnerability"},
        ],
    },
    "strategy_context": {
        "assessment": {"risk_level": "medium", "build_tool": "Maven", "java_version": "8", "test_count": 42, "dependency_count": 15},
        "strategy": {"source_version": "8", "target_version": "17"},
        "attention_dependencies": [
            {"name": "log4j-core", "version": "2.14.1", "risk": "high", "reason": "CVE-2021-44228"},
            {"name": "commons-collections", "version": "3.2.1", "risk": "high", "reason": "Deserialization vulnerability"},
        ],
    },
}

with httpx.Client(timeout=90.0) as client:
    with client.stream("POST", "http://localhost:8000/api/strategy/query/stream",
                       json=payload, headers={"Content-Type": "application/json"}) as resp:
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line.replace("data:", "", 1).strip())
            evt = data.get("type") or ""
            if "chunk" in data:
                sys.stdout.write(data["chunk"])
                sys.stdout.flush()
            elif "parsed" in data:
                print("\n\n=== FINAL ===")
                parsed = data.get("parsed", {})
                print("Answer:", (parsed.get("answer") or "")[:500])
                details = data.get("details", {})
                print("Provider:", details.get("provider"), "| Model:", details.get("model"))
                print("Fallback?", details.get("fallback", False))

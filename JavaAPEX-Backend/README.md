# Java-Apex-Backend
Backend Python FastApi based project for Java Apex Accelerator 


## LLM Configuration
Set one of these for AI features:
- `OPENAI_API_KEY` (recommended for hosted model APIs)
- `LLM_API_KEY` (generic alias used by this project)

Optional overrides:
- `LLM_BASE_URL` (default: `https://api.openai.com/v1`)
- `LLM_MODEL` (default: `gpt-4.1-mini`)
- `LLM_SUB_MODEL` (optional; only used for compatible routers that accept extra model routing)

Free/local option:
- Use `ollama` provider in the UI/API and run a local Ollama server (`OLLAMA_URL`, `OLLAMA_MODEL`).

## Build Preflight (Maven)
Microservice output now runs a mandatory Maven preflight build before results are returned.

- Production default: `MIGRATOR_REQUIRE_MAVEN_PREFLIGHT=true`
- Set explicit Maven binary if needed: `MIGRATOR_MAVEN_CMD=/usr/bin/mvn` (Linux) or `MIGRATOR_MAVEN_CMD=C:\path\to\mvn.cmd` (Windows)
- Local fallback when Maven is missing: `MIGRATOR_PREFLIGHT_USE_DOCKER=true` with `MIGRATOR_PREFLIGHT_DOCKER_IMAGE=maven:3.9.9-eclipse-temurin-17`

If Maven is unavailable and strict mode is on, migration fails fast instead of returning broken output.

### Run Backend In Docker (Recommended)
```powershell
cd JavaAPEX-Backend
.\start-backend-docker.ps1
```

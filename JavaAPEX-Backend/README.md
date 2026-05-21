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

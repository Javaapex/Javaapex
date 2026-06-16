# Java Migration Accelerator (JavaAPEX)

Comprehensive toolkit to analyze, document, and automate Java migrations (targeting Java 7 → Java 18). The project provides a FastAPI backend, a React + Vite frontend, Celery-based background processing, and integrations with Git hosting and code-quality tooling.

**Main Functionality**
- Repository analysis and dependency extraction
- Automated migration orchestration using OpenRewrite and custom migration services
- BRD (technical document) generation (PDF/HTML) from repository analysis
- LLM-driven recommendations and migration guidance
- Background job processing for long-running analyses and migrations (Celery)
- Support for local project uploads and ephemeral workspace cloning

**Tech Stack**
- Backend: Python 3.11+, FastAPI, Uvicorn
- Background jobs: Celery, Redis (broker), optional Postgres for persistence
- Frontend: React (18/19) + Vite + TypeScript
- Integrations: GitHub (PyGithub), GitLab, SonarQube, FOSSA
- Other libs: httpx, python-multipart, reportlab, python-docx, javalang
- Dev tools: pylint, bandit, radon, pre-commit (optional)

**Architecture (high level)**
- Frontend (`JavaAPEX-Frontend`) — Single-page app built with Vite/React. Communicates with the backend via REST.
- Backend API (`JavaAPEX-Backend`) — FastAPI application exposing endpoints for repository analysis, migration jobs, BRD generation, and orchestration.
- Services — modular Python services under `JavaAPEX-Backend/services` handling integrations (GitHub/GitLab), LLM helpers, migration orchestration, and artifact generation.
- Job Queue — Celery workers process long-running jobs; Redis is used as the broker and (optionally) result backend.
- Persistence — Postgres (via `psycopg2-binary`) is used for job storage and runtime metadata when enabled.
- Document generation — `pdf_generator` builds BRD and export artifacts.

**Repository layout (selected paths)**
- `JavaAPEX-Backend/` — FastAPI backend and services
- `JavaAPEX-Backend/main.py` — Backend entrypoint and API registration
- `JavaAPEX-Backend/requirements.txt` — Python dependencies
- `JavaAPEX-Backend/DEPLOY_RENDER.md` and `JavaAPEX-Backend/render.yaml` — deployment notes and Render blueprint
- `JavaAPEX-Backend/services/` — service implementations (GitHub, Celery, LLM helpers, etc.)
- `JavaAPEX-Frontend/` — Vite + React frontend
- `JavaAPEX-Frontend/package.json` — frontend scripts and dependencies

**Environment & configuration**
- Copy or create a `.env` file in `JavaAPEX-Backend/` with values for:
  - `APP_HOST`, `APP_PORT` (backend binding)
  - `DEFAULT_GITHUB_TOKEN` (recommended for GitHub API calls)
  - `CORS_ALLOWED_ORIGINS` (comma-separated)
  - `REDIS_URL` (e.g. `redis://localhost:6379/0`)
  - `DATABASE_URL` (Postgres connection string)
  - Any LLM/provider tokens (e.g. `HF_TOKEN`, `OPENAI_API_KEY`) referenced in `utils/config.py`

**Local development — Backend**
1. Change directory and install dependencies (without using a virtual environment):

```powershell
cd JavaAPEX-Backend
pip install -r requirements.txt
```

2. Run the backend (development reload):

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Local development — Frontend**
1. Change directory and install Node deps:

```bash
cd JavaAPEX-Frontend
npm install
```

2. Start dev server:

```bash
npm run dev
```

**Celery worker (background jobs)**
- Ensure Redis is running and `REDIS_URL` is set in the environment.
- Start a worker with the project's Celery app:

```bash
python -m celery -A services.celery_app:celery_app worker --loglevel=info --pool=solo
```

**Docker / Compose**
- The repository includes Dockerfiles for backend and frontend. Example: build and run backend container:

```bash
cd JavaAPEX-Backend
docker build -t javaapex-backend .
docker run -p 8000:8000 --env-file .env javaapex-backend
```

- For combined stacks, see `JavaAPEX-Frontend/docker-compose.yml`.

**Deployment notes**
- `JavaAPEX-Backend/DEPLOY_RENDER.md` contains a Render-specific blueprint and guidance.
- For production, ensure Redis, Postgres, and any LLM tokens are secured and configured via secrets.

**Troubleshooting & tips**
- Large uploads: the backend includes middleware to detect and handle large file uploads. Adjust request limits if needed.
- Request tracing: the backend attaches `X-Request-ID` to responses for correlated logs.
- Sensitive query parameters: keys listed in `main.py` are redacted from logs.


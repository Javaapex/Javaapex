# Copilot Instructions for Java Migration Accelerator

## Project Overview
- **Purpose:** Automates Java 7→21 migrations, including framework upgrades (Spring Boot, Jakarta EE, JUnit), code quality, and reporting.
- **Architecture:**
  - **Backend:** FastAPI (Python) in `java-migration-backend/Java_Migration_Accelerator_backend/java-migration-backend/`
    - Core logic in `services/` (migration, GitHub/GitLab, email, SonarQube)
    - Entry point: `main.py`
  - **Frontend:** React (TypeScript) in `java-migration-frontend/`
    - UI logic in `src/components/`, API calls in `src/services/api.ts`
  - **Example Java project:** `test-java-project/` (used for migration/testing)

## Key Workflows
- **Backend:**
  - Start with `python main.py` (after installing requirements and configuring `.env`)
  - Main API endpoints:
    - `/api/migration/start` (POST): Start migration
    - `/api/migration/{job_id}` (GET): Migration status
    - `/api/migration/preview` (POST): Preview changes
    - `/api/github/repos`, `/api/gitlab/repos`: List repos
    - `/api/migration/{job_id}/report`: Download HTML report
- **Frontend:**
  - Start with `npm run dev` in `java-migration-frontend/`
  - Connects to backend at `localhost:8001` (API)
  - Main UI: Migration wizard, dashboard, logs, reports

## Patterns & Conventions
- **Migration logic:**
  - Uses OpenRewrite recipes (see `migration_service.py`)
  - Supports multi-step migrations (Java version, frameworks, business logic)
  - Migration jobs are tracked by UUID/job_id
- **Integrations:**
  - GitHub/GitLab via tokens (set in `.env`)
  - SonarQube for code quality (optional)
  - Email notifications via SMTP
- **Reports:**
  - HTML reports and JMeter test plans generated per migration job
- **Environment:**
  - All secrets/tokens in `.env` (see README for keys)
  - Docker, Railway, Render, Vercel supported for deployment

## Examples
- See `README.md` for sample migration payloads and workflow
- Example Java project: `test-java-project/`

## Tips for AI Agents
- Reference `README.md` for up-to-date workflows and API usage
- Use service boundaries: keep backend logic in `services/`, UI logic in `components/`
- When adding migration types, update both backend (migration_service.py) and frontend wizard
- For new integrations, follow the pattern in `services/` (backend) and `api.ts` (frontend)
- Use `.env.example` as a template for new environment variables

---
For more, see [README.md](../README.md) and backend service files for implementation details.

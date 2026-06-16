# Render Deployment

This backend is ready to deploy to Render with Docker-based web and worker services.

## Why Docker

The API is written in FastAPI, but parts of the migration pipeline also rely on Java tooling, Git, Maven, and Gradle. Using Docker ensures those runtime dependencies are present in Render.

## Files Added

- `Dockerfile`: builds the app with Python 3.11, OpenJDK 17, SonarScanner, and FOSSA CLI
- `docker/start-web.sh`: startup command for the FastAPI web service
- `docker/start-worker.sh`: startup command for the Celery worker
- `render.yaml`: Render Blueprint for one web service, one worker, and Redis
- `.env.example`: safe template for required and optional environment variables

## Deploy Steps

1. Push this project to GitHub, GitLab, or Bitbucket.
2. In Render, create a new Blueprint or services from the repo.
3. If using the Blueprint flow, Render will read `render.yaml` automatically.
4. Fill in the secret environment variables shown in the service settings.
5. Deploy the Blueprint so both the web service and the worker are created.

## Runtime Details

- Health check: `/health`
- API root: `/`
- Interactive docs: `/docs`
- The container listens on Render's injected `PORT` automatically.
- The default Docker `CMD` starts the web service; Render overrides it for the worker using `dockerCommand`.

## Important Notes

- `WORK_DIR` is set to `/tmp/migrations`, which works with Render's ephemeral filesystem.
- Repository discovery now uses a clone-first flow backed by managed workspaces under `WORK_DIR/repo_workspaces`.
- Celery-backed migrations require the `java-apex-worker` service from `render.yaml`. Without it, the backend can fall back to in-process execution if enabled.
- Render free plans do not support background workers, so the worker Blueprint is pinned to `starter`.
- Optional tuning env vars for large repositories: `REPO_WORKSPACE_TTL_SEC`, `REPO_CLONE_TIMEOUT_SEC`, `REPO_ANALYSIS_MAX_JAVA_FILES`, `REPO_ANALYSIS_MAX_ENDPOINT_FILES`, and `REPO_FILE_CONTENT_MAX_BYTES`.
- Do not commit a real `.env` file. Use `.env.example` as the template instead.
- The current Blueprint keeps the web service on `free` for easy testing, but the worker uses `starter`.
- If you need always-on behavior, better performance, or outbound SMTP on ports like `587`, switch the service plan from `free` to `starter` or higher in Render.
- If you use GitHub OAuth, set `FRONTEND_ORIGIN` and, if needed, `GITHUB_REDIRECT_URI` to your deployed frontend URL.
- CORS now resolves in this order: `CORS_ALLOWED_ORIGINS` (comma-separated list), then `FRONTEND_ORIGIN`, then the built-in local/default origins in `main.py`.

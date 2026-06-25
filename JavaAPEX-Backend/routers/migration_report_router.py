"""Migration report and artifact download endpoints."""

from __future__ import annotations

import io
import logging
import os
import zipfile
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse


logger = logging.getLogger(__name__)


def create_migration_report_router(
    *,
    artifact_service: Any,
    job_service: Any,
    generate_modern_html_report: Callable[[Any, list[str]], str],
    generate_testcase_doc_markdown: Callable[[Any, str], str],
    generate_testcase_doc_docx: Callable[[Any, str], str],
    generate_testcase_html_report: Callable[..., str],
    generate_unit_test_html_report: Callable[..., str],
    markdown_to_simple_html: Callable[[str], str],
    generate_jmeter_test_plan: Callable[[Any], str],
) -> APIRouter:
    router = APIRouter(tags=["migration-reports"])

    @router.get("/migration/{job_id}/report")
    async def download_migration_report(job_id: str):
        """Generate and download migration report as HTML."""
        available_job_ids = [job.job_id for job in job_service.list_jobs()]
        logger.debug("Report requested for job_id=%s available_jobs=%s", job_id, available_job_ids)

        if not job_service.has_job(job_id):
            logger.debug("Migration report job not found for job_id=%s", job_id)
            raise HTTPException(status_code=404, detail=f"Migration job {job_id} not found")

        job = job_service.get_job(job_id, include_runtime_detail=True)
        logs = getattr(job, "migration_log", [])

        logger.debug("Generating migration report for job_id=%s status=%s logs=%s", job_id, job.status, len(logs))

        clone_path = artifact_service.maybe_restore_clone_path(job, purpose="report")
        if clone_path and os.path.isdir(clone_path):
            html_content = generate_testcase_html_report(
                job,
                clone_path,
                report_title="Java Migration and Quality Report",
            )
        else:
            html_content = generate_modern_html_report(job, logs)
        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f"attachment; filename=migration-report-{job_id}.html",
            },
        )

    @router.get("/migration/{job_id}/sonar-report-pdf")
    async def download_sonar_report_pdf(job_id: str):
        """Generate and download a premium Sonar modernization/security assessment PDF."""
        job = job_service.require_job(job_id, detail=f"Migration job {job_id} not found", include_runtime_detail=True)
        sonar_report = getattr(job, "sonar_report", None) or {}
        if not sonar_report and not getattr(job, "sonar_scan_mode", None):
            raise HTTPException(status_code=400, detail="No Sonar results are available for this migration job.")

        try:
            from pdf_generator.generator import build_sonar_assessment_pdf
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Sonar PDF dependencies are not available on the server. Install backend requirements and retry. ({exc})",
            )

        try:
            pdf_bytes = build_sonar_assessment_pdf(job)
        except Exception as exc:
            logger.exception("Failed to generate Sonar PDF for job %s", job_id)
            raise HTTPException(status_code=500, detail=f"Failed to generate Sonar PDF: {exc}")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=sonar-modernization-assessment-{job_id}.pdf",
            },
        )

    @router.get("/migration/{job_id}/testcase-doc")
    async def download_testcase_doc(job_id: str):
        """Download the Markdown testcase + change report for a migration job."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        doc_md = generate_testcase_doc_markdown(job, clone_path)
        doc_path = artifact_service.persist_testcase_markdown(job_id, job, clone_path, doc_md)
        return FileResponse(
            doc_path,
            media_type="text/markdown",
            filename=f"testcase-and-changes-{job_id}.md",
        )

    @router.get("/migration/{job_id}/testcase-docx")
    async def download_testcase_docx(job_id: str):
        """Download the DOCX testcase + change report for a migration job."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        doc_md = generate_testcase_doc_markdown(job, clone_path)
        artifact_service.persist_testcase_markdown(job_id, job, clone_path, doc_md)

        try:
            docx_path = generate_testcase_doc_docx(job, clone_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to generate DOCX: {exc}")

        return FileResponse(
            docx_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"testcase-and-changes-{job_id}.docx",
        )

    @router.get("/migration/{job_id}/testcase-report")
    async def download_testcase_report(job_id: str):
        """Download the testcase + change report as a styled HTML document."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        html_content = generate_testcase_html_report(
            job,
            clone_path,
            report_title="Test Case Generation and Validation",
        )
        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f"attachment; filename=testcase-and-changes-{job_id}.html",
            },
        )

    @router.get("/migration/{job_id}/unit-test-report")
    async def download_unit_test_report(job_id: str):
        """Download the unit test report as a styled HTML document."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)

        details_html = ""
        clone_path = artifact_service.maybe_restore_clone_path(job, purpose="unit-test-report")
        if clone_path and os.path.isdir(clone_path):
            try:
                md = generate_testcase_doc_markdown(job, clone_path)
                details_html = markdown_to_simple_html(md)
            except Exception:
                details_html = ""

        html_content = generate_unit_test_html_report(
            job,
            details_html=details_html,
            clone_path=clone_path,
            report_title="Unit Test Generation Report",
        )
        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f"attachment; filename=unit-test-report-{job_id}.html",
            },
        )

    @router.get("/migration/{job_id}/jmeter")
    async def generate_jmeter_test(job_id: str):
        """Generate and download JMeter test plan for migrated APIs."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        artifact_service.set_jmeter_base_url(job)

        jmeter_content = generate_jmeter_test_plan(job)
        return Response(
            content=jmeter_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=migration-test-{job_id}.jmx",
            },
        )

    @router.get("/migration/{job_id}/functional-test-file")
    async def get_functional_test_file(
        job_id: str,
        path: str = Query(..., description="Relative path of the functional test file under .functional_tests"),
    ):
        """Return the content of a single generated functional test file for viewing or download."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        functional_tests_root = os.path.normpath(os.path.join(clone_path, ".functional_tests"))
        requested_path = os.path.normpath(os.path.join(functional_tests_root, path))

        # Prevent path traversal
        if not requested_path.startswith(functional_tests_root + os.sep) and requested_path != functional_tests_root:
            raise HTTPException(status_code=400, detail="Invalid file path.")
        if not os.path.isfile(requested_path):
            raise HTTPException(status_code=404, detail=f"Functional test file not found: {path}")

        # Determine mime type from extension
        ext = os.path.splitext(requested_path)[1].lower()
        mime_map = {
            ".java": "text/x-java-source",
            ".ts": "text/typescript",
            ".js": "text/javascript",
            ".json": "application/json",
            ".xml": "application/xml",
            ".sh": "text/x-shellscript",
            ".py": "text/x-python",
            ".yaml": "text/yaml",
            ".yml": "text/yaml",
        }
        media_type = mime_map.get(ext, "text/plain")
        filename = os.path.basename(requested_path)

        try:
            with open(requested_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )

    @router.get("/migration/{job_id}/functional-tests-zip")
    async def download_functional_tests_zip(job_id: str):
        """Download all generated functional test files as a ZIP archive."""
        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        functional_tests_root = os.path.join(clone_path, ".functional_tests")
        if not os.path.isdir(functional_tests_root):
            raise HTTPException(status_code=404, detail="No functional test files found for this job.")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirnames, filenames in os.walk(functional_tests_root):
                for fname in filenames:
                    abs_path = os.path.join(dirpath, fname)
                    arc_name = os.path.relpath(abs_path, functional_tests_root)
                    zf.write(abs_path, arc_name)
        buf.seek(0)

        if buf.getbuffer().nbytes == 0:
            raise HTTPException(status_code=404, detail="No functional test files found to archive.")

        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=functional-tests-{job_id}.zip",
            },
        )

    # ── Playwright / Selenium HTML report serving ──────────────────────
    @router.get("/migration/{job_id}/functional-test-report/{tool}")
    async def get_functional_test_report_redirect(
        job_id: str,
        tool: str,
        request: Request,
    ):
        """Redirect bare tool URL to trailing-slash so relative assets in Allure/Playwright resolve correctly."""
        known_tools = {"playwright", "selenium", "surefire", "allure", "playwrightallure", "restassured", "gradle", "internal"}
        tool_lower = tool.lower().replace("_", "").replace("-", "")
        if tool_lower in known_tools:
            # 301 redirect: /functional-test-report/allure → /functional-test-report/allure/
            return RedirectResponse(url=str(request.url) + "/", status_code=301)
        raise HTTPException(status_code=404, detail=f"No {tool} HTML report found for this job.")

    @router.get("/migration/{job_id}/functional-test-report/{tool}/")
    @router.get("/migration/{job_id}/functional-test-report/{tool}/{file_path:path}")
    async def get_functional_test_report(
        job_id: str,
        tool: str,
        file_path: str = "index.html",
    ):
        """Serve Playwright / Selenium HTML report files (index.html + assets)."""
        if not file_path:
            file_path = "index.html"

        job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
        clone_path = artifact_service.require_clone_path(job)

        # Map tool name → report directory inside .functional_tests/
        selenium_reports = os.path.join(clone_path, ".functional_tests", "selenium", "reports")
        report_dirs = {
            "playwright": os.path.join(clone_path, ".functional_tests", "playwright", "playwright-report"),
            "playwrightallure": os.path.join(clone_path, ".functional_tests", "playwright", "allure-report"),
            "selenium": selenium_reports,
            "surefire": selenium_reports,
            "allure": os.path.join(selenium_reports, "allure-report"),
            "restassured": os.path.join(clone_path, ".functional_tests", "restassured", "target", "surefire-reports"),
            "gradle": os.path.join(clone_path, ".functional_tests", "gradle"),
            "internal": os.path.join(clone_path, ".functional_tests", "internal"),
        }

        tool_lower = tool.lower().replace("_", "").replace("-", "")
        report_root = report_dirs.get(tool_lower)
        if not report_root or not os.path.isdir(report_root):
            raise HTTPException(status_code=404, detail=f"No {tool} HTML report found for this job.")

        report_root_norm = os.path.normpath(report_root)
        requested_path = os.path.normpath(os.path.join(report_root_norm, file_path))

        # Prevent path traversal
        if not requested_path.startswith(report_root_norm + os.sep) and requested_path != report_root_norm:
            raise HTTPException(status_code=400, detail="Invalid file path.")
        if not os.path.isfile(requested_path):
            raise HTTPException(status_code=404, detail=f"Report file not found: {file_path}")

        ext = os.path.splitext(requested_path)[1].lower()
        mime_map = {
            ".html": "text/html",
            ".js": "application/javascript",
            ".mjs": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".gif": "image/gif",
            ".ico": "image/x-icon",
            ".zip": "application/zip",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
            ".ttf": "font/ttf",
            ".xml": "application/xml",
            ".webm": "video/webm",
            ".mp4": "video/mp4",
            ".map": "application/json",
            ".txt": "text/plain",
        }
        media_type = mime_map.get(ext, "application/octet-stream")

        return FileResponse(requested_path, media_type=media_type)

    return router

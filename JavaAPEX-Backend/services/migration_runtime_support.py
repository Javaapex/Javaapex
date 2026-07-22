"""Shared runtime helpers for migration execution and reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import re
import shutil
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from models.job_models import (
    FileDiffEntry,
    IssueSeverity,
    IssueStatus,
    MigrationIssue,
    MigrationResult,
)
from services.local_project_service import local_project_service
from utils.config import DEFAULT_GITHUB_TOKEN, DEFAULT_WORK_DIR


def first_nonempty_token(*values: Optional[str]) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def effective_github_token(token: str = "", github_token: str = "") -> str:
    return first_nonempty_token(github_token, token, DEFAULT_GITHUB_TOKEN)


def is_local_project_reference(source_reference: str) -> bool:
    return (source_reference or "").startswith("local://")


def extract_local_project_path(source_reference: str) -> str:
    return (source_reference or "").replace("local://", "", 1)


async def resolve_source_project_path(
    source_repo_url: str,
    repo_service: Any,
    source_token: str,
) -> str:
    if is_local_project_reference(source_repo_url):
        local_path = extract_local_project_path(source_repo_url)
        return local_project_service.resolve_local_project_path(local_path)
    if repo_service.__class__.__name__ == "GitHubService":
        from services.github_clone_analysis_service import github_clone_analysis_service

        workspace = await github_clone_analysis_service.prepare_workspace(
            repo_reference=source_repo_url,
            token=source_token,
            force_refresh=False,
        )
        return workspace.workspace_path
    return await repo_service.clone_repository(source_token, source_repo_url)


async def prepare_source_working_copy(
    source_repo_url: str,
    repo_service: Any,
    source_token: str,
) -> str:
    if is_local_project_reference(source_repo_url):
        local_path = extract_local_project_path(source_repo_url)
        return await local_project_service.stage_project_copy(local_path)
    if repo_service.__class__.__name__ == "GitHubService":
        from services.github_clone_analysis_service import github_clone_analysis_service

        working_copy_root = os.path.join(DEFAULT_WORK_DIR, "migration_job_copies")
        return await github_clone_analysis_service.stage_workspace_copy(
            repo_reference=source_repo_url,
            target_root=working_copy_root,
            token=source_token,
            force_refresh=False,
        )
    return await repo_service.clone_repository(source_token, source_repo_url)


def infer_local_project_name(source_repo_url: str) -> str:
    local_path = extract_local_project_path(source_repo_url)
    normalized = local_project_service.resolve_local_project_path(local_path)
    return os.path.basename(normalized.rstrip("\\/")) or "local-project"


def parse_target_repository_destination(target_repo_name: str, default_owner: str = "Javaapex") -> tuple[str, str]:
    raw_value = (target_repo_name or "").strip().rstrip("/")
    if not raw_value:
        return default_owner, ""

    owner = default_owner
    repo_name = ""

    if "://" in raw_value:
        parsed = urlparse(raw_value)
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2:
            owner = path_parts[0]
            repo_name = path_parts[1]
        elif path_parts:
            repo_name = path_parts[-1]
    elif "/" in raw_value:
        path_parts = [part for part in raw_value.split("/") if part]
        if len(path_parts) >= 2:
            owner = path_parts[0]
            repo_name = path_parts[1]
        elif path_parts:
            repo_name = path_parts[-1]
    else:
        repo_name = raw_value

    if repo_name.lower().endswith(".git"):
        repo_name = repo_name[:-4]

    owner = re.sub(r"[^A-Za-z0-9._-]+", "-", owner).strip("-") or default_owner
    repo_name = re.sub(r"[^A-Za-z0-9._-]+", "-", repo_name).strip("-")
    return owner, repo_name


def sanitize_local_publish_folder_name(folder_name: str, fallback_name: str) -> str:
    raw_value = (folder_name or "").strip().rstrip("\\/")
    candidate = raw_value

    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.path.rstrip("\\/")

    candidate = os.path.basename(candidate) if candidate else ""
    if candidate.lower().endswith(".git"):
        candidate = candidate[:-4]

    candidate = re.sub(r"[<>:\"/\\|?*\x00-\x1F]+", "-", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")

    fallback = re.sub(r"[<>:\"/\\|?*\x00-\x1F]+", "-", fallback_name or "repo-Migrated")
    fallback = re.sub(r"\s+", " ", fallback).strip(" .") or "repo-Migrated"
    return candidate or fallback


def publish_migrated_project_locally(
    clone_path: str,
    requested_folder_name: str,
    default_folder_name: str,
) -> str:
    local_publish_root = os.path.join(DEFAULT_WORK_DIR, "local_migration_outputs")
    os.makedirs(local_publish_root, exist_ok=True)

    requested_path = (requested_folder_name or "").strip().strip("\"'")
    use_explicit_absolute_path = os.path.isabs(requested_path)

    if use_explicit_absolute_path:
        destination_path = os.path.abspath(os.path.normpath(requested_path))
    else:
        folder_name = sanitize_local_publish_folder_name(requested_folder_name, default_folder_name)
        destination_path = os.path.join(local_publish_root, folder_name)

    if os.path.abspath(destination_path) == os.path.abspath(clone_path):
        return destination_path

    if os.path.exists(destination_path):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination_parent = os.path.dirname(destination_path)
        destination_name = os.path.basename(destination_path.rstrip("\\/")) or default_folder_name
        destination_path = os.path.join(destination_parent, f"{destination_name}-{timestamp}")

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    shutil.move(clone_path, destination_path)
    return destination_path


def _run_cmd(cwd: str, args: List[str]) -> Dict[str, Any]:
    import subprocess

    try:
        process = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        return {
            "ok": process.returncode == 0,
            "code": process.returncode,
            "stdout": (process.stdout or "").strip(),
            "stderr": (process.stderr or "").strip(),
        }
    except Exception as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}


def _normalize_git_path(path: str) -> str:
    return path.strip().strip('"').replace("\\", "/")


def _parse_git_status_change(line: str) -> Optional[Dict[str, str]]:
    if not line:
        return None

    if line.startswith("?? "):
        file_path = _normalize_git_path(line[3:])
        return {
            "file_path": file_path,
            "old_path": file_path,
            "change_type": "added",
        }

    if len(line) < 4:
        return None

    status = line[:2]
    path_part = line[3:].strip()
    old_path = None
    file_path = path_part

    if " -> " in path_part:
        old_path, file_path = path_part.split(" -> ", 1)

    normalized_old_path = _normalize_git_path(old_path or file_path)
    normalized_file_path = _normalize_git_path(file_path)
    status_flags = set(status.replace(" ", ""))

    if "D" in status_flags:
        change_type = "deleted"
    elif "A" in status_flags:
        change_type = "added"
    else:
        change_type = "modified"

    return {
        "file_path": normalized_file_path,
        "old_path": normalized_old_path,
        "change_type": change_type,
    }


def _read_git_revision_text(clone_path: str, git_path: str, file_path: str) -> str:
    result = _run_cmd(clone_path, [git_path, "show", f"HEAD:{_normalize_git_path(file_path)}"])
    return result["stdout"] if result.get("ok") else ""


def _read_working_tree_text(clone_path: str, file_path: str) -> str:
    full_path = os.path.join(clone_path, file_path.replace("/", os.sep))
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return ""

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except Exception:
        return ""


def _should_skip_diff_path(path: str) -> bool:
    normalized = _normalize_git_path(path).lstrip("./")
    if not normalized:
        return True

    lowered = normalized.lower()
    path_segments = [segment for segment in lowered.split("/") if segment]
    ignored_dirs = {
        ".git",
        ".scannerwork",
        ".javaapex-cache",
        "node_modules",
        "target",
        "build",
        "out",
        "dist",
        ".gradle",
        ".idea",
        ".vscode",
    }
    ignored_extensions = (
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".sha1",
        ".md5",
        ".sha256",
        ".sha512",
    )

    if any(segment in ignored_dirs for segment in path_segments):
        return True
    if lowered.endswith(ignored_extensions):
        return True
    return False


def generate_repository_file_diffs(
    clone_path: str,
    max_files: Optional[int] = None,
    max_lines_per_diff: int = 240,
) -> List[FileDiffEntry]:
    import difflib

    git_path = shutil.which("git")
    if not git_path or not clone_path or not os.path.isdir(os.path.join(clone_path, ".git")):
        return []

    status = _run_cmd(
        clone_path,
        [git_path, "status", "--porcelain=v1", "--untracked-files=all"],
    )

    if not status.get("ok") or not status.get("stdout"):
        return []

    diffs: List[FileDiffEntry] = []
    status_lines = status["stdout"].splitlines()
    if max_files is not None:
        status_lines = status_lines[:max_files]

    for raw_line in status_lines:
        change = _parse_git_status_change(raw_line)
        if not change:
            continue

        file_path = change["file_path"]
        old_path = change["old_path"]
        change_type = change["change_type"]
        if _should_skip_diff_path(file_path) or _should_skip_diff_path(old_path):
            continue

        old_text = "" if change_type == "added" else _read_git_revision_text(clone_path, git_path, old_path)
        new_text = "" if change_type == "deleted" else _read_working_tree_text(clone_path, file_path)

        fromfile = "/dev/null" if change_type == "added" else f"a/{old_path}"
        tofile = "/dev/null" if change_type == "deleted" else f"b/{file_path}"
        diff_lines = [f"diff --git a/{old_path} b/{file_path}"]

        if old_path != file_path:
            diff_lines.append(f"rename from {old_path}")
            diff_lines.append(f"rename to {file_path}")

        if change_type == "added":
            diff_lines.append("new file mode 100644")
        elif change_type == "deleted":
            diff_lines.append("deleted file mode 100644")

        diff_lines.extend(
            list(
                difflib.unified_diff(
                    old_text.splitlines(),
                    new_text.splitlines(),
                    fromfile=fromfile,
                    tofile=tofile,
                    lineterm="",
                )
            )
        )

        if max_lines_per_diff and len(diff_lines) > max_lines_per_diff:
            omitted = len(diff_lines) - max_lines_per_diff
            diff_lines = diff_lines[:max_lines_per_diff]
            diff_lines.append(f"... diff truncated ({omitted} additional lines omitted)")

        diff_text = "\n".join(diff_lines).strip()
        if not diff_text:
            continue

        change_count = sum(
            1
            for line in diff_lines
            if (line.startswith("+") and not line.startswith("+++"))
            or (line.startswith("-") and not line.startswith("---"))
        )
        if change_count == 0 and not any(line.startswith(("rename from ", "rename to ")) for line in diff_lines):
            continue
        diffs.append(
            FileDiffEntry(
                file_path=file_path,
                diff=diff_text,
                change_count=change_count,
            )
        )

    return diffs


def generate_testcase_doc_markdown(job: MigrationResult, clone_path: str) -> str:
    """Generate a single Markdown testcase/change report."""

    lines: List[str] = []
    lines.append("# Testcase and Change Report")
    lines.append("")
    lines.append(f"Job ID: `{job.job_id}`")
    lines.append(f"Status: `{job.status}`")
    lines.append(f"Generated At (UTC): `{datetime.now(timezone.utc).isoformat()}`")
    lines.append("")
    lines.append("## Migration Summary")
    lines.append(f"- Source repo: `{job.source_repo}`")
    lines.append(f"- Target repo: `{job.target_repo or ''}`")
    lines.append(f"- Source Java: `{job.source_java_version}`")
    lines.append(f"- Target Java: `{job.target_java_version}`")
    lines.append(f"- Conversion types: `{', '.join(job.conversion_types or [])}`")
    lines.append(f"- Files modified: `{job.files_modified}`")
    lines.append(f"- Issues fixed: `{job.issues_fixed}`")
    lines.append("")

    lines.append("## Test Results")
    test_pipeline = getattr(job, "test_pipeline", None)
    detected_count = getattr(test_pipeline, "existing_tests_detected", 0) if test_pipeline else 0
    generated_count = getattr(test_pipeline, "generated_test_cases", 0) if test_pipeline else 0
    total_count = detected_count + generated_count

    lines.append(
        f"- Total Test Cases (Analysis): `{total_count}` "
        f"(Detected: `{detected_count}`, Generated: `{generated_count}`)"
    )
    lines.append(f"- Tests run (Runtime): `{getattr(job, 'tests_run', 0)}`")
    lines.append(f"- Tests passed: `{getattr(job, 'tests_passed', 0)}`")
    lines.append(f"- Tests failed: `{getattr(job, 'tests_failed', 0)}`")
    if getattr(job, "test_llm_model", None):
        lines.append(f"- LLM model: `{job.test_llm_model}`")
    if getattr(job, "test_summary", None):
        lines.append("")
        lines.append("### LLM Summary")
        lines.append(job.test_summary)
    if getattr(job, "test_insights", None):
        insights = job.test_insights or []
        if insights:
            lines.append("")
            lines.append("### LLM Insights")
            for insight in insights[:50]:
                lines.append(f"- {insight}")
    lines.append("")

    runner = None
    if getattr(job, "test_pipeline", None) and getattr(job.test_pipeline, "runner", None):
        runner = job.test_pipeline.runner
    if isinstance(runner, dict) and runner:
        lines.append("### Test Runner")
        lines.append(f"- Tool: `{runner.get('tool')}`")
        lines.append(f"- Exit code: `{runner.get('exit_code')}`")
        lines.append(f"- Timed out: `{runner.get('timed_out')}`")
        if runner.get("parser"):
            lines.append(f"- Parser: `{runner.get('parser')}`")
        cmd = runner.get("cmd") or []
        if isinstance(cmd, list) and cmd:
            lines.append(f"- Command: `{' '.join(str(x) for x in cmd)}`")

        reports = runner.get("reports") if isinstance(runner.get("reports"), dict) else None
        if reports:
            lines.append(f"- JUnit report files: `{reports.get('report_files_count', 0)}`")
            if reports.get("report_parse_errors"):
                lines.append(f"- JUnit report parse errors: `{len(reports.get('report_parse_errors') or [])}`")

    if getattr(job, "test_pipeline", None):
        test_pipeline = job.test_pipeline
        lines.append("## Generated Test Artifacts")
        lines.append(f"- Provider: `{test_pipeline.provider}`")
        lines.append(f"- Project kind: `{test_pipeline.project_kind}`")
        if getattr(test_pipeline, "test_strategy", None):
            lines.append(f"- Test strategy: `{test_pipeline.test_strategy}`")
        lines.append(f"- Existing test cases detected: `{getattr(test_pipeline, 'existing_tests_detected', 0)}`")
        lines.append(f"- Existing test cases migrated: `{len(getattr(test_pipeline, 'migrated_test_files', []) or [])}`")
        lines.append(f"- Generated tests: `{test_pipeline.generated_tests_relative}`")
        lines.append(f"- Test cases generated: `{len(test_pipeline.generated_test_files or [])}`")
        if test_pipeline.manual_test_plan_path:
            lines.append(f"- Manual test plan: `{test_pipeline.manual_test_plan_path}`")
        if test_pipeline.migration_patch_path:
            lines.append(f"- Migration patch diff: `{test_pipeline.migration_patch_path}`")
        if getattr(test_pipeline, "migrated_test_files", None):
            lines.append("")
            lines.append("### Migrated Existing Test Files")
            for path in (test_pipeline.migrated_test_files or [])[:200]:
                lines.append(f"- `{path}`")
        if test_pipeline.generated_test_files:
            lines.append("")
            lines.append("### Generated Test Files")
            for path in test_pipeline.generated_test_files[:200]:
                lines.append(f"- `{path}`")

        functional = getattr(test_pipeline, "functional_testing", None)
        if isinstance(functional, dict) and functional:
            execution = functional.get("execution") or {}
            lines.append("")
            lines.append("### Functional Testing")
            lines.append(f"- Application type: `{functional.get('application_type', 'unknown')}`")
            lines.append(f"- Selected tools: `{', '.join(functional.get('recommended_tools', []) or []) or 'none'}`")
            lines.append(f"- Runtime port: `{functional.get('allocated_port', '-')}`")
            lines.append(f"- Execution status: `{functional.get('status', execution.get('status', 'unknown'))}`")
            lines.append(f"- Tests run: `{execution.get('tests_run', functional.get('tests_run', 0))}`")
            lines.append(f"- Tests passed: `{execution.get('tests_passed', functional.get('tests_passed', 0))}`")
            lines.append(f"- Tests failed: `{execution.get('tests_failed', functional.get('tests_failed', 0))}`")
            if functional.get("message"):
                lines.append(f"- Message: {functional.get('message')}")
            generated_functional_files = functional.get("generated_files") or []
            if generated_functional_files:
                lines.append("- Generated functional scripts:")
                for path in generated_functional_files[:100]:
                    lines.append(f"  - `{path}`")

            # MAPS-UI-style functional test-case table.
            functional_cases = functional.get("test_cases") or []
            if isinstance(functional_cases, list) and functional_cases:
                def _md_escape(value: Any) -> str:
                    text = str(value if value is not None else "").replace("|", "\\|")
                    return " ".join(text.split())

                lines.append("")
                lines.append("#### Functional Test Cases (MAPS-UI Style)")
                lines.append("")
                lines.append(
                    "| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type | Status |"
                )
                lines.append(
                    "|----|-------|--------------|-------|-----------|-----------------|-----|------|--------|"
                )
                for idx, case in enumerate(functional_cases[:200], start=1):
                    if not isinstance(case, dict):
                        continue
                    target = case.get("path") or case.get("route") or case.get("schema") or ""
                    method = str(case.get("method") or "").strip()
                    test_id = case.get("test_id") or f"TC-{idx:02d}"
                    title = case.get("title") or case.get("name") or "Generated functional test"
                    precondition = case.get("precondition") or "Application deployed and running"
                    steps_val = case.get("steps")
                    if isinstance(steps_val, list) and steps_val:
                        steps = "<br>".join(f"{i}. {_md_escape(s)}" for i, s in enumerate(steps_val[:8], start=1))
                    else:
                        steps = _md_escape(f"{method} {target}".strip() or title)
                    test_data = case.get("test_data") or (f"{method} {target}".strip() or "—")
                    expected_result = case.get("expected_result") or (
                        f"HTTP {case.get('expectedStatus')} response returned"
                        if case.get("expectedStatus") is not None
                        else "Completes successfully"
                    )
                    priority = case.get("priority") or "P2"
                    type_sign = case.get("type_sign") or "+"
                    status = case.get("status") or "generated"
                    lines.append(
                        "| {id} | {title} | {pre} | {steps} | {data} | {exp} | {pri} | {typ} | {status} |".format(
                            id=_md_escape(test_id),
                            title=_md_escape(title),
                            pre=_md_escape(precondition),
                            steps=steps,
                            data=_md_escape(test_data),
                            exp=_md_escape(expected_result),
                            pri=_md_escape(priority),
                            typ=_md_escape(type_sign),
                            status=_md_escape(status),
                        )
                    )
                if len(functional_cases) > 200:
                    lines.append("")
                    lines.append(f"_Showing 200 of {len(functional_cases)} functional test cases._")

        if test_pipeline.manual_test_plan_path and os.path.exists(test_pipeline.manual_test_plan_path):
            try:
                plan_text = Path(test_pipeline.manual_test_plan_path).read_text(encoding="utf-8", errors="ignore")
                if plan_text.strip():
                    lines.append("")
                    lines.append("### Manual And Automation Test Plan (Generated)")
                    lines.append("```markdown")
                    lines.append(plan_text.strip()[:12000])
                    if len(plan_text) > 12000:
                        lines.append("\n...(truncated)...")
                    lines.append("```")
            except Exception:
                pass

        if test_pipeline.generated_test_files:
            lines.append("")
            lines.append("### Generated Tests (Snippets)")
            for path in test_pipeline.generated_test_files[:8]:
                try:
                    if not path or not os.path.exists(path):
                        continue
                    txt = Path(path).read_text(encoding="utf-8", errors="ignore")
                    try:
                        rel = str(Path(path).resolve().relative_to(Path(clone_path).resolve()))
                    except Exception:
                        rel = os.path.basename(path)
                    fence = "java" if path.endswith(".java") else ""
                    lines.append(f"#### `{rel}`")
                    lines.append(f"```{fence}".rstrip())
                    lines.append(txt.strip()[:8000])
                    if len(txt) > 8000:
                        lines.append("\n...(truncated)...")
                    lines.append("```")
                except Exception:
                    continue
    lines.append("")

    lines.append("## What Changed (Before vs After)")
    stored_file_diffs = getattr(job, "file_diffs", None) or []
    git_path = shutil.which("git")
    if stored_file_diffs:
        total_additions = 0
        total_deletions = 0
        for file_diff in stored_file_diffs:
            diff_text = getattr(file_diff, "diff", "") or ""
            total_additions += sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
            total_deletions += sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))

        lines.append("### Captured Diff Summary")
        lines.append(f"- Files changed: `{len(stored_file_diffs)}`")
        lines.append(f"- Additions: `{total_additions}`")
        lines.append(f"- Deletions: `{total_deletions}`")
        lines.append("")
        lines.append("### Git Diff (Unified)")
        lines.append("```diff")
        for file_diff in stored_file_diffs:
            diff_text = getattr(file_diff, "diff", "") or ""
            if diff_text:
                lines.append(diff_text)
        lines.append("```")
        lines.append("")
    elif not git_path or not (clone_path and os.path.isdir(os.path.join(clone_path, ".git"))):
        lines.append("Git diff is unavailable for this run (missing git or .git directory).")
        lines.append("You can still download the migrated project ZIP to review changes.")
        lines.append("")
    else:
        status = _run_cmd(clone_path, [git_path, "status", "--porcelain=v1"])
        diff_stat = _run_cmd(clone_path, [git_path, "diff", "--stat"])
        diff = _run_cmd(clone_path, [git_path, "diff"])

        lines.append("### Git Status")
        lines.append("```")
        lines.append(status["stdout"] or "(clean)")
        lines.append("```")
        lines.append("")
        lines.append("### Git Diff Stat")
        lines.append("```")
        lines.append(diff_stat["stdout"] or "(no changes)")
        lines.append("```")
        lines.append("")
        lines.append("### Git Diff (Unified)")
        lines.append("```diff")
        lines.append(diff["stdout"] or "")
        lines.append("```")
        lines.append("")

    if getattr(job, "migration_log", None):
        logs = job.migration_log or []
        lines.append("## Migration Log")
        lines.append("```")
        lines.extend(logs[-500:])
        lines.append("```")
        lines.append("")

    if getattr(job, "issues", None):
        issues = job.issues or []
        if issues:
            lines.append("## Known Issues")
            for issue in issues[:200]:
                where = f"{issue.file_path}:{issue.line_number or ''}".rstrip(":")
                lines.append(f"- [{issue.severity}] {issue.message} (`{where}`)")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def generate_migration_issues(
    project_path: str,
    conversion_types: List[str],
    source_version: str,
    target_version: str,
) -> List[MigrationIssue]:
    """Scan project and generate migration issues based on code analysis."""

    issues: List[MigrationIssue] = []
    issue_id = 0

    java_dirs = []
    src_main = os.path.join(project_path, "src", "main", "java")
    src_test = os.path.join(project_path, "src", "test", "java")
    if os.path.exists(src_main):
        java_dirs.append(src_main)
    if os.path.exists(src_test):
        java_dirs.append(src_test)

    src_root = os.path.join(project_path, "src")
    if os.path.exists(src_root) and src_root not in java_dirs:
        java_dirs.append(src_root)

    java_dirs.append(project_path)
    target = int(target_version)

    patterns: Dict[str, List[tuple[str, str, str, str]]] = {}

    if "java_version" in conversion_types:
        patterns["java_version"] = [
            (r"new Integer\s*\(", "error", "Deprecated Method", "new Integer() is deprecated - use Integer.valueOf()"),
            (r"new Long\s*\(", "error", "Deprecated Method", "new Long() is deprecated - use Long.valueOf()"),
            (r"new Double\s*\(", "error", "Deprecated Method", "new Double() is deprecated - use Double.valueOf()"),
            (r"new Boolean\s*\(", "error", "Deprecated Method", "new Boolean() is deprecated - use Boolean.valueOf()"),
            (r"new Float\s*\(", "error", "Deprecated Method", "new Float() is deprecated - use Float.valueOf()"),
            (r"new Character\s*\(", "error", "Deprecated Method", "new Character() is deprecated - use Character.valueOf()"),
            (r"new Byte\s*\(", "error", "Deprecated Method", "new Byte() is deprecated - use Byte.valueOf()"),
            (r"new Short\s*\(", "error", "Deprecated Method", "new Short() is deprecated - use Short.valueOf()"),
            (r"\.newInstance\s*\(\s*\)", "error", "Deprecated Method", "Class.newInstance() is deprecated - use getDeclaredConstructor().newInstance()"),
            (r"new Date\s*\(\s*\)", "warning", "Deprecated API", "Consider using java.time.LocalDateTime instead of java.util.Date"),
            (r"SimpleDateFormat", "warning", "Thread Safety", "SimpleDateFormat is not thread-safe - consider DateTimeFormatter"),
            (r"java\.util\.Date", "warning", "Deprecated API", "Consider migrating to java.time API (LocalDate, LocalDateTime)"),
            (r"java\.util\.Calendar", "warning", "Deprecated API", "Consider migrating to java.time API"),
            (r"(?<![<\w])List\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use generics List<T>"),
            (r"(?<![<\w])Map\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use generics Map<K,V>"),
            (r"(?<![<\w])Set\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use generics Set<T>"),
            (r"(?<![<\w])ArrayList\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use ArrayList<T>"),
            (r"(?<![<\w])HashMap\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use HashMap<K,V>"),
            (r"(?<![<\w])HashSet\s+\w+\s*=", "warning", "Type Safety", "Raw type usage detected - use HashSet<T>"),
            (r"(?<![<\w])Vector\s+\w+\s*=", "warning", "Type Safety", "Vector is legacy - use ArrayList<T> instead"),
            (r"(?<![<\w])Hashtable\s+\w+\s*=", "warning", "Type Safety", "Hashtable is legacy - use HashMap<K,V> instead"),
            (r"new Scanner\s*\([^)]*\)\s*;", "warning", "Resource Management", "Scanner should be in try-with-resources for automatic closing"),
            (r"FileInputStream|FileOutputStream|FileReader|FileWriter", "warning", "Resource Management", "Consider using try-with-resources and Files.* methods"),
            (r'\+\s*"\s*"|"\s*"\s*\+', "info", "Performance", "Empty string concatenation detected - can be simplified"),
            (r"catch\s*\(\s*Exception\s+\w+\s*\)", "warning", "Code Quality", "Catching generic Exception - consider specific exception types"),
            (r"catch\s*\(\s*Throwable\s+\w+\s*\)", "warning", "Code Quality", "Catching Throwable includes Errors - use Exception instead"),
            (r"e\.printStackTrace\s*\(\s*\)", "warning", "Code Quality", "printStackTrace() - consider proper logging instead"),
            (r"\.equals\s*\(\s*null\s*\)", "error", "Null Safety", ".equals(null) always false - use == null check"),
            (r"extends\s+JFrame|extends\s+JPanel", "info", "Thread Safety", "Swing component - ensure EDT usage for thread safety"),
        ]

        if target >= 9:
            patterns["java_version"].extend(
                [
                    (r"sun\.misc\.", "error", "Removed Class", "sun.misc.* classes removed in Java 9+ - use standard alternatives"),
                    (r"sun\.reflect\.", "error", "Removed Class", "sun.reflect.* classes removed - use java.lang.reflect"),
                ]
            )
        if target >= 11:
            patterns["java_version"].extend(
                [
                    (r"\.trim\(\)\.isEmpty\(\)", "info", "Modern API", "Can use String.isBlank() (Java 11+) for whitespace check"),
                    (r"\.trim\(\)\.length\(\)\s*==\s*0", "info", "Modern API", "Can use String.isBlank() (Java 11+)"),
                ]
            )
        if target >= 17:
            patterns["java_version"].append(
                (r"import\s+javax\.swing\.", "info", "Modern API", "Swing still works in Java 17, but consider JavaFX for new UIs")
            )

    if "javax_to_jakarta" in conversion_types or (target >= 17 and "java_version" in conversion_types):
        patterns["javax_to_jakarta"] = [
            (r"import javax\.servlet\.", "error", "Package Migration", "javax.servlet.* -> jakarta.servlet.* (required for Java 17+/Spring Boot 3)"),
            (r"import javax\.persistence\.", "error", "Package Migration", "javax.persistence.* -> jakarta.persistence.* (required for Java 17+)"),
            (r"import javax\.validation\.", "error", "Package Migration", "javax.validation.* -> jakarta.validation.* (required for Java 17+)"),
            (r"import javax\.annotation\.", "warning", "Package Migration", "javax.annotation.* -> jakarta.annotation.* (recommended for Java 17+)"),
            (r"import javax\.inject\.", "error", "Package Migration", "javax.inject.* -> jakarta.inject.* (required for Jakarta EE)"),
            (r"import javax\.ws\.rs\.", "error", "Package Migration", "javax.ws.rs.* -> jakarta.ws.rs.* (required for JAX-RS 3.x)"),
        ]

    if "spring_boot_2_to_3" in conversion_types:
        patterns["spring_boot_2_to_3"] = [
            (r"WebSecurityConfigurerAdapter", "error", "Security Config", "WebSecurityConfigurerAdapter removed in Spring Security 6 - use SecurityFilterChain"),
            (r"@EnableGlobalMethodSecurity", "warning", "Security Config", "@EnableGlobalMethodSecurity deprecated - use @EnableMethodSecurity"),
            (r"antMatchers", "error", "Security Config", "antMatchers() removed - use requestMatchers()"),
            (r"mvcMatchers", "error", "Security Config", "mvcMatchers() removed - use requestMatchers()"),
        ]

    if "junit_4_to_5" in conversion_types:
        patterns["junit_4_to_5"] = [
            (r"import org\.junit\.Test;", "error", "Import Change", "org.junit.Test -> org.junit.jupiter.api.Test"),
            (r"import org\.junit\.Before;", "warning", "Import Change", "@Before -> @BeforeEach (JUnit 5)"),
            (r"import org\.junit\.After;", "warning", "Import Change", "@After -> @AfterEach (JUnit 5)"),
            (r"import org\.junit\.BeforeClass;", "warning", "Import Change", "@BeforeClass -> @BeforeAll (JUnit 5)"),
            (r"import org\.junit\.Ignore;", "warning", "Import Change", "@Ignore -> @Disabled (JUnit 5)"),
            (r"@RunWith", "warning", "Annotation Change", "@RunWith -> @ExtendWith (JUnit 5)"),
        ]

    if "log4j_to_slf4j" in conversion_types:
        patterns["log4j_to_slf4j"] = [
            (r"import org\.apache\.log4j\.", "error", "Import Change", "org.apache.log4j.* -> org.slf4j.* (SLF4J facade)"),
            (r"Logger\.getLogger\s*\(", "error", "Logger Factory", "Logger.getLogger() -> LoggerFactory.getLogger()"),
        ]

    scanned_files = set()
    for src_dir in java_dirs:
        if not os.path.exists(src_dir):
            continue

        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["target", "build", "out", "node_modules"]]
            for file_name in files:
                if not file_name.endswith(".java"):
                    continue

                file_path = os.path.join(root, file_name)
                if file_path in scanned_files:
                    continue
                scanned_files.add(file_path)
                relative_path = os.path.relpath(file_path, project_path)

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                        file_lines = handle.readlines()
                except Exception:
                    continue

                for conversion_type, pattern_list in patterns.items():
                    for pattern, severity, category, message in pattern_list:
                        for line_num, line in enumerate(file_lines, 1):
                            if re.search(pattern, line):
                                issue_id += 1
                                issues.append(
                                    MigrationIssue(
                                        id=f"ISS-{issue_id:04d}",
                                        severity=IssueSeverity(severity),
                                        status=IssueStatus.DETECTED,
                                        category=category,
                                        message=message,
                                        file_path=relative_path,
                                        line_number=line_num,
                                        code_snippet=line.strip()[:100],
                                        conversion_type=conversion_type if conversion_type in conversion_types else "java_version",
                                    )
                                )
                                break

    pom_path = os.path.join(project_path, "pom.xml")
    if os.path.exists(pom_path):
        try:
            with open(pom_path, "r", encoding="utf-8") as handle:
                pom_lines = handle.readlines()
            for line_num, line in enumerate(pom_lines, 1):
                if "spring-boot" in line.lower() and re.search(r"<version>2\.[0-9]", line):
                    issue_id += 1
                    issues.append(
                        MigrationIssue(
                            id=f"ISS-{issue_id:04d}",
                            severity=IssueSeverity.WARNING,
                            status=IssueStatus.DETECTED,
                            category="Dependency Update",
                            message="Spring Boot 2.x should be upgraded to 3.x for Java 17+",
                            file_path="pom.xml",
                            line_number=line_num,
                            conversion_type="java_version",
                        )
                    )
        except Exception:
            pass

    return issues

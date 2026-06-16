"""
Router for pre/post migration functional test validation.

Endpoints:
  POST /api/migration-validation/pre   — Run pre-migration compile + test check
  POST /api/migration-validation/post  — Run post-migration compile + test check
  POST /api/migration-validation/compare — Compare pre vs post snapshots
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/migration-validation", tags=["Migration Validation"])


class PreMigrationRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the original Java project")
    backup_path: Optional[str] = Field(None, description="Path to create a backup before migration")


class PostMigrationRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the migrated Java project")
    inject_functional_tests: bool = Field(True, description="Inject generated functional tests")
    pre_snapshot: Optional[Dict[str, Any]] = Field(None, description="Pre-migration snapshot for comparison")


class CompareRequest(BaseModel):
    pre_snapshot: Dict[str, Any] = Field(..., description="Pre-migration snapshot")
    post_snapshot: Dict[str, Any] = Field(..., description="Post-migration snapshot")


@router.post("/pre")
async def run_pre_migration_validation(req: PreMigrationRequest):
    """Run compile check and existing tests on the ORIGINAL (pre-migration) source."""
    from services.pre_post_migration_validator import PrePostMigrationValidator, MigrationSnapshot
    from dataclasses import asdict

    try:
        validator = PrePostMigrationValidator()
        snapshot = await validator.run_pre_migration(
            req.project_path,
            backup_path=req.backup_path,
        )
        return {
            "status": "success",
            "snapshot": asdict(snapshot),
            "compile_success": snapshot.compile.success,
            "tests_run": snapshot.tests.tests_run,
            "tests_passed": snapshot.tests.tests_passed,
            "tests_failed": snapshot.tests.tests_failed,
        }
    except Exception as e:
        logger.exception("Pre-migration validation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/post")
async def run_post_migration_validation(req: PostMigrationRequest):
    """Run compile check and tests on the MIGRATED source, optionally injecting functional tests."""
    from services.pre_post_migration_validator import (
        PrePostMigrationValidator,
        MigrationSnapshot,
        CompileResult,
        TestResult,
    )
    from dataclasses import asdict

    try:
        validator = PrePostMigrationValidator()

        # Reconstruct pre_snapshot if provided
        pre = None
        if req.pre_snapshot:
            pre = MigrationSnapshot(**{
                k: v for k, v in req.pre_snapshot.items()
                if k in MigrationSnapshot.__dataclass_fields__
            })

        post = await validator.run_post_migration(
            req.project_path,
            pre_snapshot=pre,
            inject_functional_tests=req.inject_functional_tests,
        )

        result = {
            "status": "success",
            "snapshot": asdict(post),
            "compile_success": post.compile.success,
            "tests_run": post.tests.tests_run,
            "tests_passed": post.tests.tests_passed,
            "tests_failed": post.tests.tests_failed,
            "functional_tests_injected": post.functional_tests_injected,
            "compile_errors": post.errors_detail[:20],
        }

        # Include comparison if pre_snapshot was provided
        if pre:
            comparison = validator.compare(pre, post)
            result["comparison"] = comparison
            result["migration_health_score"] = comparison["migration_health_score"]

        return result
    except Exception as e:
        logger.exception("Post-migration validation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare")
async def compare_snapshots(req: CompareRequest):
    """Compare pre and post migration snapshots."""
    from services.pre_post_migration_validator import PrePostMigrationValidator, MigrationSnapshot

    try:
        validator = PrePostMigrationValidator()
        pre = MigrationSnapshot(**{
            k: v for k, v in req.pre_snapshot.items()
            if k in MigrationSnapshot.__dataclass_fields__
        })
        post = MigrationSnapshot(**{
            k: v for k, v in req.post_snapshot.items()
            if k in MigrationSnapshot.__dataclass_fields__
        })
        comparison = validator.compare(pre, post)
        return {
            "status": "success",
            **comparison,
        }
    except Exception as e:
        logger.exception("Snapshot comparison failed")
        raise HTTPException(status_code=500, detail=str(e))

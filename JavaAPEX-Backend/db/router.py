"""REST API router exposing CRUD endpoints for all apex database tables."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from db.service import (
    create_org, get_org, list_orgs, update_org, delete_org,
    create_user, get_user, list_users, update_user, delete_user,
    create_llm_master, get_llm_master, list_llm_masters, update_llm_master, delete_llm_master,
    create_migration, get_migration, list_migrations, update_migration, delete_migration,
    create_repo_mig_opt, get_repo_mig_opt, get_repo_mig_opt_by_migration, update_repo_mig_opt,
    create_unittest_report, get_unittest_report, get_unittest_report_by_migration, update_unittest_report,
    create_dependency, get_dependency, get_dependency_by_migration, update_dependency,
    create_perf_test, get_perf_test, get_perf_test_by_migration, update_perf_test,
    create_error, get_error, list_errors_by_migration, list_errors_by_type, delete_error,
    create_llm_details, get_llm_details, list_llm_details_by_migration, get_llm_consumption_summary, delete_llm_details,
)
from db.connection import is_database_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db", tags=["database"])


# ---------------------------------------------------------------------------
# Health & utility
# ---------------------------------------------------------------------------

@router.get("/health")
async def db_health():
    """Check database connectivity."""
    available = is_database_available()
    return {"database": "available" if available else "unavailable"}


# ===========================================================================
# apex_m01_org
# ===========================================================================

@router.post("/orgs", status_code=201)
async def api_create_org(data: Dict[str, Any]):
    try:
        return create_org(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orgs")
async def api_list_orgs(active_only: bool = Query(False)):
    return list_orgs(active_only=active_only)


@router.get("/orgs/{org_id}")
async def api_get_org(org_id: int):
    row = get_org(org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


@router.put("/orgs/{org_id}")
async def api_update_org(org_id: int, data: Dict[str, Any]):
    row = update_org(org_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


@router.delete("/orgs/{org_id}")
async def api_delete_org(org_id: int):
    if not delete_org(org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"detail": "Organization deleted"}


# ===========================================================================
# apex_m02_user
# ===========================================================================

@router.post("/users", status_code=201)
async def api_create_user(data: Dict[str, Any]):
    try:
        return create_user(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users")
async def api_list_users(org_id: Optional[int] = Query(None), active_only: bool = Query(False)):
    return list_users(org_id=org_id, active_only=active_only)


@router.get("/users/{user_id}")
async def api_get_user(user_id: str):
    row = get_user(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.put("/users/{user_id}")
async def api_update_user(user_id: str, data: Dict[str, Any]):
    row = update_user(user_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.delete("/users/{user_id}")
async def api_delete_user(user_id: str):
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"detail": "User deleted"}


# ===========================================================================
# apex_m03_llm_master
# ===========================================================================

@router.post("/llm-masters", status_code=201)
async def api_create_llm_master(data: Dict[str, Any]):
    try:
        return create_llm_master(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/llm-masters")
async def api_list_llm_masters(user_id: Optional[str] = Query(None), active_only: bool = Query(False)):
    return list_llm_masters(user_id=user_id, active_only=active_only)


@router.get("/llm-masters/{lm_id}")
async def api_get_llm_master(lm_id: int):
    row = get_llm_master(lm_id)
    if not row:
        raise HTTPException(status_code=404, detail="LLM master record not found")
    return row


@router.put("/llm-masters/{lm_id}")
async def api_update_llm_master(lm_id: int, data: Dict[str, Any]):
    row = update_llm_master(lm_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="LLM master record not found")
    return row


@router.delete("/llm-masters/{lm_id}")
async def api_delete_llm_master(lm_id: int):
    if not delete_llm_master(lm_id):
        raise HTTPException(status_code=404, detail="LLM master record not found")
    return {"detail": "LLM master record deleted"}


# ===========================================================================
# apex_t01_migration_dtls
# ===========================================================================

@router.post("/migrations", status_code=201)
async def api_create_migration(data: Dict[str, Any]):
    try:
        return create_migration(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/migrations")
async def api_list_migrations(
    user_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return list_migrations(user_id=user_id, limit=limit, offset=offset)


@router.get("/migrations/{migration_id}")
async def api_get_migration(migration_id: int):
    row = get_migration(migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")
    return row


@router.put("/migrations/{migration_id}")
async def api_update_migration(migration_id: int, data: Dict[str, Any]):
    row = update_migration(migration_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")
    return row


@router.delete("/migrations/{migration_id}")
async def api_delete_migration(migration_id: int):
    if not delete_migration(migration_id):
        raise HTTPException(status_code=404, detail="Migration not found")
    return {"detail": "Migration deleted"}


# ===========================================================================
# apex_t02_repo_mig_opt
# ===========================================================================

@router.post("/repo-mig-opts", status_code=201)
async def api_create_repo_mig_opt(data: Dict[str, Any]):
    try:
        return create_repo_mig_opt(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/repo-mig-opts/by-migration/{migration_id}")
async def api_get_repo_mig_opt_by_migration(migration_id: int):
    row = get_repo_mig_opt_by_migration(migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration options not found")
    return row


@router.get("/repo-mig-opts/{opt_id}")
async def api_get_repo_mig_opt(opt_id: int):
    row = get_repo_mig_opt(opt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration options not found")
    return row


@router.put("/repo-mig-opts/{opt_id}")
async def api_update_repo_mig_opt(opt_id: int, data: Dict[str, Any]):
    row = update_repo_mig_opt(opt_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Migration options not found")
    return row


# ===========================================================================
# apex_t03_unittestreport
# ===========================================================================

@router.post("/unittest-reports", status_code=201)
async def api_create_unittest_report(data: Dict[str, Any]):
    try:
        return create_unittest_report(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/unittest-reports/by-migration/{migration_id}")
async def api_get_unittest_report_by_migration(migration_id: int):
    row = get_unittest_report_by_migration(migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unit test report not found")
    return row


@router.get("/unittest-reports/{utr_id}")
async def api_get_unittest_report(utr_id: int):
    row = get_unittest_report(utr_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unit test report not found")
    return row


@router.put("/unittest-reports/{utr_id}")
async def api_update_unittest_report(utr_id: int, data: Dict[str, Any]):
    row = update_unittest_report(utr_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Unit test report not found")
    return row


# ===========================================================================
# apex_t04_dependency
# ===========================================================================

@router.post("/dependencies", status_code=201)
async def api_create_dependency(data: Dict[str, Any]):
    try:
        return create_dependency(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dependencies/by-migration/{migration_id}")
async def api_get_dependency_by_migration(migration_id: int):
    row = get_dependency_by_migration(migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dependency record not found")
    return row


@router.get("/dependencies/{dep_id}")
async def api_get_dependency(dep_id: int):
    row = get_dependency(dep_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dependency record not found")
    return row


@router.put("/dependencies/{dep_id}")
async def api_update_dependency(dep_id: int, data: Dict[str, Any]):
    row = update_dependency(dep_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Dependency record not found")
    return row


# ===========================================================================
# apex_t05_perfTestRep
# ===========================================================================

@router.post("/perf-tests", status_code=201)
async def api_create_perf_test(data: Dict[str, Any]):
    try:
        return create_perf_test(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/perf-tests/by-migration/{migration_id}")
async def api_get_perf_test_by_migration(migration_id: int):
    row = get_perf_test_by_migration(migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Performance test report not found")
    return row


@router.get("/perf-tests/{ptr_id}")
async def api_get_perf_test(ptr_id: int):
    row = get_perf_test(ptr_id)
    if not row:
        raise HTTPException(status_code=404, detail="Performance test report not found")
    return row


@router.put("/perf-tests/{ptr_id}")
async def api_update_perf_test(ptr_id: int, data: Dict[str, Any]):
    row = update_perf_test(ptr_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Performance test report not found")
    return row


# ===========================================================================
# apex_t06_error_dtls
# ===========================================================================

@router.post("/errors", status_code=201)
async def api_create_error(data: Dict[str, Any]):
    try:
        return create_error(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/errors/by-migration/{migration_id}")
async def api_list_errors_by_migration(migration_id: int):
    return list_errors_by_migration(migration_id)


@router.get("/errors/by-type/{err_type}")
async def api_list_errors_by_type(err_type: str):
    return list_errors_by_type(err_type)


@router.get("/errors/{err_id}")
async def api_get_error(err_id: int):
    row = get_error(err_id)
    if not row:
        raise HTTPException(status_code=404, detail="Error record not found")
    return row


@router.delete("/errors/{err_id}")
async def api_delete_error(err_id: int):
    if not delete_error(err_id):
        raise HTTPException(status_code=404, detail="Error record not found")
    return {"detail": "Error record deleted"}


# ===========================================================================
# apex_t07_llm_dtls
# ===========================================================================

@router.post("/llm-details", status_code=201)
async def api_create_llm_details(data: Dict[str, Any]):
    try:
        return create_llm_details(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/llm-details/by-migration/{migration_id}")
async def api_list_llm_details_by_migration(migration_id: int):
    return list_llm_details_by_migration(migration_id)


@router.get("/llm-details/summary/{migration_id}")
async def api_get_llm_consumption_summary(migration_id: int):
    return get_llm_consumption_summary(migration_id)


@router.get("/llm-details/{ld_id}")
async def api_get_llm_details(ld_id: int):
    row = get_llm_details(ld_id)
    if not row:
        raise HTTPException(status_code=404, detail="LLM details record not found")
    return row


@router.delete("/llm-details/{ld_id}")
async def api_delete_llm_details(ld_id: int):
    if not delete_llm_details(ld_id):
        raise HTTPException(status_code=404, detail="LLM details record not found")
    return {"detail": "LLM details record deleted"}
"""CRUD service layer for all apex database tables."""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any, Dict, List, Optional

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, (date, time)):
            result[key] = value.isoformat()
    return result


def _rows_to_list(rows: Any) -> List[Dict[str, Any]]:
    return [_row_to_dict(r) for r in (rows or [])]


# ===========================================================================
# apex_m01_org
# ===========================================================================

def create_org(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_m01_org (
                apex_m01_org_name, apex_m01_org_domain_name,
                apex_m01_source_local_f, apex_m01_destination_local_f,
                apex_m01_brd_f, apex_m01_destination_new_repo_f,
                apex_m01_active_f, apex_m01_subscribed_plan, apex_m01_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_m01_org_name"], data.get("apex_m01_org_domain_name"),
             data.get("apex_m01_source_local_f", "N"), data.get("apex_m01_destination_local_f", "N"),
             data.get("apex_m01_brd_f", "N"), data.get("apex_m01_destination_new_repo_f", "N"),
             data.get("apex_m01_active_f", "Y"), data.get("apex_m01_subscribed_plan"),
             data["apex_m01_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_org(org_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_m01_org WHERE apex_m01_org_id = %s", (org_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_orgs(active_only: bool = False) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        q = "SELECT * FROM apex_m01_org"
        if active_only:
            q += " WHERE apex_m01_active_f = 'Y'"
        q += " ORDER BY apex_m01_org_id"
        cur.execute(q)
        return _rows_to_list(cur.fetchall())


def update_org(org_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets = []
    vals = []
    for fld in ["apex_m01_org_name", "apex_m01_org_domain_name",
                 "apex_m01_source_local_f", "apex_m01_destination_local_f",
                 "apex_m01_brd_f", "apex_m01_destination_new_repo_f",
                 "apex_m01_active_f", "apex_m01_subscribed_plan"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_org(org_id)
    vals.append(org_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_m01_org SET {', '.join(sets)} WHERE apex_m01_org_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


def delete_org(org_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_m01_org WHERE apex_m01_org_id = %s", (org_id,))
        return cur.rowcount > 0


# ===========================================================================
# apex_m02_user
# ===========================================================================

def create_user(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_m02_user (apex_m02_user_id, apex_m02_password, apex_m02_org_id,
               apex_m02_user_email_id, apex_m02_active_f, apex_m02_created_by)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_m02_user_id"], data["apex_m02_password"], data["apex_m02_org_id"],
             data["apex_m02_user_email_id"], data.get("apex_m02_active_f", "Y"),
             data["apex_m02_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_m02_user WHERE apex_m02_user_id = %s", (user_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_users(org_id: Optional[int] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        q = "SELECT * FROM apex_m02_user WHERE 1=1"
        params = []
        if org_id is not None:
            q += " AND apex_m02_org_id = %s"
            params.append(org_id)
        if active_only:
            q += " AND apex_m02_active_f = 'Y'"
        q += " ORDER BY apex_m02_user_id"
        cur.execute(q, params)
        return _rows_to_list(cur.fetchall())


def update_user(user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_m02_password", "apex_m02_org_id", "apex_m02_user_email_id", "apex_m02_active_f"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_user(user_id)
    vals.append(user_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_m02_user SET {', '.join(sets)} WHERE apex_m02_user_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


def delete_user(user_id: str) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_m02_user WHERE apex_m02_user_id = %s", (user_id,))
        return cur.rowcount > 0


# ===========================================================================
# apex_m03_llm_master
# ===========================================================================

def create_llm_master(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_m03_llm_master (apex_m02_user_id, apex_m03_eligible_model_name,
               apex_m03_active_f, apex_m03_created_by) VALUES (%s,%s,%s,%s) RETURNING *""",
            (data["apex_m02_user_id"], data["apex_m03_eligible_model_name"],
             data.get("apex_m03_active_f", "Y"), data["apex_m03_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_llm_master(lm_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_m03_llm_master WHERE apex_m03_lm_id = %s", (lm_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_llm_masters(user_id: Optional[str] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        q = "SELECT * FROM apex_m03_llm_master WHERE 1=1"
        params = []
        if user_id:
            q += " AND apex_m02_user_id = %s"
            params.append(user_id)
        if active_only:
            q += " AND apex_m03_active_f = 'Y'"
        q += " ORDER BY apex_m03_lm_id"
        cur.execute(q, params)
        return _rows_to_list(cur.fetchall())


def update_llm_master(lm_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_m02_user_id", "apex_m03_eligible_model_name", "apex_m03_active_f"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_llm_master(lm_id)
    vals.append(lm_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_m03_llm_master SET {', '.join(sets)} WHERE apex_m03_lm_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


def delete_llm_master(lm_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_m03_llm_master WHERE apex_m03_lm_id = %s", (lm_id,))
        return cur.rowcount > 0


# ===========================================================================
# apex_t01_migration_dtls
# ===========================================================================

def create_migration(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t01_migration_dtls (
                apex_t01_user_id, apex_t01_source_repo_url, apex_t01_destination_repo_url,
                apex_t01_conversion_type, apex_t01_detected_java_ver, apex_t01_migrating_java_ver,
                apex_t01_destination_repo_type, apex_t01_migrating_total_time, apex_t01_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_user_id"], data["apex_t01_source_repo_url"],
             data.get("apex_t01_destination_repo_url"), data.get("apex_t01_conversion_type"),
             data.get("apex_t01_detected_java_ver"), data.get("apex_t01_migrating_java_ver"),
             data.get("apex_t01_destination_repo_type"), data.get("apex_t01_migrating_total_time"),
             data["apex_t01_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_migration(migration_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t01_migration_dtls WHERE apex_t01_migration_id = %s", (migration_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_migrations(user_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        q = "SELECT * FROM apex_t01_migration_dtls WHERE 1=1"
        params = []
        if user_id:
            q += " AND apex_t01_user_id = %s"
            params.append(user_id)
        q += " ORDER BY apex_t01_created_dt DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        cur.execute(q, params)
        return _rows_to_list(cur.fetchall())


def update_migration(migration_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_t01_source_repo_url", "apex_t01_destination_repo_url",
                 "apex_t01_conversion_type", "apex_t01_detected_java_ver",
                 "apex_t01_migrating_java_ver", "apex_t01_destination_repo_type",
                 "apex_t01_migrating_total_time"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_migration(migration_id)
    vals.append(migration_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_t01_migration_dtls SET {', '.join(sets)} WHERE apex_t01_migration_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


def delete_migration(migration_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_t01_migration_dtls WHERE apex_t01_migration_id = %s", (migration_id,))
        return cur.rowcount > 0


# ===========================================================================
# apex_t02_repo_mig_opt
# ===========================================================================

def create_repo_mig_opt(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t02_repo_mig_opt (
                apex_t01_migration_id, apex_t02_mo_run_test_suite_f, apex_t02_mo_staticcode_chk_f,
                apex_t02_mo_dependency_chk_f, apex_t02_mo_business_logic_chk_f, apex_t02_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_migration_id"], data.get("apex_t02_mo_run_test_suite_f", "N"),
             data.get("apex_t02_mo_staticcode_chk_f", "N"), data.get("apex_t02_mo_dependency_chk_f", "N"),
             data.get("apex_t02_mo_business_logic_chk_f", "N"), data["apex_t02_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_repo_mig_opt(opt_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t02_repo_mig_opt WHERE apex_t02_mo_opt_id = %s", (opt_id,))
        return _row_to_dict(cur.fetchone()) or None


def get_repo_mig_opt_by_migration(migration_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t02_repo_mig_opt WHERE apex_t01_migration_id = %s", (migration_id,))
        return _row_to_dict(cur.fetchone()) or None


def update_repo_mig_opt(opt_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_t02_mo_run_test_suite_f", "apex_t02_mo_staticcode_chk_f",
                 "apex_t02_mo_dependency_chk_f", "apex_t02_mo_business_logic_chk_f"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_repo_mig_opt(opt_id)
    vals.append(opt_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_t02_repo_mig_opt SET {', '.join(sets)} WHERE apex_t02_mo_opt_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


# ===========================================================================
# apex_t03_unittestreport
# ===========================================================================

def create_unittest_report(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t03_unittestreport (
                apex_t01_migration_id, apex_t03_utr_test_count, apex_t03_utr_test_passed,
                apex_t03_utr_test_failed, apex_t03_utr_test_generated,
                apex_t03_utr_testcase_file, apex_t03_utr_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_migration_id"], data.get("apex_t03_utr_test_count", 0),
             data.get("apex_t03_utr_test_passed", 0), data.get("apex_t03_utr_test_failed", 0),
             data.get("apex_t03_utr_test_generated", 0), data.get("apex_t03_utr_testcase_file"),
             data["apex_t03_utr_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_unittest_report(utr_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t03_unittestreport WHERE apex_t03_utr_id = %s", (utr_id,))
        return _row_to_dict(cur.fetchone()) or None


def get_unittest_report_by_migration(migration_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t03_unittestreport WHERE apex_t01_migration_id = %s", (migration_id,))
        return _row_to_dict(cur.fetchone()) or None


def update_unittest_report(utr_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_t03_utr_test_count", "apex_t03_utr_test_passed",
                 "apex_t03_utr_test_failed", "apex_t03_utr_test_generated", "apex_t03_utr_testcase_file"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_unittest_report(utr_id)
    vals.append(utr_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_t03_unittestreport SET {', '.join(sets)} WHERE apex_t03_utr_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


# ===========================================================================
# apex_t04_dependency
# ===========================================================================

def create_dependency(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t04_dependency (
                apex_t01_migration_id, apex_t04_dep_total_dep, apex_t04_dep_license_issues_cnt,
                apex_t04_dep_vulnerabilities_cnt, apex_t04_dep_outdated_pack_cnt, apex_t04_dep_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_migration_id"], data.get("apex_t04_dep_total_dep", 0),
             data.get("apex_t04_dep_license_issues_cnt", 0), data.get("apex_t04_dep_vulnerabilities_cnt", 0),
             data.get("apex_t04_dep_outdated_pack_cnt", 0), data["apex_t04_dep_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_dependency(dep_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t04_dependency WHERE apex_t04_dep_id = %s", (dep_id,))
        return _row_to_dict(cur.fetchone()) or None


def get_dependency_by_migration(migration_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t04_dependency WHERE apex_t01_migration_id = %s", (migration_id,))
        return _row_to_dict(cur.fetchone()) or None


def update_dependency(dep_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_t04_dep_total_dep", "apex_t04_dep_license_issues_cnt",
                 "apex_t04_dep_vulnerabilities_cnt", "apex_t04_dep_outdated_pack_cnt"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_dependency(dep_id)
    vals.append(dep_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_t04_dependency SET {', '.join(sets)} WHERE apex_t04_dep_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


# ===========================================================================
# apex_t05_perfTestRep
# ===========================================================================

def create_perf_test(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t05_perfTestRep (
                apex_t01_migration_id, apex_t05_ptr_api_tested, apex_t05_ptr_working_endpoints,
                apex_t05_ptr_average_resp_time, apex_t05_ptr_throughput, apex_t05_ptr_created_by
            ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_migration_id"], data.get("apex_t05_ptr_api_tested", 0),
             data.get("apex_t05_ptr_working_endpoints", 0), data.get("apex_t05_ptr_average_resp_time", 0),
             data.get("apex_t05_ptr_throughput", 0), data["apex_t05_ptr_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_perf_test(ptr_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t05_perfTestRep WHERE apex_t05_ptr_id = %s", (ptr_id,))
        return _row_to_dict(cur.fetchone()) or None


def get_perf_test_by_migration(migration_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t05_perfTestRep WHERE apex_t01_migration_id = %s", (migration_id,))
        return _row_to_dict(cur.fetchone()) or None


def update_perf_test(ptr_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets, vals = [], []
    for fld in ["apex_t05_ptr_api_tested", "apex_t05_ptr_working_endpoints",
                 "apex_t05_ptr_average_resp_time", "apex_t05_ptr_throughput"]:
        if fld in data:
            sets.append(f"{fld} = %s")
            vals.append(data[fld])
    if not sets:
        return get_perf_test(ptr_id)
    vals.append(ptr_id)
    with get_cursor() as cur:
        cur.execute(f"UPDATE apex_t05_perfTestRep SET {', '.join(sets)} WHERE apex_t05_ptr_id = %s RETURNING *", vals)
        return _row_to_dict(cur.fetchone()) or None


# ===========================================================================
# apex_t06_error_dtls
# ===========================================================================

def create_error(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t06_error_dtls (
                apex_t01_migration_id, apex_t06_err_type, apex_t06_err_dtls, apex_t06_err_created_by
            ) VALUES (%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_migration_id"], data.get("apex_t06_err_type"),
             data.get("apex_t06_err_dtls"), data["apex_t06_err_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_error(err_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t06_error_dtls WHERE apex_t06_err_id = %s", (err_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_errors_by_migration(migration_id: int) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM apex_t06_error_dtls WHERE apex_t01_migration_id = %s ORDER BY apex_t06_err_id",
            (migration_id,))
        return _rows_to_list(cur.fetchall())


def list_errors_by_type(err_type: str) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM apex_t06_error_dtls WHERE apex_t06_err_type = %s ORDER BY apex_t06_err_id",
            (err_type,))
        return _rows_to_list(cur.fetchall())


def delete_error(err_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_t06_error_dtls WHERE apex_t06_err_id = %s", (err_id,))
        return cur.rowcount > 0


# ===========================================================================
# apex_t07_llm_dtls
# ===========================================================================

def create_llm_details(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO apex_t07_llm_dtls (
                apex_t01_ld_migration_id, apex_t07_ld_model_name,
                apex_t07_ld_consumed_tokens, apex_t07_ld_consumed_cost, apex_t07_ld_created_by
            ) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (data["apex_t01_ld_migration_id"], data["apex_t07_ld_model_name"],
             data.get("apex_t07_ld_consumed_tokens", 0), data.get("apex_t07_ld_consumed_cost", 0.0),
             data["apex_t07_ld_created_by"]))
        return _row_to_dict(cur.fetchone())


def get_llm_details(ld_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM apex_t07_llm_dtls WHERE apex_t07_ld_id = %s", (ld_id,))
        return _row_to_dict(cur.fetchone()) or None


def list_llm_details_by_migration(migration_id: int) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM apex_t07_llm_dtls WHERE apex_t01_ld_migration_id = %s ORDER BY apex_t07_ld_id",
            (migration_id,))
        return _rows_to_list(cur.fetchall())


def get_llm_consumption_summary(migration_id: int) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(apex_t07_ld_consumed_tokens), 0) AS total_tokens,
                      COALESCE(SUM(apex_t07_ld_consumed_cost), 0) AS total_cost,
                      COUNT(*) AS model_count
               FROM apex_t07_llm_dtls WHERE apex_t01_ld_migration_id = %s""",
            (migration_id,))
        return _row_to_dict(cur.fetchone())


def delete_llm_details(ld_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM apex_t07_llm_dtls WHERE apex_t07_ld_id = %s", (ld_id,))
        return cur.rowcount > 0
"""Pydantic models mirroring the apex database schema."""

from __future__ import annotations

from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Master Tables
# ---------------------------------------------------------------------------

class OrgCreate(BaseModel):
    apex_m01_org_name: str = Field(..., max_length=50)
    apex_m01_org_domain_name: Optional[str] = Field(None, max_length=50)
    apex_m01_source_local_f: str = Field(default="N", max_length=1)
    apex_m01_destination_local_f: str = Field(default="N", max_length=1)
    apex_m01_brd_f: str = Field(default="N", max_length=1)
    apex_m01_destination_new_repo_f: str = Field(default="N", max_length=1)
    apex_m01_active_f: str = Field(default="Y", max_length=1)
    apex_m01_subscribed_plan: Optional[str] = Field(None, max_length=50)
    apex_m01_created_by: str = Field(..., max_length=20)


class OrgResponse(OrgCreate):
    apex_m01_org_id: int
    apex_m01_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    apex_m02_user_id: str = Field(..., max_length=20)
    apex_m02_password: str = Field(..., max_length=255)
    apex_m02_org_id: int
    apex_m02_user_email_id: str = Field(..., max_length=50)
    apex_m02_active_f: str = Field(default="Y", max_length=1)
    apex_m02_created_by: str = Field(..., max_length=20)


class UserResponse(UserCreate):
    apex_m02_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class LLMMasterCreate(BaseModel):
    apex_m02_user_id: str = Field(..., max_length=20)
    apex_m03_eligible_model_name: str = Field(..., max_length=50)
    apex_m03_active_f: str = Field(default="Y", max_length=1)
    apex_m03_created_by: str = Field(..., max_length=20)


class LLMMasterResponse(LLMMasterCreate):
    apex_m03_lm_id: int
    apex_m03_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transaction Tables
# ---------------------------------------------------------------------------

class MigrationCreate(BaseModel):
    apex_t01_user_id: str = Field(..., max_length=20)
    apex_t01_source_repo_url: str = Field(..., max_length=50)
    apex_t01_destination_repo_url: Optional[str] = Field(None, max_length=50)
    apex_t01_conversion_type: Optional[str] = Field(None, max_length=50)
    apex_t01_detected_java_ver: Optional[str] = Field(None, max_length=10)
    apex_t01_migrating_java_ver: Optional[str] = Field(None, max_length=10)
    apex_t01_destination_repo_type: Optional[str] = Field(None, max_length=10)
    apex_t01_migrating_total_time: Optional[time] = None
    apex_t01_created_by: str = Field(..., max_length=20)


class MigrationResponse(MigrationCreate):
    apex_t01_migration_id: int
    apex_t01_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class RepoMigOptCreate(BaseModel):
    apex_t01_migration_id: int
    apex_t02_mo_run_test_suite_f: str = Field(default="N", max_length=1)
    apex_t02_mo_staticcode_chk_f: str = Field(default="N", max_length=1)
    apex_t02_mo_dependency_chk_f: str = Field(default="N", max_length=1)
    apex_t02_mo_business_logic_chk_f: str = Field(default="N", max_length=1)
    apex_t02_created_by: str = Field(..., max_length=20)


class RepoMigOptResponse(RepoMigOptCreate):
    apex_t02_mo_opt_id: int
    apex_t02_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class UnitTestReportCreate(BaseModel):
    apex_t01_migration_id: int
    apex_t03_utr_test_count: int = 0
    apex_t03_utr_test_passed: int = 0
    apex_t03_utr_test_failed: int = 0
    apex_t03_utr_test_generated: int = 0
    apex_t03_utr_testcase_file: Optional[bytes] = None
    apex_t03_utr_created_by: str = Field(..., max_length=20)


class UnitTestReportResponse(UnitTestReportCreate):
    apex_t03_utr_id: int
    apex_t03_utr_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class DependencyCreate(BaseModel):
    apex_t01_migration_id: int
    apex_t04_dep_total_dep: int = 0
    apex_t04_dep_license_issues_cnt: int = 0
    apex_t04_dep_vulnerabilities_cnt: int = 0
    apex_t04_dep_outdated_pack_cnt: int = 0
    apex_t04_dep_created_by: str = Field(..., max_length=20)


class DependencyResponse(DependencyCreate):
    apex_t04_dep_id: int
    apex_t04_dep_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class PerfTestReportCreate(BaseModel):
    apex_t01_migration_id: int
    apex_t05_ptr_api_tested: int = 0
    apex_t05_ptr_working_endpoints: int = 0
    apex_t05_ptr_average_resp_time: int = 0
    apex_t05_ptr_throughput: int = 0
    apex_t05_ptr_created_by: str = Field(..., max_length=20)


class PerfTestReportResponse(PerfTestReportCreate):
    apex_t05_ptr_id: int
    apex_t05_ptr_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class ErrorDetailsCreate(BaseModel):
    apex_t01_migration_id: int
    apex_t06_err_type: Optional[str] = Field(None, max_length=20)
    apex_t06_err_dtls: Optional[str] = Field(None, max_length=200)
    apex_t06_err_created_by: str = Field(..., max_length=20)


class ErrorDetailsResponse(ErrorDetailsCreate):
    apex_t06_err_id: int
    apex_t06_err_created_dt: date

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------

class LLMDetailsCreate(BaseModel):
    apex_t01_ld_migration_id: int
    apex_t07_ld_model_name: str = Field(..., max_length=20)
    apex_t07_ld_consumed_tokens: int = 0
    apex_t07_ld_consumed_cost: float = 0.0
    apex_t07_ld_created_by: str = Field(..., max_length=20)


class LLMDetailsResponse(LLMDetailsCreate):
    apex_t07_ld_id: int
    apex_t07_ld_created_dt: date

    model_config = {"from_attributes": True}
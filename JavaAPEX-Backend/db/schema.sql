-- ============================================================================
-- JavaAPEX Database Schema
-- PostgreSQL DDL for the APEX Migration Accelerator Platform
-- ============================================================================

-- Create the apex schema
CREATE SCHEMA IF NOT EXISTS apex;

-- ============================================================================
-- MASTER TABLES
-- ============================================================================

-- 1. Organization Master
CREATE TABLE apex.apex_m01_org (
    apex_m01_org_id             SERIAL          NOT NULL,
    apex_m01_org_name           VARCHAR(50)     NOT NULL,
    apex_m01_org_domain_name    VARCHAR(50),
    apex_m01_source_local_f     CHAR(1)         DEFAULT 'N'     NOT NULL,
    apex_m01_destination_local_f CHAR(1)        DEFAULT 'N'     NOT NULL,
    apex_m01_brd_f              CHAR(1)         DEFAULT 'N'     NOT NULL,
    apex_m01_destination_new_repo_f CHAR(1)     DEFAULT 'N'     NOT NULL,
    apex_m01_active_f           CHAR(1)         DEFAULT 'Y'     NOT NULL,
    apex_m01_subscribed_plan    VARCHAR(50),
    apex_m01_created_by         VARCHAR(20)     NOT NULL,
    apex_m01_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_m01_org PRIMARY KEY (apex_m01_org_id),
    CONSTRAINT ck_apex_m01_source_local_f CHECK (apex_m01_source_local_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_m01_destination_local_f CHECK (apex_m01_destination_local_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_m01_brd_f CHECK (apex_m01_brd_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_m01_destination_new_repo_f CHECK (apex_m01_destination_new_repo_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_m01_active_f CHECK (apex_m01_active_f IN ('Y', 'N')),
    CONSTRAINT uq_apex_m01_org_domain_name UNIQUE (apex_m01_org_domain_name)
);

-- 2. User Master
CREATE TABLE apex.apex_m02_user (
    apex_m02_user_id            VARCHAR(20)     NOT NULL,
    apex_m02_password           VARCHAR(255)    NOT NULL,
    apex_m02_org_id             INT             NOT NULL,
    apex_m02_user_email_id      VARCHAR(50)     NOT NULL,
    apex_m02_active_f           CHAR(1)         DEFAULT 'Y'     NOT NULL,
    apex_m02_created_by         VARCHAR(20)     NOT NULL,
    apex_m02_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_m02_user PRIMARY KEY (apex_m02_user_id),
    CONSTRAINT fk_apex_m02_user_org FOREIGN KEY (apex_m02_org_id)
        REFERENCES apex.apex_m01_org (apex_m01_org_id),
    CONSTRAINT ck_apex_m02_active_f CHECK (apex_m02_active_f IN ('Y', 'N')),
    CONSTRAINT uq_apex_m02_user_email_id UNIQUE (apex_m02_user_email_id)
);

-- 3. LLM Master
CREATE TABLE apex.apex_m03_llm_master (
    apex_m03_lm_id              SERIAL          NOT NULL,
    apex_m02_user_id            VARCHAR(20)     NOT NULL,
    apex_m03_eligible_model_name VARCHAR(50)    NOT NULL,
    apex_m03_active_f           CHAR(1)         DEFAULT 'Y'     NOT NULL,
    apex_m03_created_by         VARCHAR(20)     NOT NULL,
    apex_m03_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_m03_llm_master PRIMARY KEY (apex_m03_lm_id),
    CONSTRAINT fk_apex_m03_user FOREIGN KEY (apex_m02_user_id)
        REFERENCES apex.apex_m02_user (apex_m02_user_id),
    CONSTRAINT ck_apex_m03_active_f CHECK (apex_m03_active_f IN ('Y', 'N'))
);

-- ============================================================================
-- TRANSACTION TABLES
-- ============================================================================

-- 4. Migration Details
CREATE TABLE apex.apex_t01_migration_dtls (
    apex_t01_migration_id           BIGSERIAL       NOT NULL,
    apex_t01_user_id                VARCHAR(20)     NOT NULL,
    apex_t01_source_repo_url        VARCHAR(50)     NOT NULL,
    apex_t01_destination_repo_url   VARCHAR(50),
    apex_t01_conversion_type        VARCHAR(50),
    apex_t01_detected_java_ver      VARCHAR(10),
    apex_t01_migrating_java_ver     VARCHAR(10),
    apex_t01_destination_repo_type  VARCHAR(10),
    apex_t01_migrating_total_time   TIME,
    apex_t01_created_by             VARCHAR(20)     NOT NULL,
    apex_t01_created_dt             DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t01_migration_dtls PRIMARY KEY (apex_t01_migration_id),
    CONSTRAINT fk_apex_t01_user FOREIGN KEY (apex_t01_user_id)
        REFERENCES apex.apex_m02_user (apex_m02_user_id),
    CONSTRAINT ck_apex_t01_dest_repo_type CHECK (apex_t01_destination_repo_type IN ('new', 'existing'))
);

-- 5. Repository Migration Options
CREATE TABLE apex.apex_t02_repo_mig_opt (
    apex_t02_mo_opt_id              BIGSERIAL       NOT NULL,
    apex_t01_migration_id           BIGINT          NOT NULL,
    apex_t02_mo_run_test_suite_f    CHAR(1)         DEFAULT 'N'     NOT NULL,
    apex_t02_mo_staticcode_chk_f    CHAR(1)         DEFAULT 'N'     NOT NULL,
    apex_t02_mo_dependency_chk_f    CHAR(1)         DEFAULT 'N'     NOT NULL,
    apex_t02_mo_business_logic_chk_f CHAR(1)        DEFAULT 'N'     NOT NULL,
    apex_t02_created_by             VARCHAR(20)     NOT NULL,
    apex_t02_created_dt             DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t02_repo_mig_opt PRIMARY KEY (apex_t02_mo_opt_id),
    CONSTRAINT fk_apex_t02_migration FOREIGN KEY (apex_t01_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id),
    CONSTRAINT ck_apex_t02_run_test_suite_f CHECK (apex_t02_mo_run_test_suite_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_t02_staticcode_chk_f CHECK (apex_t02_mo_staticcode_chk_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_t02_dependency_chk_f CHECK (apex_t02_mo_dependency_chk_f IN ('Y', 'N')),
    CONSTRAINT ck_apex_t02_business_logic_chk_f CHECK (apex_t02_mo_business_logic_chk_f IN ('Y', 'N'))
);

-- 6. Unit Test Report
CREATE TABLE apex.apex_t03_unittestreport (
    apex_t03_utr_id                 BIGSERIAL       NOT NULL,
    apex_t01_migration_id           BIGINT          NOT NULL,
    apex_t03_utr_test_count         INT             DEFAULT 0,
    apex_t03_utr_test_passed        INT             DEFAULT 0,
    apex_t03_utr_test_failed        INT             DEFAULT 0,
    apex_t03_utr_test_generated     INT             DEFAULT 0,
    apex_t03_utr_testcase_file      BYTEA,
    apex_t03_utr_created_by         VARCHAR(20)     NOT NULL,
    apex_t03_utr_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t03_unittestreport PRIMARY KEY (apex_t03_utr_id),
    CONSTRAINT fk_apex_t03_migration FOREIGN KEY (apex_t01_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id)
);

-- 7. Dependency Details
CREATE TABLE apex.apex_t04_dependency (
    apex_t04_dep_id                 BIGSERIAL       NOT NULL,
    apex_t01_migration_id           BIGINT          NOT NULL,
    apex_t04_dep_total_dep          INT             DEFAULT 0,
    apex_t04_dep_license_issues_cnt INT             DEFAULT 0,
    apex_t04_dep_vulnerabilities_cnt INT            DEFAULT 0,
    apex_t04_dep_outdated_pack_cnt  INT             DEFAULT 0,
    apex_t04_dep_created_by         VARCHAR(20)     NOT NULL,
    apex_t04_dep_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t04_dependency PRIMARY KEY (apex_t04_dep_id),
    CONSTRAINT fk_apex_t04_migration FOREIGN KEY (apex_t01_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id)
);

-- 8. Performance Test Report
CREATE TABLE apex.apex_t05_perfTestRep (
    apex_t05_ptr_id                 BIGSERIAL       NOT NULL,
    apex_t01_migration_id           BIGINT          NOT NULL,
    apex_t05_ptr_api_tested         INT             DEFAULT 0,
    apex_t05_ptr_working_endpoints  INT             DEFAULT 0,
    apex_t05_ptr_average_resp_time  INT             DEFAULT 0,
    apex_t05_ptr_throughput         INT             DEFAULT 0,
    apex_t05_ptr_created_by         VARCHAR(20)     NOT NULL,
    apex_t05_ptr_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t05_perfTestRep PRIMARY KEY (apex_t05_ptr_id),
    CONSTRAINT fk_apex_t05_migration FOREIGN KEY (apex_t01_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id)
);

-- 9. Error Details
CREATE TABLE apex.apex_t06_error_dtls (
    apex_t06_err_id                 BIGSERIAL       NOT NULL,
    apex_t01_migration_id           BIGINT          NOT NULL,
    apex_t06_err_type               VARCHAR(20),
    apex_t06_err_dtls               VARCHAR(200),
    apex_t06_err_created_by         VARCHAR(20)     NOT NULL,
    apex_t06_err_created_dt         DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t06_error_dtls PRIMARY KEY (apex_t06_err_id),
    CONSTRAINT fk_apex_t06_migration FOREIGN KEY (apex_t01_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id)
);

-- 10. LLM Details (Consumption Tracking)
CREATE TABLE apex.apex_t07_llm_dtls (
    apex_t07_ld_id                  BIGSERIAL       NOT NULL,
    apex_t01_ld_migration_id        BIGINT          NOT NULL,
    apex_t07_ld_model_name          VARCHAR(20)     NOT NULL,
    apex_t07_ld_consumed_tokens     BIGINT          DEFAULT 0,
    apex_t07_ld_consumed_cost       NUMERIC(12, 6)  DEFAULT 0.0,
    apex_t07_ld_created_by          VARCHAR(20)     NOT NULL,
    apex_t07_ld_created_dt          DATE            DEFAULT CURRENT_DATE NOT NULL,

    CONSTRAINT pk_apex_t07_llm_dtls PRIMARY KEY (apex_t07_ld_id),
    CONSTRAINT fk_apex_t07_migration FOREIGN KEY (apex_t01_ld_migration_id)
        REFERENCES apex.apex_t01_migration_dtls (apex_t01_migration_id)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Organization indexes
CREATE INDEX ix_apex_m01_org_active ON apex.apex_m01_org (apex_m01_active_f);

-- User indexes
CREATE INDEX ix_apex_m02_user_org ON apex.apex_m02_user (apex_m02_org_id);
CREATE INDEX ix_apex_m02_user_active ON apex.apex_m02_user (apex_m02_active_f);

-- LLM Master indexes
CREATE INDEX ix_apex_m03_user ON apex.apex_m03_llm_master (apex_m02_user_id);
CREATE INDEX ix_apex_m03_active ON apex.apex_m03_llm_master (apex_m03_active_f);

-- Migration details indexes
CREATE INDEX ix_apex_t01_user ON apex.apex_t01_migration_dtls (apex_t01_user_id);
CREATE INDEX ix_apex_t01_created_dt ON apex.apex_t01_migration_dtls (apex_t01_created_dt);

-- Migration options index
CREATE INDEX ix_apex_t02_migration ON apex.apex_t02_repo_mig_opt (apex_t01_migration_id);

-- Unit test report index
CREATE INDEX ix_apex_t03_migration ON apex.apex_t03_unittestreport (apex_t01_migration_id);

-- Dependency index
CREATE INDEX ix_apex_t04_migration ON apex.apex_t04_dependency (apex_t01_migration_id);

-- Performance test report index
CREATE INDEX ix_apex_t05_migration ON apex.apex_t05_perfTestRep (apex_t01_migration_id);

-- Error details index
CREATE INDEX ix_apex_t06_migration ON apex.apex_t06_error_dtls (apex_t01_migration_id);
CREATE INDEX ix_apex_t06_err_type ON apex.apex_t06_error_dtls (apex_t06_err_type);

-- LLM details index
CREATE INDEX ix_apex_t07_migration ON apex.apex_t07_llm_dtls (apex_t01_ld_migration_id);
CREATE INDEX ix_apex_t07_model_name ON apex.apex_t07_llm_dtls (apex_t07_ld_model_name);
# MAPS UI (ford-credit/maps-ui-gcp-bq) — Functional Test Cases

## 1. Application Analysis Summary

| Attribute | Detail |
|-----------|--------|
| **Repository** | `github.com/ford-credit/maps-ui-gcp-bq` |
| **Application** | Ford Credit **MAPS** — a web-based reporting & analytics portal |
| **Type** | Java EE (Servlet/JSP-less), Gradle multi-module web application |
| **Modules** | `MAPSCommon`, `MAPSWAR`, `MAPSEAR`, `MAPSServer`, `secAdminEAR` |
| **Architecture** | Front-Controller (`MAPSServlet` at `/MAPS`) → Page/Navigation config (`pageTable.xml`) → **View Transformers (VT)** → **Business Facades** → **Integration Delegates / DAOs** |
| **UI Rendering** | Apache **Velocity** templates (`.vm`) — full pages + AJAX fragments |
| **Data Sources** | **Teradata**, **SQL Server**, **BigQuery** (`BQTable` — the GCP-BQ migration target) |
| **Reporting Engine** | SQL Server Reporting Services (**SSRS**) via JAX-WS SOAP |
| **Security** | CDS/ADR authorization (`ADRAuthorizer`), `SecurityContextFilter`, `AntiHackingFilter` |
| **Ops** | `/health` endpoint, `/api/unprotected/ping`, performance logging filter, gzip compression, job scheduler (`/jobScheduler`) |

### Core Functional Domains
Report Viewing • Briefing Books • Custom Organizations • Preferences • User Data • Organization Search • Production Verification/Release • Support & Navigation • Background Scheduler • Data Integration • Error Handling & Security.

---

## 2. Functional Test Case Count

> ### ✅ Total Functional Test Cases = **95**

| # | Module | Prefix | Count |
|---|--------|--------|-------|
| 1 | Authentication, Authorization & Session | `TC-AUTH` | 8 |
| 2 | Report Viewing & Navigation | `TC-RPT` | 15 |
| 3 | Briefing Book Management | `TC-BB` | 16 |
| 4 | Custom Organization | `TC-ORG` | 15 |
| 5 | Preferences | `TC-PREF` | 6 |
| 6 | User Data | `TC-USR` | 5 |
| 7 | Organization Search | `TC-SRCH` | 5 |
| 8 | Verification & Production Release | `TC-VER` | 5 |
| 9 | Support & Navigation | `TC-NAV` | 5 |
| 10 | Scheduler & Background Jobs | `TC-SCH` | 4 |
| 11 | Data Integration (Teradata / BigQuery / SSRS) | `TC-DATA` | 6 |
| 12 | Error Handling & Cross-cutting | `TC-ERR` | 5 |
| | **TOTAL** | | **95** |

---

## 3. Detailed Functional Test Cases

**Legend** — Priority: P1 (Critical), P2 (High), P3 (Medium). Type: `+` Positive, `−` Negative.

### Module 1 — Authentication, Authorization & Session (`TC-AUTH`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-AUTH-01 | Authorized user lands on Report page | Valid CDS user with `MAPSApplication/View` privilege | 1. Open app root URL `/MAPSWAR/MAPS` | Valid CDSID | User is authenticated and the default **Report Page** loads with the report menu (`null/null → getReportMenu`) | P1 | + |
| TC-AUTH-02 | Unauthorized user is blocked | User without `MAPSApplication/View` | 1. Access `/MAPS` | User lacking privilege | **Not Authorized** page is shown; no report data exposed | P1 | − |
| TC-AUTH-03 | Invalid/expired session handling | Session has expired | 1. Trigger any action after timeout | Expired `JSESSIONID` | **Invalid Session** page is displayed and user is prompted to re-login | P1 | − |
| TC-AUTH-04 | Session timeout warning & Continue | Active session nearing timeout | 1. Stay idle until warning 2. Click **Continue** | — | Session warning appears; **Continue** extends session (`SessionStatusContinue.vm`) | P2 | + |
| TC-AUTH-05 | Health check endpoint (unprotected) | App deployed | 1. GET `/health` | — | HTTP 200 with body `{"status": "pass"}`, `Content-Type: application/json`, no auth required | P1 | + |
| TC-AUTH-06 | Unprotected ping endpoint | App deployed | 1. GET `/api/unprotected/ping` | — | Responds successfully without authentication | P2 | + |
| TC-AUTH-07 | Anti-hacking filter blocks malicious input | App running | 1. Send request with XSS/SQLi payload in a parameter | `reportName=<script>alert(1)</script>` | `AntiHackingFilter` rejects/sanitizes the request; no script executes | P1 | − |
| TC-AUTH-08 | Direct action access without privilege | Logged-in user lacking `VerifyProd` | 1. Invoke `action=submitReleaseOfData` directly | Non-privileged user | Authorization denied; action not executed | P1 | − |

### Module 2 — Report Viewing & Navigation (`TC-RPT`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-RPT-01 | Default landing loads report menu | Authorized user | 1. Open `/MAPS` (null/null) | — | Report menu is fetched via `ReportFacade.getReportMenu` and rendered on Report Page | P1 | + |
| TC-RPT-02 | Navigate to Report page from menu | On any page | 1. Click **Report Page** (`gotoReportPage`) | — | Report Page reloads with report tree/menu | P1 | + |
| TC-RPT-03 | Load report dimensions (AJAX) | On Report Page | 1. Select a report node (`getDimensionsContent`) | `dimensionId`, `selectedReport` | Dimensions fragment (`DimensionsContent.ajax.vm`) returns available dimensions | P1 | + |
| TC-RPT-04 | Load report options (AJAX) | Report selected | 1. Open options (`getOptionsContent`) | `reportName` | Options fragment (`OptionsContent.ajax.vm`) renders configurable options | P2 | + |
| TC-RPT-05 | View report content (AJAX) | Report + params selected | 1. Run report (`getReportContent`) | `reportName`, `reportType`, `rptNb` | Report content fragment (`ReportContent.ajax.vm`) renders result grid | P1 | + |
| TC-RPT-06 | View full report | Report selected | 1. Trigger `viewReport` | `ItemPath`, `path` | Full report renders on Report Page via `ReportFacade.getReport` | P1 | + |
| TC-RPT-07 | Reload organization menu | On Report Page | 1. Trigger `reloadOrgMenu` | — | Organization AJAX fragment (`OrganizationContent.ajax.vm`) refreshes | P2 | + |
| TC-RPT-08 | Retrieve multi-org children | Multi-org node present | 1. Expand node (`retreiveMultiOrgChildren`) | `multiOrgDimensionId`, `multiOrgParentIds` | Child org nodes load (`MultiOrgChildData.ajax.vm`) | P2 | + |
| TC-RPT-09 | Export report to PDF | Report displayed | 1. Click **PDF** (`viewReportPDF`) | `format=PDF` | PDF stream downloads via `OutputStreamResponseHandler` | P1 | + |
| TC-RPT-10 | Export report to Excel | Report displayed | 1. Click **Excel** (`viewReportExcel`) | `format=EXCEL` | Excel stream downloads | P1 | + |
| TC-RPT-11 | Report with no data | Params returning 0 rows | 1. Run report | Params with empty result | Report renders with a "no data" state, no error | P2 | + |
| TC-RPT-12 | Report with invalid parameters | On Report Page | 1. Submit invalid params | `rptNb=INVALID` | AJAX error fragment returned via `MAPSAjaxErrorPageResolver` | P2 | − |
| TC-RPT-13 | Reports Not Available | SSRS/catalog unavailable | 1. Open Report Page | Catalog service down | **ReportsNotAvailable** page shown gracefully | P1 | − |
| TC-RPT-14 | Open Report Loader | Saved request exists | 1. Trigger `openReportLoader` | `RRIKey` | Report Loader page (`ReportLoaderPage.vm`) opens | P2 | + |
| TC-RPT-15 | Save report request info (PUR) | Report configured | 1. Trigger `saveReportRequestInfo` | `RRIKey`, `toParams` | Request saved; `SaveReportRequest.ajax.vm` confirms | P2 | + |

### Module 3 — Briefing Book Management (`TC-BB`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-BB-01 | View briefing book list | Authorized user | 1. Trigger `getBriefingbookData` | — | Briefing Book page lists user's books/folders | P1 | + |
| TC-BB-02 | Open Add-to-Briefing-Book page | Report open | 1. Trigger `getAddBriefingbook` | `selectedReport` | Add Briefing Book page (`AddBriefingbookPage.vm`) opens | P1 | + |
| TC-BB-03 | Save briefing book (valid) | On Add BB page | 1. Enter name/folder 2. Save (`saveBriefingbook`) | `fldname`, `reportName` (≤50 chars) | Report saved to briefing book; confirmation shown | P1 | + |
| TC-BB-04 | Save with duplicate folder name | Folder name already exists | 1. Save folder with existing name | Duplicate `fldname` | Validation error **1001** (Duplicate BB folder name) | P2 | − |
| TC-BB-05 | Save with duplicate report name | Report name already in folder | 1. Save report with existing name | Duplicate `reportName` | Validation error **1002** (Duplicate BB report name) | P2 | − |
| TC-BB-06 | Folder name exceeds 50 chars | On Add Folder page | 1. Enter 51-char name 2. Save | 51-char `fldname` | Validation error **1004** (Folder name > 50 chars) | P2 | − |
| TC-BB-07 | Report name all spaces | On Add BB page | 1. Enter only spaces 2. Save | `reportName="     "` | Validation error **1006** (Report name all spaces) | P2 | − |
| TC-BB-08 | Field with invalid characters | On Add BB page | 1. Enter invalid chars 2. Save | `reportName="rep@rt#"` | Validation error **1003** (Invalid characters) | P2 | − |
| TC-BB-09 | Add briefing book folder | On Add BB page | 1. Trigger `addBriefingbookFolder` | `fldname` | Add Folder page (`AddFolderPage.vm`) opens | P2 | + |
| TC-BB-10 | Update folders | On Add Folder page | 1. Modify 2. `updateFolders` | `selectedFolder` | Folders updated; returns to Add BB page | P2 | + |
| TC-BB-11 | Cancel add folder | On Add Folder page | 1. Trigger `cancelAddFolder` | — | Discards changes; returns to Add BB page | P3 | + |
| TC-BB-12 | Delete briefing book | BB exists | 1. Trigger `deleteBriefingbook` | `rptNb`, `selectedFolder` | Briefing book/report removed; `BBContent.ajax.vm` refreshes | P1 | + |
| TC-BB-13 | Open saved report from BB | Saved BB report exists | 1. Trigger `getSavedRptData` | `rptNb` | Saved report opens on Report Page | P1 | + |
| TC-BB-14 | Print saved BB report (PDF) | Saved BB report exists | 1. Trigger `printBBReport` | `rptNb` | PDF stream of the saved report is generated | P2 | + |
| TC-BB-15 | View AMR subscription list | Authorized user | 1. Trigger `getAMRList` | — | Automated Mail Report list (`AMRListPage.vm`) displays subscriptions | P2 | + |
| TC-BB-16 | Add / remove AMR subscription | On AMR list | 1. `addSubscription` then `removeSubscription` | `subId` | Subscription toggled; `AMRSubscription.ajax.vm` reflects status | P2 | + |

### Module 4 — Custom Organization (`TC-ORG`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-ORG-01 | View custom org list | Authorized user | 1. Trigger `gotoCustomOrgPage` | — | Maintain Custom Org page lists existing custom orgs | P1 | + |
| TC-ORG-02 | Open Create Custom Org page | On Custom Org page | 1. Trigger `gotoCreateCustomOrgPage` | — | Create page (`CreateModifyCustomOrgPage.vm`) opens with org list | P1 | + |
| TC-ORG-03 | Create custom org (valid) | On Create page | 1. Enter name 2. Add components 3. `saveModifications` | `customOrgNm="TEST_ORG"` | Custom org created; navigates to Modify page | P1 | + |
| TC-ORG-04 | Create with blank name | On Create page | 1. Leave name blank 2. Save | `customOrgNm=""` | Validation error **1007** (Custom org name blank) | P2 | − |
| TC-ORG-05 | Create with invalid characters | On Create page | 1. Enter invalid name 2. Save | `customOrgNm="org@#"` | Validation error **1003** (Invalid characters) | P2 | − |
| TC-ORG-06 | Add component | On Create/Modify page | 1. Trigger `addComponent` | `parentId`, `dimensionId` | Component added; `CreateCustomOrgContentAJAX.vm` refreshes | P1 | + |
| TC-ORG-07 | Remove component | Component present | 1. Trigger `removeComponent` | `dimensionId` | Component removed; content fragment refreshes | P2 | + |
| TC-ORG-08 | Reload selection tree | On Create/Modify page | 1. Trigger `reloadCustomOrgSelectionTree` | — | Selection tree reloads | P3 | + |
| TC-ORG-09 | Open Modify Custom Org page | Custom org exists | 1. Trigger `gotoModifyCustomOrgPage` | `customOrgNm` | Modify page loads with existing components | P1 | + |
| TC-ORG-10 | Save modifications | On Modify page | 1. Change 2. `saveModifications` | Modified components | Changes saved via `CustomOrgFacade.saveChanges` | P1 | + |
| TC-ORG-11 | Delete custom org | Custom org exists | 1. Trigger `deleteCustomOrg` | `customOrgNm` | Org deleted; `CustomOrgContentAJAX.vm` refreshes | P1 | + |
| TC-ORG-12 | Delete failure handling | DB error during delete | 1. Trigger `deleteCustomOrg` | DB down | Graceful AJAX error via `MAPSAjaxErrorPageResolver` | P2 | − |
| TC-ORG-13 | Copy custom org | Custom org exists | 1. Trigger `copyCustomOrg` | `customOrgNm` | Copy created; list refreshes | P2 | + |
| TC-ORG-14 | Org search form (custom org) | On Create/Modify page | 1. Trigger `getOrgSearchForm` | — | `CustomOrgSearchFormAJAX.vm` search form appears | P2 | + |
| TC-ORG-15 | Org search results (custom org) | On search form | 1. Trigger `getOrgSearchResults` | Search term | `OrgSearchResultsAJAX.vm` returns matching orgs | P2 | + |

### Module 5 — Preferences (`TC-PREF`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-PREF-01 | Open Preference page | Authorized user | 1. Trigger `gotoPreferencePage` | — | Preference page loads org list (`PreferenceFacade.getOrgList`) | P1 | + |
| TC-PREF-02 | Retrieve org children | On Preference page | 1. Expand org node (`retreiveChildren`) | `parentId` | Child org data loads (`OrgChildData.ajax.vm`) | P2 | + |
| TC-PREF-03 | Save organization preference | Org selected | 1. Select org 2. `savePreference` | Selected org id | Preference saved; `Save.ajax.vm` confirms | P1 | + |
| TC-PREF-04 | Saved-OK confirmation | Preference saved | 1. Complete save | — | **SavedOkPage** confirmation displayed | P2 | + |
| TC-PREF-05 | Save with no org selected | On Preference page | 1. Save without selecting | Empty selection | Validation prevents save / prompts selection | P2 | − |
| TC-PREF-06 | Preference persists across sessions | Preference saved | 1. Re-login 2. Open Report Page | Same user | Saved default org is applied automatically | P2 | + |

### Module 6 — User Data (`TC-USR`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-USR-01 | Open User Data page | `MAPSApplication/View` privilege | 1. Trigger `gotoUserDataPage` | — | User Data page loads (`UserDataFacade.getUserData`) | P1 | + |
| TC-USR-02 | Retrieve user data | On User Data page | 1. Trigger `retrieveUserData` | Target CDSID | User's saved data retrieved and displayed | P1 | + |
| TC-USR-03 | Delete user data | User data exists | 1. Trigger `deleteUserData` | Data id | Selected user data deleted; page refreshes | P1 | + |
| TC-USR-04 | Transfer user data | Two valid users | 1. Trigger `transferUserData` | Source + target CDSID | Data transferred to target user | P2 | + |
| TC-USR-05 | Transfer to invalid user | On User Data page | 1. Transfer to non-existent user | Invalid target CDSID | Error shown; no data transferred | P2 | − |

### Module 7 — Organization Search (`TC-SRCH`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-SRCH-01 | Open org search form | On Report/Custom Org page | 1. Trigger `getOrgSearchForm` | — | `OrgSearchFormAJAX.vm` search form appears | P2 | + |
| TC-SRCH-02 | Search by valid criteria | On search form | 1. Enter term 2. `getOrgSearchResults` | Valid org name/id | Matching orgs returned (`performOrgSearch`) | P1 | + |
| TC-SRCH-03 | Search with no matches | On search form | 1. Search unknown term | Non-existent org | Empty results state shown, no error | P2 | + |
| TC-SRCH-04 | Search with special characters | On search form | 1. Enter special chars | `%`, `'`, `--` | Input sanitized; no SQL injection; safe results | P1 | − |
| TC-SRCH-05 | Custom org search form loads | On Custom Org page | 1. Trigger search form | — | `CustomOrgSearchFormAJAX.vm` renders correctly | P3 | + |

### Module 8 — Verification & Production Release (`TC-VER`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-VER-01 | Open Verification page | User with verification access | 1. Trigger `gotoVerificationPage` | `verificationMode` | Verification menu loads (`getVerificationMenu`) | P1 | + |
| TC-VER-02 | Release data to production (authorized) | User with `VerifyProd/View` | 1. Trigger `submitReleaseOfData` | Release payload | Data released via `VerificationFacade.releaseToProduction` | P1 | + |
| TC-VER-03 | Release without privilege | User lacking `VerifyProd` | 1. Trigger `submitReleaseOfData` | Non-privileged user | Authorization denied; release blocked | P1 | − |
| TC-VER-04 | Exit verification to Report page | On Verification page | 1. Trigger `goBacktoReportPageFromPreProd` | — | Returns to Report Page (`exitVerificationPage`) | P2 | + |
| TC-VER-05 | Extended history page | Authorized user | 1. Trigger `gotoExtentedHistoryPage` | — | Extended history menu loads (`getExtHistoryMenu`) | P2 | + |

### Module 9 — Support & Navigation (`TC-NAV`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-NAV-01 | Main menu renders all links | Logged in | 1. Load any page | — | Main menu shows Preference, Report, Splash, Support, Test links (`MainMenu.layer.vm`) | P2 | + |
| TC-NAV-02 | Support page loads | Logged in | 1. Trigger `gotoSupportPage` | — | Support page (`SupportPage.vm`) with app/support info | P2 | + |
| TC-NAV-03 | Splash page loads | Logged in | 1. Trigger `gotoSplashPage` | — | Splash page (`SplashPage.vm`) renders | P3 | + |
| TC-NAV-04 | Conversation/session state preserved | Mid-workflow | 1. Navigate between pages | — | Conversation context persists (no `3004` context-not-found) | P1 | + |
| TC-NAV-05 | Response compression (gzip) | App running | 1. Request `/MAPS` with `Accept-Encoding: gzip` | — | Response is gzip-compressed by `Compress` filter | P3 | + |

### Module 10 — Scheduler & Background Jobs (`TC-SCH`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-SCH-01 | Job scheduler endpoint triggers job | Scheduler configured | 1. Invoke `/jobScheduler` | Job params | `MAPSJobSchedulerServlet` processes the scheduled job | P2 | + |
| TC-SCH-02 | Refresh-and-notify task executes | Scheduler running | 1. Trigger ProdLive refresh task | — | Cache refreshed and notification sent (`ProdLiveRefreshAndNotifyTask`) | P2 | + |
| TC-SCH-03 | Clear-cache-and-notify task | Scheduler running | 1. Trigger clear-cache task | — | Cache cleared; notification sent (`ClearCacheAndNotifyTask`) | P2 | + |
| TC-SCH-04 | Process control records filter | Scheduler running | 1. Run job with control filter | — | Only eligible records processed (`ProcessControlRecordsFilter`) | P3 | + |

### Module 11 — Data Integration (Teradata / BigQuery / SSRS) (`TC-DATA`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-DATA-01 | Report data from Teradata | Teradata reachable | 1. Run a Teradata-backed report | Valid query params | Data retrieved via `TeradataDAO`; report renders | P1 | + |
| TC-DATA-02 | Report data from BigQuery | BigQuery configured | 1. Run a BQ-backed report | `BQTable` mapping | Data retrieved from BigQuery (GCP-BQ migration path) | P1 | + |
| TC-DATA-03 | SSRS report execution | SSRS/SOAP reachable | 1. Execute an SSRS report | Report `ItemPath` | Report executes via JAX-WS SOAP and renders/exports | P1 | + |
| TC-DATA-04 | Database unavailable handling | DB down | 1. Run any DB-backed report | Connection failure | Graceful error **3002** (Database unavailable) | P1 | − |
| TC-DATA-05 | Organization data from SQL Server | SQL Server reachable | 1. Load org hierarchy | — | Org data loads via `OrgSQLServerDAO` | P2 | + |
| TC-DATA-06 | Unique constraint on save | Existing key | 1. Save duplicate record | Duplicate key | Error **3001** (Unique constraint) surfaced cleanly | P2 | − |

### Module 12 — Error Handling & Cross-cutting (`TC-ERR`)

| ID | Title | Precondition | Steps | Test Data | Expected Result | Pri | Type |
|----|-------|--------------|-------|-----------|-----------------|-----|------|
| TC-ERR-01 | General exception page | Unexpected server error | 1. Force a runtime error | — | **GeneralException** page shown (system error **3003**) | P1 | − |
| TC-ERR-02 | AJAX general exception | AJAX call errors | 1. Force error on AJAX action | — | `AJAXGeneralException.vm` fragment returned, page stays intact | P1 | − |
| TC-ERR-03 | AJAX unauthorized | Session invalid during AJAX | 1. Fire AJAX action after logout | Expired session | AJAX invalid-session/unauthorized fragment returned | P2 | − |
| TC-ERR-04 | Performance logging | App running | 1. Perform any action | — | `MAPSPerformanceLoggingFilter` records timing metrics | P3 | + |
| TC-ERR-05 | Conversation context not found | Stale conversation token | 1. Resume with expired token | Invalid `page_timeStamp` | Error **3004** handled with a friendly message | P2 | − |

---

## 4. Traceability Notes

- **Routing source of truth:** `MAPSWAR/src/main/resources/xml/pageTable.xml` (page definitions + navigation rules).
- **Front controller:** `MAPSServlet` (`/MAPS`, `/MAPSWAR/MAPS`) — see `MAPSWAR/src/main/webapp/WEB-INF/web.xml`.
- **Validation codes:** `com.ford.fc.MAPS.common.ValidationConstants` (1001–1007 business validations; 3001–3004 system).
- **Health/Ops:** `com.ford.fc.MAPS.health.HealthCheck` → `/health` returns `{"status":"pass"}`.
- **Recommended automation tools:** Selenium (UI flows), REST Assured (`/health`, `/api/unprotected/ping`, AJAX endpoints), and DB assertion utilities for Teradata/BigQuery data validation.

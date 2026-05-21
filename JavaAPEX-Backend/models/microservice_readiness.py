from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MicroserviceScoreBreakdown(BaseModel):
    name: str
    score: int
    weight: int
    summary: str


class ServiceCandidate(BaseModel):
    name: str
    packages: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    scaling_signals: List[str] = Field(default_factory=list)
    external_integrations: List[str] = Field(default_factory=list)
    transactional: bool = False


class AnalysisDiagnostics(BaseModel):
    java_files_total: int = 0
    java_files_scanned: int = 0
    package_count: int = 0
    detected_modules: int = 0
    cross_module_dependencies: int = 0
    circular_dependencies: int = 0
    external_integration_count: int = 0
    scan_truncated: bool = False


class DetailedEligibilityReport(BaseModel):
    project_structure: List[str] = Field(default_factory=list)
    package_structure: List[str] = Field(default_factory=list)
    module_boundaries: List[str] = Field(default_factory=list)
    dependency_coupling: List[str] = Field(default_factory=list)
    database_access_patterns: List[str] = Field(default_factory=list)
    communication_analysis: List[str] = Field(default_factory=list)
    deployment_independence: List[str] = Field(default_factory=list)
    scalability_indicators: List[str] = Field(default_factory=list)


class MicroserviceReadinessReport(BaseModel):
    projectName: str
    score: int
    eligibility: str
    recommendedArchitecture: str
    summary: str
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    serviceCandidates: List[ServiceCandidate] = Field(default_factory=list)
    couplingIssues: List[str] = Field(default_factory=list)
    databaseConcerns: List[str] = Field(default_factory=list)
    scalingCandidates: List[str] = Field(default_factory=list)
    recommendedMigrationStrategy: List[str] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    scoreBreakdown: List[MicroserviceScoreBreakdown] = Field(default_factory=list)
    detailedEligibilityReport: DetailedEligibilityReport = Field(default_factory=DetailedEligibilityReport)
    architecturalObservations: List[str] = Field(default_factory=list)
    analysisDiagnostics: AnalysisDiagnostics = Field(default_factory=AnalysisDiagnostics)
    reportGeneratedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)


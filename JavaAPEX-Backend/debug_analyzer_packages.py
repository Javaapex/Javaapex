import os, sys, re
from pathlib import Path
sys.path.insert(0, r'D:\JavaAPEX\JavaAPEX-Backend')
from analyzers.microservice_readiness_analyzer import MicroserviceReadinessAnalyzer
from services.repository_workspace_service import RepositoryWorkspace

workspace_path = r'C:\Users\Admin\AppData\Local\Temp\migrations\repo_workspaces\24d808823b7d048adb36f192'
workspace = RepositoryWorkspace(
    repo_url='https://github.com/spring-projects/spring-petclinic',
    normalized_repo_url='https://github.com/spring-projects/spring-petclinic',
    owner='spring-projects',
    repo='spring-petclinic',
    workspace_path=workspace_path,
    default_branch='main',
    cache_key='remote',
    auth_scope_key='public',
)
analyzer = MicroserviceReadinessAnalyzer()
facts = list(analyzer._scan_java_facts(Path(workspace_path)))
packages = [fact.package_name for fact in facts if fact.package_name]
print('analyzer_fact_count', len(facts))
print('package count', len(set(packages)))
for package in sorted(set(packages)):
    print('package:', package)
from utils.java_analysis_utils import common_package_prefix
base = common_package_prefix(packages)
print('analyzer base_prefix:', base)
for fact in facts[:20]:
    print('fact', fact.path, fact.package_name, fact.module_name, fact.is_service, fact.is_controller)

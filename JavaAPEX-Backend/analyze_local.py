import asyncio
import sys
import os
sys.path.append('.')
from services.migration_service import MigrationService

async def analyze():
    project_path = r'C:\Users\PULIMURUGAN T\Downloads\java-migration-accelerator-clean-main\java-migration-accelerator-clean-main\test-java-project'
    print(f"Project path: {project_path}")
    print(f"Absolute path: {os.path.abspath(project_path)}")
    print(f"Path exists: {os.path.exists(project_path)}")
    if os.path.exists(project_path):
        print(f"Contents: {os.listdir(project_path)}")

    service = MigrationService()
    result = await service.analyze_project(project_path)
    print('ANALYSIS RESULT:')
    import json
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(analyze())
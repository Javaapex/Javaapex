import asyncio
import sys
import os
sys.path.append('java-migration-backend/Java_Migration_Accelerator_backend')
from java_migration_backend.services.migration_service import MigrationService

async def analyze():
    service = MigrationService()
    result = await service.analyze_project('OnlineTravelAgency')
    print('ANALYSIS RESULT:')
    import json
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(analyze())
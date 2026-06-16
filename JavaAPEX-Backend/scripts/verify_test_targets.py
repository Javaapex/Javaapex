import os
import sys
from pathlib import Path
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)

# Mock some project structure
project_path = "C:/Java-Sorim-Apex/temp_test_project"
src_main = Path(project_path) / "src/main/java/com/example"
os.makedirs(src_main, exist_ok=True)

(src_main / "CriticalService.java").write_text("package com.example;\npublic class CriticalService { public void doWork() {} }")
(src_main / "NormalService.java").write_text("package com.example;\npublic class NormalService { public void doWork() {} }")

# Mock issues
mock_issues = [
    {
        "severity": "critical",
        "category": "bugs",
        "message": "Potential NullPointerException",
        "file_path": "com/example/CriticalService.java"
    }
]

# Import the service
sys.path.append("C:/Java-Sorim-Apex/JavaAPEX-Backend - Copy")
from services.llm_test_pipeline import LLMTestPipelineService

service = LLMTestPipelineService()

print("\n--- Testing Target Collection ---")
# Limit 5
targets = service._collect_java_test_targets(project_path, limit=5, issues=mock_issues)

print(f"Total targets picked: {len(targets)}")
for t in targets:
    print(f"Target: {t['class']} in {t['package']} (Path: {t['relpath']})")

# Verify priority
critical_picked = any(t['class'] == 'CriticalService' for t in targets)
print(f"\nCriticalService prioritized: {'✅ YES' if critical_picked else '❌ NO'}")

# Cleanup
import shutil
shutil.rmtree(project_path)
print("--- Test Complete ---")

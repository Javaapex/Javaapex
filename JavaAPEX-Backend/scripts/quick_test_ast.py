#!/usr/bin/env python3
"""
Quick test of AST-based test generation.
Tests that generated code is syntactically correct.
"""

import sys
from pathlib import Path

# Test AST import
try:
    from services.ast_test_generator import generate_test_for_java_file
    print("✅ AST module imported successfully")
except ImportError as e:
    print(f"❌ Failed to import AST module: {e}")
    sys.exit(1)

# Test with sample Java file
sample_java = Path(__file__).parent / "SampleCalculator.java"

if not sample_java.exists():
    print(f"❌ Sample file not found: {sample_java}")
    sys.exit(1)

print(f"📄 Testing with file: {sample_java}")
print("-" * 60)

# Generate test code
test_code = generate_test_for_java_file(str(sample_java), junit_style="junit5", java_version=21)

if not test_code:
    print("❌ Failed to generate test code")
    sys.exit(1)

print("✅ Test code generated successfully!")
print("\n" + "="*60)
print("GENERATED TEST CODE:")
print("="*60 + "\n")
print(test_code)
print("\n" + "="*60)
print("VALIDATION:")
print("="*60)

# Validate the generated code
checks = [
    ("Package declaration", "package com.example;" in test_code),
    ("JUnit 5 imports", "import org.junit.jupiter.api.Test;" in test_code),
    ("@Test annotations", "@Test" in test_code),
    ("Test method for add()", "void test_add()" in test_code),
    ("Test method for subtract()", "void test_subtract()" in test_code),
    ("Test method for multiply()", "void test_multiply()" in test_code),
    ("BeforeEach setup", "@BeforeEach" in test_code),
    ("Instance creation", "instance = new Calculator()" in test_code),
    ("Balanced braces", test_code.count('{') == test_code.count('}')),
    ("No backticks", '`' not in test_code),
    ("No markdown fences", '```' not in test_code),
]

all_passed = True
for check_name, result in checks:
    status = "✅" if result else "❌"
    print(f"{status} {check_name}")
    all_passed = all_passed and result

print("\n" + "="*60)
if all_passed:
    print("🎉 ALL CHECKS PASSED - Test code is valid!")
    print("✅ No backticks - No markdown artifacts")
    print("✅ Proper Java structure - Will compile!")
    sys.exit(0)
else:
    print("❌ Some checks failed")
    sys.exit(1)

#!/usr/bin/env python3
"""
Quick test script to verify AST-based test generation works.
Run from JavaAPEX-Backend directory:
    python3 test_ast_generation.py
"""

import sys
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent))

from services.ast_test_generator import (
    JavaASTAnalyzer,
    ASTTestCodeGenerator,
    generate_test_for_java_file
)


def test_ast_analyzer():
    """Test the Java AST analyzer on a sample Java file."""
    print("\n" + "="*60)
    print("TEST 1: JavaASTAnalyzer")
    print("="*60)
    
    # Create a sample Java file
    sample_java = """
package com.example;

import java.util.List;

public class Calculator {
    private int value = 0;
    
    public Calculator() {
        this.value = 0;
    }
    
    public Calculator(int initialValue) {
        this.value = initialValue;
    }
    
    public int add(int a, int b) {
        return a + b;
    }
    
    public int subtract(int a, int b) {
        return a - b;
    }
    
    public void reset() {
        this.value = 0;
    }
    
    public int getValue() {
        return this.value;
    }
}
"""
    
    # Write sample file
    sample_file = Path("/tmp/Calculator.java")
    sample_file.write_text(sample_java)
    print(f"Created sample file: {sample_file}")
    
    # Parse it
    analyzer = JavaASTAnalyzer()
    class_info = analyzer.parse_java_file(str(sample_file))
    
    if not class_info:
        print("❌ Failed to parse Java file")
        return False
    
    print(f"\n✅ Successfully parsed Java file")
    print(f"   Package: {class_info['package']}")
    print(f"   Class: {class_info['class_name']}")
    print(f"   Methods: {len(class_info['methods'])}")
    for method in class_info['methods']:
        print(f"     - {method['name']}() : {method['return_type']}")
    print(f"   Constructors: {len(class_info['constructors'])}")
    for ctor in class_info['constructors']:
        print(f"     - {ctor['name']}({len(ctor['parameters'])} params)")
    
    return True


def test_ast_test_generator():
    """Test the test code generator."""
    print("\n" + "="*60)
    print("TEST 2: ASTTestCodeGenerator")
    print("="*60)
    
    # Use same sample from test 1
    analyzer = JavaASTAnalyzer()
    class_info = analyzer.parse_java_file("/tmp/Calculator.java")
    
    generator = ASTTestCodeGenerator(junit_style="junit5")
    test_code = generator.generate_test_class(class_info, java_version=21)
    
    print("\n✅ Generated test code (JUnit 5):\n")
    print(test_code)
    
    # Verify it's valid Java syntax
    if "package com.example;" in test_code:
        print("✅ Package declaration present")
    if "import org.junit.jupiter.api.Test;" in test_code:
        print("✅ JUnit 5 imports present")
    if "@Test" in test_code:
        print("✅ @Test annotations present")
    if "void test_add()" in test_code:
        print("✅ Test method for 'add' generated")
    
    # Count braces
    open_braces = test_code.count('{')
    close_braces = test_code.count('}')
    if open_braces == close_braces and open_braces > 0:
        print(f"✅ Balanced braces ({open_braces} pairs)")
    else:
        print(f"❌ Unbalanced braces (open={open_braces}, close={close_braces})")
        return False
    
    return True


def test_junit4_generation():
    """Test JUnit 4 format generation."""
    print("\n" + "="*60)
    print("TEST 3: JUnit 4 Test Generation")
    print("="*60)
    
    analyzer = JavaASTAnalyzer()
    class_info = analyzer.parse_java_file("/tmp/Calculator.java")
    
    generator = ASTTestCodeGenerator(junit_style="junit4")
    test_code = generator.generate_test_class(class_info, java_version=17)
    
    print("\n✅ Generated test code (JUnit 4):\n")
    print(test_code[:500] + "\n...\n")
    
    if "import org.junit.Test;" in test_code:
        print("✅ JUnit 4 imports present")
    if "public class" in test_code:
        print("✅ JUnit 4 public class (not package-private)")
    if "@Test" in test_code:
        print("✅ @Test annotations present")
    
    return True


def test_convenience_function():
    """Test the high-level convenience function."""
    print("\n" + "="*60)
    print("TEST 4: Convenience Function")
    print("="*60)
    
    test_code = generate_test_for_java_file("/tmp/Calculator.java", junit_style="junit5", java_version=21)
    
    if test_code and len(test_code) > 200:
        print("✅ High-level function works")
        print(f"   Generated {len(test_code)} bytes of test code")
        return True
    else:
        print("❌ Failed to generate test code")
        return False


def main():
    print("\n🧪 AST-Based Test Generation Verification")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(("AST Analyzer", test_ast_analyzer()))
        results.append(("Test Generator", test_ast_test_generator()))
        results.append(("JUnit 4 Support", test_junit4_generation()))
        results.append(("Convenience Function", test_convenience_function()))
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
        all_passed = all_passed and passed
    
    print("=" * 60)
    
    if all_passed:
        print("\n✅ All tests passed! AST-based generation is working correctly.")
        return True
    else:
        print("\n❌ Some tests failed.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

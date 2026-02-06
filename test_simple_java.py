#!/usr/bin/env python3
"""
Simple test for Java version detection
"""
import sys
import os
import asyncio

# Add the backend path to sys.path
sys.path.append('java-migration-backend/Java_Migration_Accelerator_backend/java-migration-backend')

from services.github_service import GitHubService

async def test_simple():
    """Test Java version detection on a simple Java 1.0 file"""

    # Create a mock repository object with our test file
    class MockFile:
        def __init__(self, name, content):
            self.name = name
            self.content = content
            self.type = "file"  # Add type attribute

        @property
        def decoded_content(self):
            class MockDecodedContent:
                def decode(self, encoding='utf-8', errors='ignore'):
                    return self._content
            mock = MockDecodedContent()
            mock._content = self.content
            return mock

    class MockRepository:
        def __init__(self, files):
            self.files = files

        def get_contents(self, path=""):
            if path == "":
                # Return root files
                return [MockFile(f['name'], f['content']) for f in self.files]
            else:
                # Find specific file
                for f in self.files:
                    if f['name'] == path:
                        return MockFile(f['name'], f['content'])
                raise Exception(f"File {path} not found")

    # Test data - simple Java 1.0 file
    test_files = [{
        'name': 'HelloWorld.java',
        'content': '''// Test Java 1.0 file - should be detected as Java 1.0
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}'''
    }]

    # Create mock repository
    mock_repo = MockRepository(test_files)

    # Test the detection
    service = GitHubService()

    print("🧪 Simple Java Version Detection Test")
    print("=" * 50)

    try:
        # Test the detection
        print("📁 Test file content:")
        print(test_files[0]['content'])
        print()

        # Debug: check what files are found
        java_files = await service._scan_repo_for_java_files(mock_repo)
        print(f"📂 Found Java files: {java_files}")

        detected_version = await service._detect_java_version_from_repo(mock_repo)
        print(f"✅ Detected Java Version: {detected_version}")

        if detected_version == "1.0":
            print("✅ SUCCESS: Correctly detected Java 1.0!")
        else:
            print(f"❌ FAILED: Expected Java 1.0, got {detected_version}")

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_simple())
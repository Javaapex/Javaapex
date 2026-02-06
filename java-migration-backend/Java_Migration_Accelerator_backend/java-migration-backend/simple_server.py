#!/usr/bin/env python3
"""
Simple mock server to handle the GitHub analyze-url endpoint
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import urllib.parse

class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/github/analyze-url'):
            # Parse the query parameters
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)

            repo_url = query_params.get('repo_url', [''])[0]
            token = query_params.get('token', [''])[0]

            # Extract owner and repo from URL
            if 'github.com/' in repo_url:
                url_parts = repo_url.split('github.com/')[1].split('/')
                owner = url_parts[0] if len(url_parts) > 0 else 'unknown'
                repo = url_parts[1].replace('.git', '') if len(url_parts) > 1 else 'unknown'
            else:
                owner = 'unknown'
                repo = 'unknown'

            # Mock response with dynamic repo info
            response = {
                "repo_url": repo_url,
                "owner": owner,
                "repo": repo,
                "analysis": {
                    "language": "Java",
                    "java_version": "8",
                    "dependencies": [
                        {"group_id": "junit", "artifact_id": "junit", "version": "4.12"},
                        {"group_id": "org.springframework", "artifact_id": "spring-core", "version": "4.3.0.RELEASE"}
                    ],
                    "files": [
                        {"path": "src/main/java", "type": "directory"},
                        {"path": "src/test/java", "type": "directory"},
                        {"path": "pom.xml", "type": "file"}
                    ],
                    "structure": "Maven project",
                    "build_tool": "Maven",
                    "has_tests": True,
                    "total_files": 45,
                    "java_files": 32
                }
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        elif self.path.startswith('/api/github/list-files'):
            # Mock file listing response with comprehensive file structure
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)
            repo_url = query_params.get('repo_url', [''])[0]
            current_path = query_params.get('path', [''])[0]

            # Extract owner and repo from URL
            if 'github.com/' in repo_url:
                url_parts = repo_url.split('github.com/')[1].split('/')
                owner = url_parts[0] if len(url_parts) > 0 else 'unknown'
                repo = url_parts[1].replace('.git', '') if len(url_parts) > 1 else 'unknown'
            else:
                owner = 'unknown'
                repo = 'unknown'

            # Generate realistic file structures based on repository URL patterns and actual GitHub-like structures
            # Extract repository name and owner for pattern matching
            repo_key = repo_url.replace('https://github.com/', '').replace('http://github.com/', '').replace('.git', '').lower()
            repo_parts = repo_key.split('/')
            repo_name = repo_parts[1] if len(repo_parts) > 1 else 'unknown'

            # Pattern-based repository structure generation
            def generate_realistic_structure(repo_name, repo_key):
                """Generate a realistic file structure based on repository name patterns"""

                structures = {}

                # Common root files for any Java project
                root_files = [
                    {"name": ".gitignore", "type": "file", "path": ".gitignore", "size": 256},
                    {"name": "README.md", "type": "file", "path": "README.md", "size": 1024},
                    {"name": "LICENSE", "type": "file", "path": "LICENSE", "size": 512}
                ]

                # Build tool detection and src structure
                if any(word in repo_name.lower() for word in ['gradle', 'android', 'kotlin']):
                    # Gradle project
                    root_files.extend([
                        {"name": "build.gradle", "type": "file", "path": "build.gradle", "size": 2048},
                        {"name": "settings.gradle", "type": "file", "path": "settings.gradle", "size": 256},
                        {"name": "gradle", "type": "dir", "path": "gradle", "size": 0},
                        {"name": "gradlew", "type": "file", "path": "gradlew", "size": 8192},
                        {"name": "gradlew.bat", "type": "file", "path": "gradlew.bat", "size": 4096},
                        {"name": "src", "type": "dir", "path": "src", "size": 0}
                    ])
                else:
                    # Maven project (default)
                    root_files.extend([
                        {"name": "pom.xml", "type": "file", "path": "pom.xml", "size": 2048},
                        {"name": ".mvn", "type": "dir", "path": ".mvn", "size": 0},
                        {"name": "mvnw", "type": "file", "path": "mvnw", "size": 8192},
                        {"name": "mvnw.cmd", "type": "file", "path": "mvnw.cmd", "size": 4096},
                        {"name": "src", "type": "dir", "path": "src", "size": 0},
                        {"name": "target", "type": "dir", "path": "target", "size": 0}
                    ])

                structures[""] = root_files

                # Source directory structure
                structures["src"] = [
                    {"name": "main", "type": "dir", "path": "src/main", "size": 0},
                    {"name": "test", "type": "dir", "path": "src/test", "size": 0}
                ]

                structures["src/main"] = [
                    {"name": "java", "type": "dir", "path": "src/main/java", "size": 0},
                    {"name": "resources", "type": "dir", "path": "src/main/resources", "size": 0}
                ]

                # Generate package structure based on repository name patterns
                if 'spring' in repo_name.lower() or 'boot' in repo_name.lower():
                    # Spring Boot structure
                    structures["src/main/java"] = [{"name": "com", "type": "dir", "path": "src/main/java/com", "size": 0}]
                    structures["src/main/java/com"] = [{"name": "example", "type": "dir", "path": "src/main/java/com/example", "size": 0}]
                    structures["src/main/java/com/example"] = [
                        {"name": "Application.java", "type": "file", "path": "src/main/java/com/example/Application.java", "size": 2048},
                        {"name": "controller", "type": "dir", "path": "src/main/java/com/example/controller", "size": 0},
                        {"name": "service", "type": "dir", "path": "src/main/java/com/example/service", "size": 0},
                        {"name": "repository", "type": "dir", "path": "src/main/java/com/example/repository", "size": 0},
                        {"name": "model", "type": "dir", "path": "src/main/java/com/example/model", "size": 0},
                        {"name": "config", "type": "dir", "path": "src/main/java/com/example/config", "size": 0}
                    ]

                    # Controller files
                    structures["src/main/java/com/example/controller"] = [
                        {"name": "UserController.java", "type": "file", "path": "src/main/java/com/example/controller/UserController.java", "size": 1536},
                        {"name": "ProductController.java", "type": "file", "path": "src/main/java/com/example/controller/ProductController.java", "size": 2048},
                        {"name": "OrderController.java", "type": "file", "path": "src/main/java/com/example/controller/OrderController.java", "size": 1792}
                    ]

                    # Service files
                    structures["src/main/java/com/example/service"] = [
                        {"name": "UserService.java", "type": "file", "path": "src/main/java/com/example/service/UserService.java", "size": 2560},
                        {"name": "ProductService.java", "type": "file", "path": "src/main/java/com/example/service/ProductService.java", "size": 3072},
                        {"name": "OrderService.java", "type": "file", "path": "src/main/java/com/example/service/OrderService.java", "size": 2304}
                    ]

                    # Repository files
                    structures["src/main/java/com/example/repository"] = [
                        {"name": "UserRepository.java", "type": "file", "path": "src/main/java/com/example/repository/UserRepository.java", "size": 1024},
                        {"name": "ProductRepository.java", "type": "file", "path": "src/main/java/com/example/repository/ProductRepository.java", "size": 1280},
                        {"name": "OrderRepository.java", "type": "file", "path": "src/main/java/com/example/repository/OrderRepository.java", "size": 896}
                    ]

                    # Model files
                    structures["src/main/java/com/example/model"] = [
                        {"name": "User.java", "type": "file", "path": "src/main/java/com/example/model/User.java", "size": 1024},
                        {"name": "Product.java", "type": "file", "path": "src/main/java/com/example/model/Product.java", "size": 1536},
                        {"name": "Order.java", "type": "file", "path": "src/main/java/com/example/model/Order.java", "size": 2048}
                    ]

                    # Config files
                    structures["src/main/java/com/example/config"] = [
                        {"name": "SecurityConfig.java", "type": "file", "path": "src/main/java/com/example/config/SecurityConfig.java", "size": 1792},
                        {"name": "WebConfig.java", "type": "file", "path": "src/main/java/com/example/config/WebConfig.java", "size": 1024}
                    ]

                elif 'collection' in repo_name.lower() or 'algorithm' in repo_name.lower():
                    # Collections/Algorithms structure
                    structures["src/main/java"] = [{"name": "com", "type": "dir", "path": "src/main/java/com", "size": 0}]
                    structures["src/main/java/com"] = [{"name": "example", "type": "dir", "path": "src/main/java/com/example", "size": 0}]
                    structures["src/main/java/com/example"] = [
                        {"name": "collections", "type": "dir", "path": "src/main/java/com/example/collections", "size": 0},
                        {"name": "algorithms", "type": "dir", "path": "src/main/java/com/example/algorithms", "size": 0}
                    ]

                    # Collections examples
                    structures["src/main/java/com/example/collections"] = [
                        {"name": "ArrayListExample.java", "type": "file", "path": "src/main/java/com/example/collections/ArrayListExample.java", "size": 2048},
                        {"name": "HashMapExample.java", "type": "file", "path": "src/main/java/com/example/collections/HashMapExample.java", "size": 2560},
                        {"name": "LinkedListExample.java", "type": "file", "path": "src/main/java/com/example/collections/LinkedListExample.java", "size": 1536},
                        {"name": "HashSetExample.java", "type": "file", "path": "src/main/java/com/example/collections/HashSetExample.java", "size": 1792},
                        {"name": "TreeMapExample.java", "type": "file", "path": "src/main/java/com/example/collections/TreeMapExample.java", "size": 2304}
                    ]

                    # Algorithms structure
                    structures["src/main/java/com/example/algorithms"] = [
                        {"name": "sorting", "type": "dir", "path": "src/main/java/com/example/algorithms/sorting", "size": 0},
                        {"name": "searching", "type": "dir", "path": "src/main/java/com/example/algorithms/searching", "size": 0},
                        {"name": "math", "type": "dir", "path": "src/main/java/com/example/algorithms/math", "size": 0}
                    ]

                    structures["src/main/java/com/example/algorithms/sorting"] = [
                        {"name": "BubbleSort.java", "type": "file", "path": "src/main/java/com/example/algorithms/sorting/BubbleSort.java", "size": 1024},
                        {"name": "QuickSort.java", "type": "file", "path": "src/main/java/com/example/algorithms/sorting/QuickSort.java", "size": 1536},
                        {"name": "MergeSort.java", "type": "file", "path": "src/main/java/com/example/algorithms/sorting/MergeSort.java", "size": 2048},
                        {"name": "InsertionSort.java", "type": "file", "path": "src/main/java/com/example/algorithms/sorting/InsertionSort.java", "size": 1280}
                    ]

                    structures["src/main/java/com/example/algorithms/searching"] = [
                        {"name": "BinarySearch.java", "type": "file", "path": "src/main/java/com/example/algorithms/searching/BinarySearch.java", "size": 1024},
                        {"name": "LinearSearch.java", "type": "file", "path": "src/main/java/com/example/algorithms/searching/LinearSearch.java", "size": 768},
                        {"name": "InterpolationSearch.java", "type": "file", "path": "src/main/java/com/example/algorithms/searching/InterpolationSearch.java", "size": 1280}
                    ]

                    structures["src/main/java/com/example/algorithms/math"] = [
                        {"name": "Fibonacci.java", "type": "file", "path": "src/main/java/com/example/algorithms/math/Fibonacci.java", "size": 896},
                        {"name": "PrimeNumbers.java", "type": "file", "path": "src/main/java/com/example/algorithms/math/PrimeNumbers.java", "size": 1536},
                        {"name": "Factorial.java", "type": "file", "path": "src/main/java/com/example/algorithms/math/Factorial.java", "size": 768}
                    ]

                elif 'java8' in repo_name.lower() or 'java-8' in repo_name.lower() or 'stream' in repo_name.lower():
                    # Java 8 features structure
                    structures["src/main/java"] = [{"name": "java8", "type": "dir", "path": "src/main/java/java8", "size": 0}]
                    structures["src/main/java/java8"] = [{"name": "examples", "type": "dir", "path": "src/main/java/java8/examples", "size": 0}]
                    structures["src/main/java/java8/examples"] = [
                        {"name": "stream", "type": "dir", "path": "src/main/java/java8/examples/stream", "size": 0},
                        {"name": "lambda", "type": "dir", "path": "src/main/java/java8/examples/lambda", "size": 0},
                        {"name": "optional", "type": "dir", "path": "src/main/java/java8/examples/optional", "size": 0},
                        {"name": "datetime", "type": "dir", "path": "src/main/java/java8/examples/datetime", "size": 0},
                        {"name": "functional", "type": "dir", "path": "src/main/java/java8/examples/functional", "size": 0}
                    ]

                    structures["src/main/java/java8/examples/stream"] = [
                        {"name": "StreamExamples.java", "type": "file", "path": "src/main/java/java8/examples/stream/StreamExamples.java", "size": 3072},
                        {"name": "ParallelStreamExample.java", "type": "file", "path": "src/main/java/java8/examples/stream/ParallelStreamExample.java", "size": 2048},
                        {"name": "StreamOperations.java", "type": "file", "path": "src/main/java/java8/examples/stream/StreamOperations.java", "size": 2560}
                    ]

                    structures["src/main/java/java8/examples/lambda"] = [
                        {"name": "LambdaExamples.java", "type": "file", "path": "src/main/java/java8/examples/lambda/LambdaExamples.java", "size": 2560},
                        {"name": "FunctionalInterfaceExample.java", "type": "file", "path": "src/main/java/java8/examples/lambda/FunctionalInterfaceExample.java", "size": 1536},
                        {"name": "MethodReferenceExample.java", "type": "file", "path": "src/main/java/java8/examples/lambda/MethodReferenceExample.java", "size": 1792}
                    ]

                    structures["src/main/java/java8/examples/optional"] = [
                        {"name": "OptionalExamples.java", "type": "file", "path": "src/main/java/java8/examples/optional/OptionalExamples.java", "size": 2048},
                        {"name": "OptionalBestPractices.java", "type": "file", "path": "src/main/java/java8/examples/optional/OptionalBestPractices.java", "size": 2304}
                    ]

                    structures["src/main/java/java8/examples/datetime"] = [
                        {"name": "LocalDateTimeExamples.java", "type": "file", "path": "src/main/java/java8/examples/datetime/LocalDateTimeExamples.java", "size": 2048},
                        {"name": "ZonedDateTimeExamples.java", "type": "file", "path": "src/main/java/java8/examples/datetime/ZonedDateTimeExamples.java", "size": 1792}
                    ]

                    structures["src/main/java/java8/examples/functional"] = [
                        {"name": "FunctionExamples.java", "type": "file", "path": "src/main/java/java8/examples/functional/FunctionExamples.java", "size": 1536},
                        {"name": "PredicateExamples.java", "type": "file", "path": "src/main/java/java8/examples/functional/PredicateExamples.java", "size": 1280},
                        {"name": "ConsumerExamples.java", "type": "file", "path": "src/main/java/java8/examples/functional/ConsumerExamples.java", "size": 1024}
                    ]

                else:
                    # Generic Java project structure
                    structures["src/main/java"] = [{"name": "com", "type": "dir", "path": "src/main/java/com", "size": 0}]
                    structures["src/main/java/com"] = [{"name": "example", "type": "dir", "path": "src/main/java/com/example", "size": 0}]
                    structures["src/main/java/com/example"] = [
                        {"name": f"{repo_name.replace('-', '').replace('_', '')}", "type": "dir", "path": f"src/main/java/com/example/{repo_name.replace('-', '').replace('_', '')}", "size": 0}
                    ]

                    # Add some generic Java files
                    base_path = f"src/main/java/com/example/{repo_name.replace('-', '').replace('_', '')}"
                    structures[base_path] = [
                        {"name": "Main.java", "type": "file", "path": f"{base_path}/Main.java", "size": 1024},
                        {"name": "Utils.java", "type": "file", "path": f"{base_path}/Utils.java", "size": 1536},
                        {"name": "Constants.java", "type": "file", "path": f"{base_path}/Constants.java", "size": 768}
                    ]

                # Resources
                structures["src/main/resources"] = [
                    {"name": "application.properties", "type": "file", "path": "src/main/resources/application.properties", "size": 256},
                    {"name": "application.yml", "type": "file", "path": "src/main/resources/application.yml", "size": 512},
                    {"name": "logback-spring.xml", "type": "file", "path": "src/main/resources/logback-spring.xml", "size": 1024}
                ]

                # Test structure
                structures["src/test"] = [{"name": "java", "type": "dir", "path": "src/test/java", "size": 0}]
                structures["src/test/java"] = [{"name": "com", "type": "dir", "path": "src/test/java/com", "size": 0}]
                structures["src/test/java/com"] = [{"name": "example", "type": "dir", "path": "src/test/java/com/example", "size": 0}]

                # Add test files based on main structure
                test_files = []
                for path_key in structures:
                    if path_key.startswith("src/main/java/") and not path_key.endswith("/"):
                        if structures[path_key]:
                            for file_info in structures[path_key]:
                                if file_info["type"] == "file" and file_info["name"].endswith(".java"):
                                    test_path = path_key.replace("src/main/java/", "src/test/java/")
                                    test_file = file_info["name"].replace(".java", "Test.java")
                                    test_files.append({
                                        "name": test_file,
                                        "type": "file",
                                        "path": f"{test_path}/{test_file}",
                                        "size": max(512, file_info["size"] // 4)
                                    })

                if test_files:
                    structures["src/test/java/com/example"] = test_files[:5]  # Limit to 5 test files

                # Add build tool specific directories
                if any(word in repo_name.lower() for word in ['gradle', 'android', 'kotlin']):
                    structures["gradle"] = [
                        {"name": "wrapper", "type": "dir", "path": "gradle/wrapper", "size": 0}
                    ]
                    structures["gradle/wrapper"] = [
                        {"name": "gradle-wrapper.properties", "type": "file", "path": "gradle/wrapper/gradle-wrapper.properties", "size": 256},
                        {"name": "gradle-wrapper.jar", "type": "file", "path": "gradle/wrapper/gradle-wrapper.jar", "size": 65536}
                    ]
                else:
                    structures[".mvn"] = [
                        {"name": "wrapper", "type": "dir", "path": ".mvn/wrapper", "size": 0}
                    ]
                    structures[".mvn/wrapper"] = [
                        {"name": "maven-wrapper.properties", "type": "file", "path": ".mvn/wrapper/maven-wrapper.properties", "size": 256},
                        {"name": "maven-wrapper.jar", "type": "file", "path": ".mvn/wrapper/maven-wrapper.jar", "size": 65536}
                    ]

                return structures

            # Generate structure based on repository name
            file_structures = generate_realistic_structure(repo_name, repo_key)

            # Default Spring Boot structure for unknown repos
            default_structure = {
                "": [
                    {"name": ".github", "type": "dir", "path": ".github", "size": 0},
                    {"name": ".gitignore", "type": "file", "path": ".gitignore", "size": 256},
                    {"name": "src", "type": "dir", "path": "src", "size": 0},
                    {"name": "target", "type": "dir", "path": "target", "size": 0},
                    {"name": "pom.xml", "type": "file", "path": "pom.xml", "size": 2048},
                    {"name": "README.md", "type": "file", "path": "README.md", "size": 1024},
                    {"name": "LICENSE", "type": "file", "path": "LICENSE", "size": 512},
                    {"name": ".mvn", "type": "dir", "path": ".mvn", "size": 0},
                    {"name": "mvnw", "type": "file", "path": "mvnw", "size": 8192},
                    {"name": "mvnw.cmd", "type": "file", "path": "mvnw.cmd", "size": 4096}
                ],
                ".github": [
                    {"name": "workflows", "type": "dir", "path": ".github/workflows", "size": 0}
                ],
                ".github/workflows": [
                    {"name": "ci.yml", "type": "file", "path": ".github/workflows/ci.yml", "size": 1024},
                    {"name": "build.yml", "type": "file", "path": ".github/workflows/build.yml", "size": 512}
                ],
                "src": [
                    {"name": "main", "type": "dir", "path": "src/main", "size": 0},
                    {"name": "test", "type": "dir", "path": "src/test", "size": 0}
                ],
                "src/main": [
                    {"name": "java", "type": "dir", "path": "src/main/java", "size": 0},
                    {"name": "resources", "type": "dir", "path": "src/main/resources", "size": 0}
                ],
                "src/main/java": [
                    {"name": "com", "type": "dir", "path": "src/main/java/com", "size": 0},
                    {"name": "org", "type": "dir", "path": "src/main/java/org", "size": 0}
                ],
                "src/main/java/com": [
                    {"name": "example", "type": "dir", "path": "src/main/java/com/example", "size": 0}
                ],
                "src/main/java/com/example": [
                    {"name": "Application.java", "type": "file", "path": "src/main/java/com/example/Application.java", "size": 2048},
                    {"name": "controller", "type": "dir", "path": "src/main/java/com/example/controller", "size": 0},
                    {"name": "service", "type": "dir", "path": "src/main/java/com/example/service", "size": 0},
                    {"name": "model", "type": "dir", "path": "src/main/java/com/example/model", "size": 0},
                    {"name": "repository", "type": "dir", "path": "src/main/java/com/example/repository", "size": 0}
                ],
                "src/main/java/com/example/controller": [
                    {"name": "UserController.java", "type": "file", "path": "src/main/java/com/example/controller/UserController.java", "size": 1536},
                    {"name": "ProductController.java", "type": "file", "path": "src/main/java/com/example/controller/ProductController.java", "size": 1024}
                ],
                "src/main/java/com/example/service": [
                    {"name": "UserService.java", "type": "file", "path": "src/main/java/com/example/service/UserService.java", "size": 2048},
                    {"name": "ProductService.java", "type": "file", "path": "src/main/java/com/example/service/ProductService.java", "size": 1536}
                ],
                "src/main/java/com/example/model": [
                    {"name": "User.java", "type": "file", "path": "src/main/java/com/example/model/User.java", "size": 1024},
                    {"name": "Product.java", "type": "file", "path": "src/main/java/com/example/model/Product.java", "size": 768}
                ],
                "src/main/java/com/example/repository": [
                    {"name": "UserRepository.java", "type": "file", "path": "src/main/java/com/example/repository/UserRepository.java", "size": 512},
                    {"name": "ProductRepository.java", "type": "file", "path": "src/main/java/com/example/repository/ProductRepository.java", "size": 512}
                ],
                "src/main/resources": [
                    {"name": "application.properties", "type": "file", "path": "src/main/resources/application.properties", "size": 256},
                    {"name": "application.yml", "type": "file", "path": "src/main/resources/application.yml", "size": 512},
                    {"name": "logback-spring.xml", "type": "file", "path": "src/main/resources/logback-spring.xml", "size": 1024}
                ],
                "src/test": [
                    {"name": "java", "type": "dir", "path": "src/test/java", "size": 0}
                ],
                "src/test/java": [
                    {"name": "com", "type": "dir", "path": "src/test/java/com", "size": 0}
                ],
                "src/test/java/com": [
                    {"name": "example", "type": "dir", "path": "src/test/java/com/example", "size": 0}
                ],
                "src/test/java/com/example": [
                    {"name": "ApplicationTests.java", "type": "file", "path": "src/test/java/com/example/ApplicationTests.java", "size": 512},
                    {"name": "controller", "type": "dir", "path": "src/test/java/com/example/controller", "size": 0},
                    {"name": "service", "type": "dir", "path": "src/test/java/com/example/service", "size": 0}
                ],
                "src/test/java/com/example/controller": [
                    {"name": "UserControllerTest.java", "type": "file", "path": "src/test/java/com/example/controller/UserControllerTest.java", "size": 1024},
                    {"name": "ProductControllerTest.java", "type": "file", "path": "src/test/java/com/example/controller/ProductControllerTest.java", "size": 768}
                ],
                "src/test/java/com/example/service": [
                    {"name": "UserServiceTest.java", "type": "file", "path": "src/test/java/com/example/service/UserServiceTest.java", "size": 1024},
                    {"name": "ProductServiceTest.java", "type": "file", "path": "src/test/java/com/example/service/ProductServiceTest.java", "size": 896}
                ],
                ".mvn": [
                    {"name": "wrapper", "type": "dir", "path": ".mvn/wrapper", "size": 0}
                ],
                ".mvn/wrapper": [
                    {"name": "maven-wrapper.properties", "type": "file", "path": ".mvn/wrapper/maven-wrapper.properties", "size": 256},
                    {"name": "maven-wrapper.jar", "type": "file", "path": ".mvn/wrapper/maven-wrapper.jar", "size": 65536}
                ]
            }

            # Get the appropriate structure for this repository
            file_structures = repo_structures.get(repo_key, default_structure)

            # Get files for the current path, default to root if path not found
            files = file_structures.get(current_path, file_structures[""])

            response = {
                "repo_url": repo_url,
                "owner": owner,
                "repo": repo,
                "path": current_path,
                "files": files
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        elif self.path.startswith('/api/migration/'):
            # Handle migration status requests like /api/migration/mock-job-12345
            job_id = self.path.split('/')[-1]
            if job_id == 'mock-job-12345':
                response = {
                    "job_id": "mock-job-12345",
                    "status": "completed",
                    "source_repo": "https://github.com/rmuller/java8-examples.git",
                    "target_repo": "https://github.com/user/migrated-java8-examples",
                    "source_java_version": "8",
                    "target_java_version": "18",
                    "conversion_types": ["java_version"],
                    "started_at": "2024-01-07T12:55:00Z",
                    "completed_at": "2024-01-07T12:56:00Z",
                    "progress_percent": 100,
                    "current_step": "Migration completed successfully!",
                    "dependencies": [
                        {"group_id": "junit", "artifact_id": "junit", "current_version": "4.12", "new_version": "5.9.2", "status": "upgraded"},
                        {"group_id": "org.springframework", "artifact_id": "spring-core", "current_version": "4.3.0.RELEASE", "new_version": "6.0.0", "status": "upgraded"}
                    ],
                    "files_modified": 15,
                    "issues_fixed": 8,
                    "api_endpoints_validated": 0,
                    "api_endpoints_working": 0,
                    "sonar_quality_gate": "PASSED",
                    "sonar_bugs": 0,
                    "sonar_vulnerabilities": 0,
                    "sonar_code_smells": 2,
                    "sonar_coverage": 85.5,
                    "error_message": None,
                    "migration_log": [
                        "Migration started",
                        "Analyzed project structure",
                        "Upgraded Java version from 8 to 18",
                        "Updated dependencies",
                        "Fixed deprecated API calls",
                        "Migration completed successfully!"
                    ],
                    "issues": [],
                    "total_errors": 0,
                    "total_warnings": 2,
                    "errors_fixed": 0,
                    "warnings_fixed": 2
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(404)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"detail": "Migration job not found"}).encode())
        elif self.path == '/api/java-versions':
            response = {
                "source_versions": [
                    {"value": "7", "label": "Java 7"},
                    {"value": "8", "label": "Java 8 (LTS)"},
                    {"value": "9", "label": "Java 9"},
                    {"value": "10", "label": "Java 10"},
                    {"value": "11", "label": "Java 11 (LTS)"},
                    {"value": "12", "label": "Java 12"},
                    {"value": "13", "label": "Java 13"},
                    {"value": "14", "label": "Java 14"},
                    {"value": "15", "label": "Java 15"},
                    {"value": "16", "label": "Java 16"},
                    {"value": "17", "label": "Java 17 (LTS)"},
                    {"value": "18", "label": "Java 18"},
                    {"value": "19", "label": "Java 19"},
                    {"value": "20", "label": "Java 20"},
                    {"value": "21", "label": "Java 21 (LTS)"},
                    {"value": "22", "label": "Java 22"},
                    {"value": "23", "label": "Java 23"}
                ],
                "target_versions": [
                    {"value": "7", "label": "Java 7"},
                    {"value": "8", "label": "Java 8 (LTS)"},
                    {"value": "9", "label": "Java 9"},
                    {"value": "10", "label": "Java 10"},
                    {"value": "11", "label": "Java 11 (LTS)"},
                    {"value": "12", "label": "Java 12"},
                    {"value": "13", "label": "Java 13"},
                    {"value": "14", "label": "Java 14"},
                    {"value": "15", "label": "Java 15"},
                    {"value": "16", "label": "Java 16"},
                    {"value": "17", "label": "Java 17 (LTS)"},
                    {"value": "18", "label": "Java 18"},
                    {"value": "19", "label": "Java 19"},
                    {"value": "20", "label": "Java 20"},
                    {"value": "21", "label": "Java 21 (LTS)"},
                    {"value": "22", "label": "Java 22"},
                    {"value": "23", "label": "Java 23"}
                ]
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/api/conversion-types':
            response = [
                {
                    "id": "java_version",
                    "name": "Java Version Upgrade",
                    "description": "Upgrade Java version (e.g., Java 8 → Java 17)",
                    "category": "Language",
                    "icon": "☕"
                },
                {
                    "id": "maven_to_gradle",
                    "name": "Maven → Gradle",
                    "description": "Convert Maven (pom.xml) to Gradle (build.gradle)",
                    "category": "Build Tool",
                    "icon": "🔧"
                },
                {
                    "id": "gradle_to_maven",
                    "name": "Gradle → Maven",
                    "description": "Convert Gradle (build.gradle) to Maven (pom.xml)",
                    "category": "Build Tool",
                    "icon": "🔧"
                },
                {
                    "id": "javax_to_jakarta",
                    "name": "javax → Jakarta EE",
                    "description": "Migrate javax.* packages to jakarta.* (EE 8 → EE 9+)",
                    "category": "Framework",
                    "icon": "📦"
                },
                {
                    "id": "jakarta_to_javax",
                    "name": "Jakarta EE → javax",
                    "description": "Migrate jakarta.* packages back to javax.*",
                    "category": "Framework",
                    "icon": "📦"
                },
                {
                    "id": "spring_boot_2_to_3",
                    "name": "Spring Boot 2 → 3",
                    "description": "Upgrade Spring Boot 2.x to 3.x with Jakarta EE",
                    "category": "Framework",
                    "icon": "🌱"
                },
                {
                    "id": "junit_4_to_5",
                    "name": "JUnit 4 → JUnit 5",
                    "description": "Migrate JUnit 4 tests to JUnit 5 (Jupiter)",
                    "category": "Testing",
                    "icon": "✅"
                },
                {
                    "id": "log4j_to_slf4j",
                    "name": "Log4j → SLF4J",
                    "description": "Migrate Log4j to SLF4J logging facade",
                    "category": "Logging",
                    "icon": "📝"
                }
            ]

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "Not Found"}).encode())

    def do_POST(self):
        if self.path == '/api/migration/start':
            # Read the POST data
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode('utf-8'))

            # Mock migration response
            response = {
                "job_id": "mock-job-12345",
                "status": "pending",
                "source_repo": request_data.get('source_repo_url', ''),
                "target_repo": None,
                "source_java_version": request_data.get('source_java_version', '7'),
                "target_java_version": request_data.get('target_java_version', '18'),
                "conversion_types": request_data.get('conversion_types', []),
                "started_at": "2024-01-07T12:55:00Z",
                "progress_percent": 0,
                "current_step": "Initializing migration...",
                "dependencies": [],
                "files_modified": 0,
                "issues_fixed": 0,
                "api_endpoints_validated": 0,
                "api_endpoints_working": 0,
                "sonar_quality_gate": None,
                "sonar_bugs": 0,
                "sonar_vulnerabilities": 0,
                "sonar_code_smells": 0,
                "sonar_coverage": 0.0,
                "error_message": None,
                "migration_log": ["Mock migration started"],
                "issues": [],
                "total_errors": 0,
                "total_warnings": 0,
                "errors_fixed": 0,
                "warnings_fixed": 0
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "Not Found"}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, MockHandler)
    print("Mock server running on port 8000...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()

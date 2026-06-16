# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Microservice eligibility assessment (called during analyze-url)
# Extracted so it runs automatically during repository analysis — no separate button.
# DETERMINISTIC 100-point scoring system with detailed evaluation criteria.
# ═══════════════════════════════════════════════════════════════════════════════
async def _assess_microservice_eligibility(owner: str, repo: str, analysis: dict) -> dict:
    """
    Comprehensive microservice eligibility assessment with deterministic scoring.
    Returns detailed evaluation criteria, benefits, risks, and recommendations.
    
    Score Ranges:
    - 70-100%: ELIGIBLE (Recommended) - Show benefits + risks of NOT converting
    - 51-69%: INTERMEDIATE (Partial) - Show key changes needed to become eligible
    - 0-50%: NOT RECOMMENDED - Show why not recommended + what would need to change
    """
    all_files = analysis.get("all_files", [])
    dependencies = analysis.get("dependencies", [])
    detected_frameworks = analysis.get("detected_frameworks", [])
    java_version = analysis.get("java_version") or analysis.get("java_version_from_build") or "unknown"
    build_tool = analysis.get("build_tool", "unknown")

    # Canonical criteria definitions (requested business rules)
    # Option 1: with DB coupling
    # Option 2: without DB coupling
    CRITERIA_DEFINITIONS = {
        "Database Coupling Detection": {
            "option_1_weight": 25,
            "description": "Process of identifying how strongly multiple modules or domains in an application depend on the same database structures (such as shared tables, schemas, or queries), to assess whether the data layer can be independently split for microservices.",
        },
        "Coupling & Dependency Analysis": {
            "option_1_weight": 25,
            "option_2_weight": 50,
            "description": "Examining how strongly different parts of a system (classes, modules, or services) depend on each other, in order to determine how easily they can be separated or independently deployed.",
        },
        "Transaction & State Complexity": {
            "option_1_weight": 25,
            "option_2_weight": 30,
            "description": "Measure of how much an application relies on multi-module transactions and shared or in-memory state, which can make it difficult to split into independent services.",
        },
        "Code Structure & Modularity": {
            "option_1_weight": 25,
            "option_2_weight": 20,
            "description": "The degree to which an application’s codebase is organized into clear, logical components with well-defined responsibilities, enabling easier understanding, maintenance, and isolation of functionality for potential extraction into independent services.",
        },
    }

    def _criterion_meta(name: str, has_db: bool) -> tuple[int, str]:
        definition = CRITERIA_DEFINITIONS.get(name, {})
        weight = (
            definition.get("option_1_weight")
            if has_db
            else definition.get("option_2_weight", definition.get("option_1_weight", 0))
        )
        return int(weight or 0), str(definition.get("description", "")).strip()

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 1: Extract code structure metrics with IMPROVED DETECTION
    # Uses regex patterns to detect actual annotations (not imports/comments/strings)
    # ═══════════════════════════════════════════════════════════════════════════════
    import re
    
    java_files = []
    controllers = []
    services_files = []
    repositories = []
    entities = []
    configs = []
    dtos = []
    utils = []
    tests = []
    
    # Track domain patterns for domain separation detection
    domain_patterns = set()  # e.g., "user", "order", "payment", "inventory"
    
    # Regex patterns for detecting actual class-level annotations
    # These patterns match annotations at start of line (with optional whitespace)
    # and NOT in comments, imports, or string literals
    annotation_patterns = {
        "controller": re.compile(r'^\s*@(Rest)?Controller\b', re.MULTILINE),
        "service": re.compile(r'^\s*@Service\b', re.MULTILINE),
        "repository": re.compile(r'^\s*@Repository\b', re.MULTILINE),
        "entity": re.compile(r'^\s*@Entity\b', re.MULTILINE),
        "component": re.compile(r'^\s*@Component\b', re.MULTILINE),
        "configuration": re.compile(r'^\s*@Configuration\b', re.MULTILINE),
    }
    
    # Track annotation-based detection (more accurate than filename-based)
    annotation_detected_controllers = []
    annotation_detected_services = []
    annotation_detected_repositories = []
    annotation_detected_entities = []
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 1: Scan all files and detect components
    # Domain extraction is DEFERRED until we know which components exist
    # ═══════════════════════════════════════════════════════════════════════════════
    for f in all_files:
        fname = f.get("path", f.get("name", "")) if isinstance(f, dict) else str(f)
        fname_lower = fname.lower()
        if fname_lower.endswith(".java"):
            java_files.append(fname)
            base = fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace(".java", "")
            base_lower = base.lower()
            
            # NOTE: We NO LONGER extract domains from path segments here
            # Domains will be extracted ONLY from actual detected components (Phase 2)
            # This ensures deterministic domain count based on real components
            
            # FILENAME-BASED detection (as fallback)
            # IMPORTANT: Check "config" BEFORE "controller" to avoid misclassifying
            # classes like "HelloControllerConfig" as controllers (they are configs)
            if "test" in base_lower:
                tests.append(base)
            elif "config" in base_lower or "configuration" in base_lower:
                configs.append(base)
            elif "controller" in base_lower:
                controllers.append(base)
                # Domain extraction moved to Phase 2
            elif "service" in base_lower and "test" not in base_lower:
                services_files.append(base)
                # Domain extraction moved to Phase 2
            elif "repository" in base_lower or "dao" in base_lower:
                repositories.append(base)
            elif any(kw in fname_lower for kw in ["entity", "model", "domain"]) and "test" not in fname_lower:
                # Only add to entities if filename suggests it's an entity
                # BUT we'll verify with annotation check below
                pass  # Don't add by filename alone - wait for annotation check
            elif "dto" in base_lower or "request" in base_lower or "response" in base_lower:
                dtos.append(base)
            elif "util" in base_lower or "helper" in base_lower or "common" in base_lower:
                utils.append(base)
            elif "test" in base_lower:
                tests.append(base)
            
            # ANNOTATION-BASED detection (more accurate) - check file content if available
            file_content = f.get("content", "") if isinstance(f, dict) else ""
            if file_content:
                # Remove comments and string literals to avoid false positives
                # Simple approach: check if annotation appears at start of a line
                if annotation_patterns["controller"].search(file_content):
                    if base not in annotation_detected_controllers:
                        annotation_detected_controllers.append(base)
                if annotation_patterns["service"].search(file_content):
                    if base not in annotation_detected_services:
                        annotation_detected_services.append(base)
                if annotation_patterns["repository"].search(file_content):
                    if base not in annotation_detected_repositories:
                        annotation_detected_repositories.append(base)
                if annotation_patterns["entity"].search(file_content):
                    if base not in annotation_detected_entities:
                        annotation_detected_entities.append(base)
    
    # MERGE detection results - prefer annotation-based if available, else use filename-based
    # For entities specifically, ONLY use annotation-based detection to avoid false positives
    if annotation_detected_controllers:
        controllers = list(set(controllers + annotation_detected_controllers))
    if annotation_detected_services:
        services_files = list(set(services_files + annotation_detected_services))
    if annotation_detected_repositories:
        repositories = list(set(repositories + annotation_detected_repositories))
    
    # ── Build file content map for dynamic scoring (class_name → content) ──
    file_content_map = {}
    for f in all_files:
        if isinstance(f, dict):
            fname = f.get("path", f.get("name", ""))
            if fname.lower().endswith(".java") and f.get("content"):
                base = fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace(".java", "")
                file_content_map[base] = f["content"]
    
    # ENTITIES: Only count if @Entity annotation was found (not just filename pattern)
    # This fixes the false positive issue where DTOs/models were counted as entities
    if annotation_detected_entities:
        entities = annotation_detected_entities  # Use ONLY annotation-based detection
    else:
        # If no content was available for scanning, keep empty unless filename clearly indicates entity
        # AND there's evidence of JPA/Hibernate in dependencies
        has_jpa_dependency = any(
            kw in str(d.get("artifact_id", "")).lower()
            for d in dependencies
            for kw in ["jpa", "hibernate", "spring-data-jpa"]
        )
        if not has_jpa_dependency:
            entities = []  # No JPA = no real entities
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 2: Extract domains ONLY from actual detected components
    # This ensures domain count is deterministic and based on real components
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def extract_domain_from_component(component_name: str) -> str:
        """Extract domain name from component class name (e.g., UserController -> user)"""
        name = component_name.lower()
        # Remove common suffixes
        for suffix in ["controller", "restcontroller", "service", "serviceimpl", "repository", "dao", "entity"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        # Remove common prefixes
        for prefix in ["rest", "api", "impl"]:
            if name.startswith(prefix) and len(name) > len(prefix):
                name = name[len(prefix):]
        return name.strip() if len(name) >= 2 else ""
    
    # Extract domains from actual controllers
    for ctrl in controllers:
        domain = extract_domain_from_component(ctrl)
        if domain:
            domain_patterns.add(domain)
    
    # Extract domains from actual services
    for svc in services_files:
        domain = extract_domain_from_component(svc)
        if domain:
            domain_patterns.add(domain)
    
    # Extract domains from actual repositories
    for repo in repositories:
        domain = extract_domain_from_component(repo)
        if domain:
            domain_patterns.add(domain)
    
    # Extract domains from actual entities
    for ent in entities:
        domain = extract_domain_from_component(ent)
        if domain:
            domain_patterns.add(domain)
    
    # Sort domains for deterministic ordering
    domain_patterns = set(sorted(domain_patterns))
    
    print(f"[MICROSERVICE] Detection results:")
    print(f"  - Controllers: {len(controllers)} (filename: {len(controllers) - len(annotation_detected_controllers)}, annotation: {len(annotation_detected_controllers)})")
    print(f"  - Services: {len(services_files)} (filename: {len(services_files) - len(annotation_detected_services)}, annotation: {len(annotation_detected_services)})")
    print(f"  - Repositories: {len(repositories)} (filename: {len(repositories) - len(annotation_detected_repositories)}, annotation: {len(annotation_detected_repositories)})")
    print(f"  - Entities: {len(entities)} (annotation-only to avoid false positives)")
    print(f"  - Domains (from components): {len(domain_patterns)} ({list(domain_patterns)[:5]})")

    # Detect technology patterns
    has_spring_boot = any("spring-boot" in str(d.get("artifact_id", "")).lower() for d in dependencies)
    has_spring_web = any("spring-web" in str(d.get("artifact_id", "")).lower() for d in dependencies)
    has_spring_data = any("spring-data" in str(d.get("artifact_id", "")).lower() for d in dependencies)
    has_spring_cloud = any("spring-cloud" in str(d.get("artifact_id", "")).lower() for d in dependencies)
    has_rest_api = len(controllers) > 0
    has_database = has_spring_data or any(
        kw in str(d.get("artifact_id", "")).lower()
        for d in dependencies
        for kw in ["jdbc", "jpa", "hibernate", "mybatis", "h2", "mysql", "postgres", "oracle", "mongodb"]
    )
    has_messaging = any(
        kw in str(d.get("artifact_id", "")).lower()
        for d in dependencies
        for kw in ["kafka", "rabbitmq", "jms", "activemq", "amqp"]
    )
    has_caching = any(
        kw in str(d.get("artifact_id", "")).lower()
        for d in dependencies
        for kw in ["redis", "cache", "ehcache", "hazelcast"]
    )

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 2: Calculate scores for each evaluation criteria (100 points total)
    # 
    # OPTION 1 (WITH Database): 4 Criteria × 25% each = 100%
    #   1. Database Coupling Detection (25%)
    #   2. Coupling & Dependency Analysis (25%)
    #   3. Transaction & State Complexity (25%)
    #   4. Code Structure & Modularity (25%)
    #
    # OPTION 2 (WITHOUT Database): 3 Criteria = 100%
    #   1. Coupling & Dependency Analysis (50%)
    #   2. Transaction & State Complexity (30%)
    #   3. Code Structure & Modularity (20%)
    # ═══════════════════════════════════════════════════════════════════════════════
    evaluation_criteria = []
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # DETERMINE DATABASE LAYER - STRICT DETECTION
    # ═══════════════════════════════════════════════════════════════════════════════
    # A "real" database layer requires:
    # 1. Repository classes (actual data access) - @Repository annotation OR
    # 2. Multiple entities with JPA/Hibernate dependency
    # 3. Single entity without repository = likely a DTO/model, NOT a real DB layer
    
    has_repository_classes = len(repositories) > 0
    has_multiple_entities = len(entities) >= 2
    has_jpa_or_hibernate = any(
        kw in str(d.get("artifact_id", "")).lower()
        for d in dependencies
        for kw in ["jpa", "hibernate", "spring-data-jpa", "spring-data-jdbc"]
    )
    
    # STRICT database layer check:
    # Option 1 (With DB) ONLY if:
    # - Has @Repository classes, OR
    # - Has multiple @Entity classes AND JPA/Hibernate dependency
    # Single entity alone is NOT enough (could be a DTO)
    has_database_layer = has_repository_classes or (has_multiple_entities and has_jpa_or_hibernate)
    
    criteria_option = "OPTION_1_WITH_DATABASE" if has_database_layer else "OPTION_2_WITHOUT_DATABASE"
    
    print(f"[MICROSERVICE] Database layer detection:")
    print(f"  - Repositories: {len(repositories)} (has_repository_classes={has_repository_classes})")
    print(f"  - Entities: {len(entities)} (has_multiple_entities={has_multiple_entities})")
    print(f"  - JPA/Hibernate dependency: {has_jpa_or_hibernate}")
    print(f"  - FINAL: has_database_layer={has_database_layer}")
    print(f"[MICROSERVICE] Using {criteria_option}")
    
    # ══════════════════════════════════════════════════════════════════════════════
    # CRITERIA 1: Database Coupling Detection - ONLY FOR OPTION 1 (WITH Database)
    # Option 2 does NOT have this criterion - it starts with Domain Separation
    # ══════════════════════════════════════════════════════════════════════════════
    
    if has_database_layer:
        # ── OPTION 1 - CRITERIA 1: Database Coupling Detection (25% / 25 points) ──
        # Process of identifying how strongly multiple modules or domains in an application
        # depend on the same database structures (tables, schemas, or stored procedures),
        # to assess whether the data layer can be independently split for microservices.
        db_coupling_max = 25
        db_coupling_score = 0
        db_coupling_justification = ""
        
        # Dynamic: count actual entity relationships and native queries from file content
        total_entity_rels = sum(
            content.count("@ManyToOne") + content.count("@OneToMany") + content.count("@ManyToMany") + content.count("@OneToOne")
            for content in file_content_map.values()
        )
        total_native_queries = sum(
            content.count("nativeQuery") + content.count("JdbcTemplate") + content.count("@Query")
            for content in file_content_map.values()
        )
        total_shared_tables = sum(
            content.count("@JoinTable") + content.count("@JoinColumn")
            for content in file_content_map.values()
        )
        
        # Score based on actual relationship density
        rel_density = total_entity_rels + (total_native_queries * 0.5) + (total_shared_tables * 0.5)
        
        if rel_density == 0 and len(repositories) >= 2:
            db_coupling_score = round(db_coupling_max * 0.90)
            db_coupling_justification = f"Clean data boundaries: {len(repositories)} repositories, {len(entities)} entities, 0 cross-entity relationships, 0 native queries — each domain can own its data store."
        elif rel_density <= 3 and len(repositories) >= 2:
            db_coupling_score = round(db_coupling_max * 0.75)
            db_coupling_justification = f"{len(repositories)} repositories, {len(entities)} entities with {total_entity_rels} JPA relationships and {total_native_queries} queries — manageable data coupling for separation."
        elif rel_density <= 8:
            db_coupling_score = round(db_coupling_max * 0.55)
            db_coupling_justification = f"Moderate DB coupling: {total_entity_rels} entity relationships, {total_native_queries} queries, {total_shared_tables} join tables — requires schema refactoring for database-per-service."
        elif rel_density <= 15:
            db_coupling_score = round(db_coupling_max * 0.35)
            db_coupling_justification = f"Significant DB coupling: {total_entity_rels} entity relationships + {total_native_queries} native queries — shared tables across domains complicate splitting."
        else:
            db_coupling_score = round(db_coupling_max * 0.15)
            db_coupling_justification = f"Heavy DB coupling: {total_entity_rels} entity relationships, {total_native_queries} queries, {total_shared_tables} join tables — tightly shared schema, needs major data refactoring."
        
        evaluation_criteria.append({
            "name": "Database Coupling Detection",
            "description": "Process of identifying how strongly multiple modules or domains depend on the same database structures (such as shared tables, schemas, or queries), to assess whether the data layer can be independently split for microservices.",
            "weightage": "25%",
            "score": db_coupling_score,
            "max_score": db_coupling_max,
            "score_percent": round((db_coupling_score / db_coupling_max) * 100),
            "justification": db_coupling_justification
        })
    
    # NOTE: Option 2 (Without Database) does NOT have Database Coupling Detection
    # It starts directly with Coupling & Dependency Analysis at 50% weightage
    
    # ═══ Calculate unique_domains for use in recommendations/justifications ═══
    unique_domains = len(domain_patterns)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # CRITERIA: Coupling & Dependency Analysis
    # - Option 1 (With DB): 25% / 25 points
    # - Option 2 (Without DB): 50% / 50 points
    # ══════════════════════════════════════════════════════════════════════════════
    # Examining how strongly different parts of a system depend on each other
    # (e.g., shared libraries, direct module calls, or APIs)
    coupling_max, coupling_description = _criterion_meta("Coupling & Dependency Analysis", has_database_layer)
    coupling_weightage = "25%" if has_database_layer else "50%"
    coupling_score = 0
    coupling_justification = ""
    
    # Dynamic: analyze actual imports across all Java files
    all_import_lines = []
    all_internal_imports = 0
    all_external_imports = 0
    total_interfaces_found = 0
    total_injection_points = 0
    for comp_name, content in file_content_map.items():
        imp_lines = [l for l in content.split("\n") if l.strip().startswith("import ")]
        all_import_lines.extend(imp_lines)
        total_interfaces_found += len(re.findall(r'\bimplements\s+\w+', content))
        total_injection_points += content.count("@Autowired") + content.count("@Inject")
    
    # Determine coupling from structural signals + actual content
    if has_database_layer:
        has_clear_layers = len(controllers) > 0 and len(services_files) > 0 and len(repositories) > 0
    else:
        has_clear_layers = len(controllers) > 0 and len(services_files) > 0
    has_dtos = len(dtos) > 0
    
    # Dynamic scoring based on actual metrics
    coupling_percent = 0
    coupling_details = []
    if has_clear_layers:
        coupling_percent += 30
        coupling_details.append(f"{len(controllers)}C/{len(services_files)}S/{len(repositories)}R layered")
    if has_dtos:
        coupling_percent += 15
        coupling_details.append(f"{len(dtos)} DTOs")
    if total_interfaces_found >= 3:
        coupling_percent += 20
        coupling_details.append(f"{total_interfaces_found} interfaces")
    elif total_interfaces_found >= 1:
        coupling_percent += 10
        coupling_details.append(f"{total_interfaces_found} interface(s)")
    if total_injection_points >= 5:
        coupling_percent += 15
        coupling_details.append(f"{total_injection_points} DI points")
    if len(services_files) >= len(controllers) and len(services_files) > 0:
        coupling_percent += 10
        coupling_details.append("services≥controllers")
    if len(all_import_lines) > 0:
        # Bonus: if most imports are internal (same base package)
        coupling_percent += 10
        coupling_details.append(f"{len(all_import_lines)} imports analyzed")
    
    coupling_percent = min(coupling_percent, 100)
    coupling_score = round(coupling_max * coupling_percent / 100)
    
    if coupling_percent >= 70:
        coupling_justification = f"Low coupling: {', '.join(coupling_details)}. Well-defined interfaces enable independent deployment."
    elif coupling_percent >= 50:
        coupling_justification = f"Moderate coupling: {', '.join(coupling_details)}. Some shared dependencies but manageable for extraction."
    elif coupling_percent >= 30:
        coupling_justification = f"Significant coupling: {', '.join(coupling_details) if coupling_details else 'limited separation'}. Needs interface extraction before splitting."
    else:
        coupling_justification = f"High coupling detected ({coupling_percent}%): {', '.join(coupling_details) if coupling_details else 'no clear boundaries'}. Requires major restructuring."
    
    evaluation_criteria.append({
        "name": "Coupling & Dependency Analysis",
        "description": "Examining how strongly different parts of a system (classes, modules, or services) depend on each other, in order to determine how easily they can be separated or independently deployed.",
        "weightage": coupling_weightage,
        "description": coupling_description,
        "score": coupling_score,
        "max_score": coupling_max,
        "score_percent": round((coupling_score / coupling_max) * 100),
        "justification": coupling_justification
    })
    
    # ══════════════════════════════════════════════════════════════════════════════
    # CRITERIA: Transaction & State Complexity
    # - Option 1 (With DB): 25% / 25 points
    # - Option 2 (Without DB): 30% / 30 points
    # ══════════════════════════════════════════════════════════════════════════════
    # Measure of how much an application relies on multi-module transactions and shared state
    # (sessions, caches, or in-memory data), which can make it difficult to split into independent services.
    tx_state_max, tx_state_description = _criterion_meta("Transaction & State Complexity", has_database_layer)
    tx_state_weightage = "25%" if has_database_layer else "30%"
    tx_state_score = 0
    tx_state_justification = ""
    
    # Dynamic: count actual transaction/state annotations from file content
    total_tx_annotations = sum(content.count("@Transactional") for content in file_content_map.values())
    total_session_refs = sum(
        content.count("HttpSession") + content.count("@SessionAttribute") + content.count("@SessionScope")
        for content in file_content_map.values()
    )
    total_async_events = sum(
        content.count("@Async") + content.count("@EventListener") + content.count("@KafkaListener") + content.count("@RabbitListener") + content.count("@JmsListener")
        for content in file_content_map.values()
    )
    
    # Also check dependency-level indicators as fallback
    has_tx_mgmt_dep = any(
        kw in str(d.get("artifact_id", "")).lower()
        for d in dependencies
        for kw in ["transaction", "xa", "jta", "atomikos"]
    )
    has_session_dep = any("session" in str(d.get("artifact_id", "")).lower() for d in dependencies)
    
    # Combined: use actual counts + dependency hints
    has_tx_mgmt = total_tx_annotations > 5 or has_tx_mgmt_dep
    has_session_state = total_session_refs > 0 or has_session_dep
    
    if total_async_events >= 2 and total_tx_annotations == 0 and total_session_refs == 0:
        tx_state_score = round(tx_state_max * 0.85)
        tx_state_justification = f"Event-driven architecture: {total_async_events} async/listener annotations, 0 @Transactional, 0 session refs — ideal for eventual consistency."
    elif total_tx_annotations == 0 and total_session_refs == 0:
        tx_state_score = round(tx_state_max * 0.75)
        tx_state_justification = f"Stateless design: 0 @Transactional annotations, 0 session references across {len(file_content_map)} files — no distributed transaction concerns."
    elif total_tx_annotations <= 3 and total_session_refs == 0:
        tx_state_score = round(tx_state_max * 0.60)
        tx_state_justification = f"Light transactional: {total_tx_annotations} @Transactional method(s), no session state — minor saga patterns needed."
    elif total_session_refs >= 1 and total_tx_annotations <= 5:
        tx_state_score = round(tx_state_max * 0.40)
        tx_state_justification = f"{total_session_refs} session reference(s) + {total_tx_annotations} @Transactional — needs distributed cache migration (Redis/Hazelcast)."
    elif total_tx_annotations > 5:
        tx_state_score = round(tx_state_max * 0.25)
        tx_state_justification = f"Heavy transactional: {total_tx_annotations} @Transactional + {total_session_refs} session refs — requires saga/outbox pattern redesign."
    else:
        tx_state_score = round(tx_state_max * 0.30)
        tx_state_justification = f"{total_tx_annotations} @Transactional, {total_session_refs} session refs — moderate state complexity needs attention."
    
    evaluation_criteria.append({
        "name": "Transaction & State Complexity",
        "description": "Measure of how much an application relies on multi-module transactions and shared or in-memory state, which can make it difficult to split into independent services.",
        "weightage": tx_state_weightage,
        "description": tx_state_description,
        "score": tx_state_score,
        "max_score": tx_state_max,
        "score_percent": round((tx_state_score / tx_state_max) * 100),
        "justification": tx_state_justification
    })
    
    # ══════════════════════════════════════════════════════════════════════════════
    # CRITERIA: Code Structure & Modularity
    # - Option 1 (With DB): 25% / 25 points
    # - Option 2 (Without DB): 20% / 20 points
    # ══════════════════════════════════════════════════════════════════════════════
    # The degree to which the codebase is organized into clear, logical components
    # with well-defined responsibilities and interfaces
    modularity_max, modularity_description = _criterion_meta("Code Structure & Modularity", has_database_layer)
    modularity_weightage = "25%" if has_database_layer else "20%"
    modularity_score = 0
    modularity_justification = ""
    
    # Check for multi-module build and structural patterns
    is_multi_module = len([f for f in all_files if "pom.xml" in str(f).lower() or "build.gradle" in str(f).lower()]) > 1
    has_docker = any("dockerfile" in str(f).lower() or "docker-compose" in str(f).lower() for f in all_files)
    has_ci_cd = any(kw in str(f).lower() for f in all_files for kw in ["jenkinsfile", ".github/workflows", ".gitlab-ci", "azure-pipelines"])
    has_config_externalized = any(kw in str(f).lower() for f in all_files for kw in ["application.yml", "application.properties", "config.yml", "bootstrap.yml"])
    
    # Calculate modularity score based on multiple factors (as percentage of max)
    modularity_percent = 0
    modularity_details = []
    
    if is_multi_module:
        modularity_percent += 20
        modularity_details.append("multi-module build structure")
    if has_clear_layers:
        modularity_percent += 20
        modularity_details.append("clear layered architecture")
    if has_dtos:
        modularity_percent += 10
        modularity_details.append("DTOs for data transfer")
    if has_docker:
        modularity_percent += 15
        modularity_details.append("containerization ready")
    if has_ci_cd:
        modularity_percent += 10
        modularity_details.append("CI/CD pipeline exists")
    if has_config_externalized:
        modularity_percent += 10
        modularity_details.append("externalized configuration")
    if has_spring_cloud:
        modularity_percent += 15
        modularity_details.append("cloud-native patterns")
    
    # Cap at 100% and convert to score
    modularity_percent = min(modularity_percent, 100)
    modularity_score = round(modularity_max * modularity_percent / 100)
    
    if modularity_percent >= 70:
        modularity_justification = f"Excellent code structure with {', '.join(modularity_details)}. Well-suited for microservices decomposition."
    elif modularity_percent >= 50:
        modularity_justification = f"Good modularity with {', '.join(modularity_details)}. Some restructuring may be needed."
    elif modularity_percent >= 30:
        modularity_justification = f"Basic modularity detected: {', '.join(modularity_details) if modularity_details else 'limited patterns'}. Needs architectural improvements."
    else:
        modularity_justification = "Limited code modularity. Codebase needs significant restructuring for clear component boundaries and interfaces."
    
    evaluation_criteria.append({
        "name": "Code Structure & Modularity",
        "description": "The degree to which an application's codebase is organized into clear, logical components with well-defined responsibilities, enabling easier understanding, maintenance, and isolation of functionality for potential extraction into independent services.",
        "weightage": modularity_weightage,
        "description": modularity_description,
        "score": modularity_score,
        "max_score": modularity_max,
        "score_percent": round((modularity_score / modularity_max) * 100),
        "justification": modularity_justification
    })
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 3: Calculate total score and determine eligibility level
    # Option 1: 4 criteria × 25 = 100 max (DB Coupling 25 + Coupling 25 + Tx 25 + Modularity 25)
    # Option 2: 3 criteria = 100 max (Coupling 50 + Tx 30 + Modularity 20)
    # ═══════════════════════════════════════════════════════════════════════════════
    total_score = sum(c["score"] for c in evaluation_criteria)
    max_total = sum(c["max_score"] for c in evaluation_criteria)
    score_percent = round((total_score / max_total) * 100) if max_total > 0 else 0
    
    print(f"[MICROSERVICE] Scoring complete:")
    print(f"  - Option: {criteria_option}")
    print(f"  - Criteria count: {len(evaluation_criteria)}")
    print(f"  - Total score: {total_score}/{max_total} = {score_percent}%")
    
    # Determine eligibility level
    if score_percent >= 70:
        eligibility_level = "ELIGIBLE"
        eligibility_label = "Good Candidate"
        eligible = True
        confidence = "high"
    elif score_percent >= 51:
        eligibility_level = "INTERMEDIATE"
        eligibility_label = "Intermediate (Partial)"
        eligible = True  # Partially eligible
        confidence = "medium"
    else:
        eligibility_level = "NOT_RECOMMENDED"
        eligibility_label = "Not Suitable"
        eligible = False
        confidence = "low"
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 4: CHUNK-BASED ANALYSIS (per flowchart)
    # Iterate through each controller to form functional application chunks.
    # Each chunk = Controller + its Services + Entities + Repositories
    # Chunks without controllers are marked as "Low Microservice Readiness"
    # ═══════════════════════════════════════════════════════════════════════════════
    
    # Helper: score a single chunk using DYNAMIC content-based analysis
    def _score_chunk(chunk_controllers, chunk_services, chunk_repos, chunk_entities, chunk_domain):
        """Score a single chunk by analyzing actual file content (imports, annotations, relationships)."""
        chunk_criteria = []
        chunk_has_db = len(chunk_repos) > 0 or (len(chunk_entities) >= 2 and has_jpa_or_hibernate)
        chunk_has_layers = len(chunk_controllers) > 0 and len(chunk_services) > 0
        chunk_has_dtos_local = any(d.lower() in chunk_domain.lower() or chunk_domain.lower() in d.lower() for d in dtos)
        
        # ── Gather actual content for this chunk's components ──
        chunk_all_components = chunk_controllers + chunk_services + list(chunk_repos) + list(chunk_entities)
        chunk_contents = [file_content_map.get(comp, "") for comp in chunk_all_components]
        combined_content = "\n".join(chunk_contents)
        
        # ── Dynamic metrics from actual code ──
        # Count imports (application-only cross-domain, excluding framework/JDK imports)
        import_lines = [l.strip() for l in combined_content.split("\n") if l.strip().startswith("import ")]
        import_paths = []
        for line in import_lines:
            match = re.search(r"import\s+(?:static\s+)?([a-zA-Z0-9_.*]+)\s*;", line)
            if match:
                import_paths.append(match.group(1))

        local_packages = set()
        for content in chunk_contents:
            package_match = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", content, re.MULTILINE)
            if package_match:
                local_packages.add(package_match.group(1).strip())

        local_prefixes = set()
        for package_name in local_packages:
            tokens = [token for token in package_name.split(".") if token]
            if len(tokens) >= 3:
                local_prefixes.add(".".join(tokens[:3]))
            elif tokens:
                local_prefixes.add(".".join(tokens))

        app_imports = []
        platform_prefixes = (
            "java.", "javax.", "jakarta.", "org.springframework.", "org.slf4j.", "ch.qos.logback.",
            "lombok.", "com.fasterxml.", "org.hibernate.", "org.apache.", "org.junit.", "reactor.",
        )
        for import_path in import_paths:
            lowered = import_path.lower()
            if lowered.startswith(platform_prefixes):
                continue
            app_imports.append(import_path)

        total_imports = len(app_imports)
        same_domain_imports = 0
        cross_domain_imports = 0
        for import_path in app_imports:
            import_tokens = [token for token in import_path.split(".") if token]
            import_prefix = ".".join(import_tokens[:3]) if len(import_tokens) >= 3 else ".".join(import_tokens)
            is_local = (
                chunk_domain.lower() in import_path.lower()
                or any(import_path.startswith(prefix + ".") or import_path == prefix for prefix in local_prefixes)
            )
            if is_local:
                same_domain_imports += 1
            else:
                cross_domain_imports += 1

        cross_domain_ratio = cross_domain_imports / max(total_imports, 1)
        
        # Count transaction/state annotations IN THIS CHUNK
        chunk_tx_count = combined_content.count("@Transactional")
        chunk_session_refs = combined_content.count("HttpSession") + combined_content.count("@SessionAttribute") + combined_content.count("@SessionScope")
        chunk_cacheable = combined_content.count("@Cacheable") + combined_content.count("@CacheEvict")
        chunk_async = combined_content.count("@Async") + combined_content.count("@EventListener") + combined_content.count("@KafkaListener") + combined_content.count("@RabbitListener") + combined_content.count("@JmsListener")
        
        # Count entity relationships
        entity_rel_count = combined_content.count("@ManyToOne") + combined_content.count("@OneToMany") + combined_content.count("@ManyToMany") + combined_content.count("@OneToOne")
        native_queries = combined_content.count("@Query") + combined_content.count("nativeQuery")
        
        # Detect interface usage (loose coupling indicator)
        interface_count = len(re.findall(r'\bimplements\s+\w+', combined_content))
        injection_count = combined_content.count("@Autowired") + combined_content.count("@Inject") + len(re.findall(r'private\s+final\s+\w+\s+\w+;', combined_content))
        
        if chunk_has_db:
            # ══ Option 1: DB Coupling (25) + Coupling (25) + Tx (25) + Modularity (25) ══
            db_max = 25
            # Dynamic DB coupling: fewer entity relationships + fewer native queries = easier to extract
            if entity_rel_count == 0 and native_queries == 0:
                db_pct = 0.90  # Very clean - no cross-entity deps
                db_justification = f"No entity relationships or native queries — clean data boundary ({len(chunk_repos)} repos, {len(chunk_entities)} entities)"
            elif entity_rel_count <= 2 and native_queries == 0:
                db_pct = 0.75
                db_justification = f"{entity_rel_count} entity relationship(s) detected — manageable data coupling ({len(chunk_repos)} repos, {len(chunk_entities)} entities)"
            elif entity_rel_count <= 5:
                db_pct = 0.55
                db_justification = f"{entity_rel_count} entity relationships and {native_queries} native queries — moderate DB coupling requiring schema separation planning"
            elif entity_rel_count <= 10:
                db_pct = 0.35
                db_justification = f"{entity_rel_count} entity relationships — significant cross-entity dependencies complicate database splitting"
            else:
                db_pct = 0.15
                db_justification = f"{entity_rel_count} entity relationships + {native_queries} native queries — heavy DB coupling, shared schema likely"
            db_score = round(db_max * db_pct)
            chunk_criteria.append({"name": "Database Coupling Detection", "score": db_score, "max_score": db_max, "score_percent": round((db_score/db_max)*100), "justification": db_justification})
            coup_max = 25
        else:
            coup_max = 50
        
        # ══ Coupling & Dependency Analysis (dynamic) ══
        # Based on cross-domain import ratio + interface usage + DI patterns
        if total_imports == 0 and chunk_has_layers:
            coup_pct = 0.75
            coup_just = "Moderate coupling (0/0 cross-domain imports), clear layers — extractable with minor refactoring"
        elif cross_domain_ratio <= 0.15 and chunk_has_dtos_local and interface_count >= 1:
            coup_pct = 0.90
            coup_just = f"Low cross-domain coupling ({cross_domain_imports}/{total_imports} external imports), DTOs present, {interface_count} interface(s) — well-isolated"
        elif cross_domain_ratio <= 0.25 and chunk_has_layers:
            coup_pct = 0.75
            coup_just = f"Moderate coupling ({cross_domain_imports}/{total_imports} cross-domain imports), clear layers — extractable with minor refactoring"
        elif cross_domain_ratio <= 0.40:
            coup_pct = 0.55
            coup_just = f"{cross_domain_imports} of {total_imports} imports are cross-domain ({round(cross_domain_ratio*100)}%) — needs interface extraction before separation"
        elif cross_domain_ratio <= 0.60:
            coup_pct = 0.35
            coup_just = f"High coupling: {round(cross_domain_ratio*100)}% of imports are cross-domain — significant dependency untangling required"
        else:
            coup_pct = 0.15
            coup_just = f"Very high coupling: {cross_domain_imports}/{total_imports} imports cross domain boundaries — tightly integrated with other modules"
        coup_score = round(coup_max * coup_pct)
        chunk_criteria.append({"name": "Coupling & Dependency Analysis", "score": coup_score, "max_score": coup_max, "score_percent": round((coup_score/coup_max)*100), "justification": coup_just})
        
        # ══ Transaction & State Complexity (dynamic) ══
        tx_max = 25 if chunk_has_db else 30
        if chunk_async >= 2 and chunk_tx_count == 0 and chunk_session_refs == 0:
            tx_pct = 0.90
            tx_just = f"Event-driven ({chunk_async} async/listener annotations), no transactions, no session state — ideal for microservices"
        elif chunk_tx_count == 0 and chunk_session_refs == 0:
            tx_pct = 0.75
            tx_just = f"Stateless: 0 @Transactional, 0 session references — no distributed transaction concerns"
        elif chunk_tx_count <= 2 and chunk_session_refs == 0:
            tx_pct = 0.60
            tx_just = f"{chunk_tx_count} @Transactional method(s), no session state — minor transaction boundary needed"
        elif chunk_session_refs >= 1 and chunk_tx_count <= 3:
            tx_pct = 0.40
            tx_just = f"{chunk_session_refs} session reference(s) + {chunk_tx_count} @Transactional — needs distributed cache and saga patterns"
        elif chunk_tx_count > 3:
            tx_pct = 0.25
            tx_just = f"Heavy transactional: {chunk_tx_count} @Transactional + {chunk_session_refs} session refs — complex distributed transaction redesign needed"
        else:
            tx_pct = 0.30
            tx_just = f"{chunk_tx_count} @Transactional, {chunk_session_refs} session refs — moderate state complexity"
        tx_score = round(tx_max * tx_pct)
        chunk_criteria.append({"name": "Transaction & State Complexity", "score": tx_score, "max_score": tx_max, "score_percent": round((tx_score/tx_max)*100), "justification": tx_just})
        
        # ══ Code Structure & Modularity (dynamic) ══
        mod_max = 25 if chunk_has_db else 20
        mod_pct = 0
        mod_details = []
        if is_multi_module:
            mod_pct += 15
            mod_details.append("multi-module project")
        if chunk_has_layers:
            mod_pct += 25
            mod_details.append(f"{len(chunk_controllers)}C/{len(chunk_services)}S layered")
        if chunk_has_dtos_local:
            mod_pct += 10
            mod_details.append("domain DTOs")
        if has_docker:
            mod_pct += 15
            mod_details.append("containerization")
        if has_config_externalized:
            mod_pct += 10
            mod_details.append("externalized config")
        if interface_count >= 2:
            mod_pct += 10
            mod_details.append(f"{interface_count} interfaces")
        if injection_count >= 2:
            mod_pct += 10
            mod_details.append("DI pattern")
        if has_spring_cloud:
            mod_pct += 10
            mod_details.append("cloud-native")
        mod_pct = min(mod_pct, 100)
        mod_score = round(mod_max * mod_pct / 100)
        if mod_pct >= 60:
            mod_just = f"Good modularity: {', '.join(mod_details)} — ready for extraction"
        elif mod_pct >= 35:
            mod_just = f"Partial modularity: {', '.join(mod_details) if mod_details else 'basic structure'} — needs interface boundaries"
        else:
            mod_just = f"Limited modularity ({mod_pct}%) — requires structural refactoring before extraction"
        chunk_criteria.append({"name": "Code Structure & Modularity", "score": mod_score, "max_score": mod_max, "score_percent": round((mod_score/mod_max)*100), "justification": mod_just})
        
        total = sum(c["score"] for c in chunk_criteria)
        max_t = sum(c["max_score"] for c in chunk_criteria)
        pct = round((total / max_t) * 100) if max_t > 0 else 0
        return pct, chunk_criteria, "OPTION_1" if chunk_has_db else "OPTION_2"
    
    # ── Build chunks: group by controller → find related services/entities/repos ──
    chunk_results = []
    used_services = set()
    used_entities = set()
    used_repos = set()
    
    # Helper to find related components by domain name matching
    def _find_related(component_list, domain_name):
        """Find components whose name contains the domain name."""
        related = []
        for comp in component_list:
            comp_domain = extract_domain_from_component(comp)
            if comp_domain and (domain_name in comp_domain or comp_domain in domain_name):
                related.append(comp)
        return related
    
    # Filter out config/utility controllers
    config_exclusion_patterns_local = [
        "config", "configuration", "security", "cors", "swagger",
        "exception", "handler", "resolver", "interceptor", "filter",
        "auth", "oauth", "token", "gateway", "proxy", "bean",
        "util", "helper", "common", "base", "abstract", "global"
    ]
    
    def is_config_or_utility(class_name: str) -> bool:
        name_lower = class_name.lower()
        return any(pattern in name_lower for pattern in config_exclusion_patterns_local)
    
    business_controllers = [c for c in controllers if not is_config_or_utility(c)]
    
    for ctrl in business_controllers:
        ctrl_domain = extract_domain_from_component(ctrl)
        if not ctrl_domain:
            continue
        
        # Step 5: Identify services used by this controller
        chunk_services = _find_related(services_files, ctrl_domain)
        
        # Step 6: Identify entities used
        chunk_entities_list = _find_related(entities, ctrl_domain)
        
        # Step 7: Identify repositories
        chunk_repos_list = _find_related(repositories, ctrl_domain)
        
        # Track used components
        used_services.update(chunk_services)
        used_entities.update(chunk_entities_list)
        used_repos.update(chunk_repos_list)
        
        # Determine chunk status per flowchart
        if not chunk_services:
            # No services → NOT ELIGIBLE (No Business Logic)
            # Still provide dynamic criteria explaining WHY
            ctrl_content = file_content_map.get(ctrl, "")
            ctrl_lines = len(ctrl_content.split("\n")) if ctrl_content else 0
            ctrl_methods = len(re.findall(r'@(Get|Post|Put|Delete|Patch)Mapping', ctrl_content))
            chunk_score = 15 + min(10, ctrl_methods * 2)  # 15-25 based on endpoints
            chunk_classification = "NOT_SUITABLE"
            chunk_label = "Not Suitable"
            chunk_reason = f"No business logic layer (service classes) found for this controller ({ctrl_methods} endpoints, {ctrl_lines} lines)"
            chunk_criteria_detail = [
                {"name": "Coupling & Dependency Analysis", "score": 0, "max_score": 50, "score_percent": 0, "justification": f"No service layer — controller has {ctrl_methods} endpoint(s) but no business logic separation"},
                {"name": "Transaction & State Complexity", "score": round(30 * 0.5), "max_score": 30, "score_percent": 50, "justification": "Cannot assess — no service layer to analyze transactional behavior"},
                {"name": "Code Structure & Modularity", "score": round(20 * 0.15), "max_score": 20, "score_percent": 15, "justification": f"Controller-only ({ctrl_lines} lines) — no layered architecture, needs service extraction"}
            ]
            chunk_option = "OPTION_2"
        elif not chunk_entities_list and not chunk_repos_list:
            # Services exist but no entities → LOW MICROSERVICE READINESS
            chunk_score, chunk_criteria_detail, chunk_option = _score_chunk(
                [ctrl], chunk_services, [], [], ctrl_domain
            )
            if chunk_score >= 70:
                chunk_classification = "GOOD_CANDIDATE"
                chunk_label = "Good Candidate"
            elif chunk_score >= 51:
                chunk_classification = "REFACTOR_REQUIRED"
                chunk_label = "Refactor Required"
            else:
                chunk_classification = "NOT_SUITABLE"
                chunk_label = "Not Suitable"
            chunk_reason = "Shared logic / utility layer only (no data entities)"
        else:
            # Full chunk: Controller + Services + Entities + Repositories
            chunk_score, chunk_criteria_detail, chunk_option = _score_chunk(
                [ctrl], chunk_services, chunk_repos_list, chunk_entities_list, ctrl_domain
            )
            if chunk_score >= 81:
                chunk_classification = "HIGHLY_SUITABLE"
                chunk_label = "Highly Suitable"
            elif chunk_score >= 70:
                chunk_classification = "GOOD_CANDIDATE"
                chunk_label = "Good Candidate"
            elif chunk_score >= 51:
                chunk_classification = "REFACTOR_REQUIRED"
                chunk_label = "Refactor Required"
            else:
                chunk_classification = "NOT_SUITABLE"
                chunk_label = "Not Suitable"
            chunk_reason = f"Complete functional chunk: {ctrl} → {', '.join(chunk_services[:2])} → {', '.join(chunk_entities_list[:2] + chunk_repos_list[:2])}"
        
        chunk_results.append({
            "chunk_name": f"{ctrl_domain.capitalize()} Module",
            "controller": ctrl,
            "services": chunk_services,
            "entities": chunk_entities_list,
            "repositories": chunk_repos_list,
            "score": chunk_score,
            "classification": chunk_classification,
            "label": chunk_label,
            "reason": chunk_reason,
            "criteria": chunk_criteria_detail,
            "criteria_option": chunk_option,
            "components": [ctrl] + chunk_services + chunk_entities_list + chunk_repos_list
        })
    
    # Handle services without controllers (shared/utility - low readiness)
    orphan_services = [s for s in services_files if s not in used_services and not is_config_or_utility(s)]
    if orphan_services and not business_controllers:
        # No controllers at all → mark as NOT ELIGIBLE per flowchart
        # Dynamic: analyze what these services actually contain
        orphan_content = "\n".join(file_content_map.get(s, "") for s in orphan_services)
        orphan_tx = orphan_content.count("@Transactional")
        orphan_interfaces = len(re.findall(r'\bimplements\s+\w+', orphan_content))
        orphan_score = 15 + min(15, len(orphan_services) * 3) + (5 if orphan_interfaces >= 2 else 0)
        orphan_score = min(orphan_score, 45)  # Cap below 51 (not suitable)
        
        orphan_entities_left = list(set(entities) - used_entities)
        orphan_repos_left = list(set(repositories) - used_repos)
        
        chunk_results.append({
            "chunk_name": "Shared Utilities",
            "controller": None,
            "services": orphan_services,
            "entities": orphan_entities_left,
            "repositories": orphan_repos_left,
            "score": orphan_score,
            "classification": "NOT_SUITABLE",
            "label": "Not Suitable",
            "reason": f"No API boundary (no controllers) — {len(orphan_services)} service(s) cannot form independent microservice without REST exposure",
            "criteria": [
                {"name": "Coupling & Dependency Analysis", "score": round(50 * 0.20), "max_score": 50, "score_percent": 20, "justification": f"No API boundary — {len(orphan_services)} services have no controller exposure, cannot be independently deployed"},
                {"name": "Transaction & State Complexity", "score": round(30 * (0.70 if orphan_tx == 0 else 0.35)), "max_score": 30, "score_percent": 70 if orphan_tx == 0 else 35, "justification": f"{orphan_tx} @Transactional annotations in {len(orphan_services)} utility services"},
                {"name": "Code Structure & Modularity", "score": round(20 * (0.30 if orphan_interfaces >= 1 else 0.10)), "max_score": 20, "score_percent": 30 if orphan_interfaces >= 1 else 10, "justification": f"{orphan_interfaces} interface(s) found — {'some abstraction' if orphan_interfaces >= 1 else 'no abstraction'}, but no layered architecture without controllers"}
            ],
            "criteria_option": "OPTION_2",
            "components": orphan_services
        })
    
    print(f"[MICROSERVICE] Chunk analysis complete: {len(chunk_results)} chunks formed")
    for cr in chunk_results:
        print(f"  - {cr['chunk_name']}: {cr['score']}% → {cr['label']}")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 14: OVERALL APPLICATION ANALYSIS (aggregate chunk scores)
    # Methods: Weighted Score (preferred for enterprise), Eligible Chunk Ratio
    # ═══════════════════════════════════════════════════════════════════════════════
    
    if chunk_results:
        # 14.2: Calculate overall application score (weighted by component count)
        total_weighted = 0
        total_weight = 0
        for cr in chunk_results:
            weight = len(cr["components"]) if cr["components"] else 1
            total_weighted += cr["score"] * weight
            total_weight += weight
        overall_weighted_score = round(total_weighted / total_weight) if total_weight > 0 else score_percent
        
        # 14.3: Calculate eligible chunk ratio
        eligible_chunks = [cr for cr in chunk_results if cr["score"] >= 70]
        eligible_chunk_ratio = round((len(eligible_chunks) / len(chunk_results)) * 100) if chunk_results else 0
        
        # Use weighted score as the primary overall score for the application
        final_score = overall_weighted_score
    else:
        # No chunks formed (no controllers) — use the flat score
        final_score = score_percent
        overall_weighted_score = score_percent
        eligible_chunks = []
        eligible_chunk_ratio = 0
    
    # Re-determine eligibility based on final (chunk-aggregated) score
    if final_score >= 70:
        eligibility_level = "ELIGIBLE"
        eligibility_label = "Good Candidate"
        eligible = True
        confidence = "high"
    elif final_score >= 51:
        eligibility_level = "INTERMEDIATE"
        eligibility_label = "Intermediate (Partial)"
        eligible = True
        confidence = "medium"
    else:
        eligibility_level = "NOT_RECOMMENDED"
        eligibility_label = "Not Suitable"
        eligible = False
        confidence = "low"
    
    # Update score_percent to use the chunk-aggregated score
    score_percent = final_score
    
    print(f"[MICROSERVICE] Overall: weighted={overall_weighted_score}%, eligible_chunks={len(eligible_chunks)}/{len(chunk_results)}, ratio={eligible_chunk_ratio}%")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 4b: Generate DYNAMIC benefits based on actual repo characteristics
    # ═══════════════════════════════════════════════════════════════════════════════
    benefits_if_converted = []
    if score_percent >= 51:
        # Based on detected service domains
        deduped_services_count = len(set(extract_domain_from_component(s) for s in services_files if extract_domain_from_component(s)))
        
        if deduped_services_count > 1:
            benefits_if_converted.append({
                "title": "Independent Deployment",
                "description": f"Your {deduped_services_count} service domains ({', '.join(list(domain_patterns)[:3])}) can be deployed independently, reducing release coordination overhead.",
                "icon": "✅"
            })
        else:
            benefits_if_converted.append({
                "title": "Deployment Isolation",
                "description": f"The '{list(domain_patterns)[0] if domain_patterns else 'core'}' service can be extracted and deployed separately from shared infrastructure.",
                "icon": "✅"
            })

        if len(controllers) > 1:
            benefits_if_converted.append({
                "title": "Targeted Scalability",
                "description": f"Your {len(controllers)} API endpoints can scale independently — high-traffic endpoints won't bottleneck low-traffic ones.",
                "icon": "✅"
            })
        else:
            benefits_if_converted.append({
                "title": "Horizontal Scalability",
                "description": f"With {len(java_files)} source files, splitting into services allows each to scale based on its own demand patterns.",
                "icon": "✅"
            })

        # Fault isolation based on coupling
        coupling_criteria = next((c for c in evaluation_criteria if "Coupling" in c["name"]), None)
        if coupling_criteria and coupling_criteria["score_percent"] >= 50:
            benefits_if_converted.append({
                "title": "Fault Isolation",
                "description": f"Your codebase shows {coupling_criteria['score_percent']}% decoupling readiness — failures in one service won't cascade to others.",
                "icon": "✅"
            })
        else:
            benefits_if_converted.append({
                "title": "Fault Isolation (After Refactoring)",
                "description": "Once dependencies are decoupled, each service can fail independently without bringing down the entire system.",
                "icon": "✅"
            })

        # Technology benefit
        if has_spring_boot:
            benefits_if_converted.append({
                "title": "Technology Evolution",
                "description": "Spring Boot services can be individually upgraded or replaced with newer frameworks (Quarkus, Micronaut) without affecting others.",
                "icon": "✅"
            })
        else:
            benefits_if_converted.append({
                "title": "Technology Flexibility",
                "description": "Each extracted service can adopt the most suitable technology stack for its specific business function.",
                "icon": "✅"
            })

        # Modularity benefit
        modularity_criteria = next((c for c in evaluation_criteria if "Modularity" in c["name"] or "Structure" in c["name"]), None)
        if modularity_criteria and modularity_criteria["score_percent"] >= 60:
            benefits_if_converted.append({
                "title": "Accelerated Development",
                "description": f"Good existing modularity ({modularity_criteria['score_percent']}%) means teams can own individual services and deliver features in parallel.",
                "icon": "✅"
            })
        else:
            benefits_if_converted.append({
                "title": "Improved Maintainability",
                "description": f"Breaking {len(java_files)} files into focused services creates clearer ownership and reduces cognitive load per team.",
                "icon": "✅"
            })

        # Chunk-specific benefit
        if len(eligible_chunks) > 0:
            benefits_if_converted.append({
                "title": "Phased Migration Ready",
                "description": f"{len(eligible_chunks)} of {len(chunk_results)} modules scored 70%+ — you can start migrating eligible chunks immediately while refactoring others.",
                "icon": "✅"
            })

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 5b: Generate DYNAMIC risks based on actual repo characteristics
    # ═══════════════════════════════════════════════════════════════════════════════
    risks_if_not_converted = []
    if score_percent >= 51:
        deduped_services_count = len(set(extract_domain_from_component(s) for s in services_files if extract_domain_from_component(s)))
        
        if len(java_files) > 50:
            risks_if_not_converted.append({
                "title": "Growing Complexity",
                "description": f"With {len(java_files)} Java files in a monolith, adding features will increase merge conflicts and regression risk exponentially.",
                "icon": "⚠️"
            })
        elif len(java_files) > 20:
            risks_if_not_converted.append({
                "title": "Scaling Bottleneck",
                "description": f"As the {len(java_files)}-file codebase grows, the monolith will become harder to scale for individual high-demand components.",
                "icon": "⚠️"
            })
        else:
            risks_if_not_converted.append({
                "title": "Future Scalability Risk",
                "description": f"Even with {len(java_files)} files today, growth will eventually require the entire application to scale for any single component's demand.",
                "icon": "⚠️"
            })

        if len(controllers) > 1:
            risks_if_not_converted.append({
                "title": "Deployment Risk",
                "description": f"All {len(controllers)} API endpoints must be redeployed together — a bug in one endpoint risks downtime for all.",
                "icon": "⚠️"
            })
        else:
            risks_if_not_converted.append({
                "title": "Full Redeployment Required",
                "description": "Any change requires redeploying the entire application, increasing release risk.",
                "icon": "⚠️"
            })

        if deduped_services_count > 1:
            domain_list = list(domain_patterns)
            risks_if_not_converted.append({
                "title": "Team Bottleneck",
                "description": f"Your {deduped_services_count} service domains share one deployment — teams working on '{domain_list[0]}' block teams on '{domain_list[-1] if len(domain_list) > 1 else domain_list[0]}'.",
                "icon": "⚠️"
            })
        else:
            risks_if_not_converted.append({
                "title": "Single Point of Failure",
                "description": "The monolithic architecture means any component failure can bring down the entire application.",
                "icon": "⚠️"
            })

        if has_database_layer:
            risks_if_not_converted.append({
                "title": "Database Contention",
                "description": f"All {len(repositories)} data access patterns compete for the same database resources, creating performance bottlenecks under load.",
                "icon": "⚠️"
            })

        risks_if_not_converted.append({
            "title": "Technical Debt Accumulation",
            "description": f"Maintaining {len(java_files)} files in a single codebase will accumulate coupling and make future decomposition progressively harder.",
            "icon": "⚠️"
        })

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 6b: Generate DYNAMIC changes needed based on weak criteria scores
    # ═══════════════════════════════════════════════════════════════════════════════
    changes_needed = []
    if score_percent < 70:
        for criteria in evaluation_criteria:
            if criteria["score_percent"] < 60:
                if "Database" in criteria["name"]:
                    changes_needed.append({
                        "title": "Reduce Database Coupling",
                        "description": f"Scored {criteria['score_percent']}% — with {len(repositories)} repositories sharing data, introduce database-per-service pattern. Each of your {unique_domains} domain(s) should own its data store.",
                        "icon": "🔧"
                    })
                elif "Coupling" in criteria["name"]:
                    changes_needed.append({
                        "title": "Decouple Service Dependencies",
                        "description": f"Scored {criteria['score_percent']}% — services have direct dependencies. Replace synchronous calls with API contracts or event-driven messaging between domains.",
                        "icon": "🔧"
                    })
                elif "Transaction" in criteria["name"]:
                    changes_needed.append({
                        "title": "Simplify Transaction Boundaries",
                        "description": f"Scored {criteria['score_percent']}% — break distributed transactions using the saga pattern. Move from shared in-memory state to per-service stateless design.",
                        "icon": "🔧"
                    })
                elif "Modularity" in criteria["name"] or "Structure" in criteria["name"]:
                    missing = []
                    if not is_multi_module: missing.append("multi-module structure")
                    if not has_clear_layers: missing.append("layered architecture")
                    if not has_docker: missing.append("containerization")
                    if not has_config_externalized: missing.append("externalized config")
                    changes_needed.append({
                        "title": "Improve Code Modularity",
                        "description": f"Scored {criteria['score_percent']}% — missing: {', '.join(missing[:3]) if missing else 'clear component boundaries'}. Organize into well-defined modules.",
                        "icon": "🔧"
                    })
        
        # Chunk-specific changes
        refactor_chunks = [cr for cr in chunk_results if cr["classification"] == "REFACTOR_REQUIRED"]
        if refactor_chunks:
            changes_needed.append({
                "title": f"Refactor {len(refactor_chunks)} Module(s)",
                "description": f"Modules needing refactoring: {', '.join(cr['chunk_name'] for cr in refactor_chunks[:3])}. Improve separation and reduce internal coupling.",
                "icon": "🔧"
            })
        
        if not changes_needed:
            changes_needed.append({
                "title": "Strengthen Domain Boundaries",
                "description": f"Overall score {score_percent}% is close to eligible. Improve separation between your {unique_domains} domain(s) to cross the 70% threshold.",
                "icon": "🔧"
            })

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 7b: Generate DYNAMIC reasons why NOT recommended (shown if <= 50%)
    # ═══════════════════════════════════════════════════════════════════════════════
    not_recommended_reasons = []
    if score_percent <= 50:
        if unique_domains <= 1:
            not_recommended_reasons.append({
                "title": "Single Domain Detected",
                "description": f"Only {unique_domains} domain found ({', '.join(list(domain_patterns)[:2]) if domain_patterns else 'undetermined'}). Microservices require at least 2-3 distinct bounded contexts.",
                "icon": "❌"
            })
        elif unique_domains < 3:
            not_recommended_reasons.append({
                "title": "Insufficient Domain Separation",
                "description": f"Only {unique_domains} domains detected ({', '.join(list(domain_patterns)[:3])}). Recommended minimum is 3+ bounded contexts.",
                "icon": "❌"
            })

        coupling_criteria = next((c for c in evaluation_criteria if "Coupling" in c["name"]), None)
        if coupling_criteria and coupling_criteria["score_percent"] < 50:
            not_recommended_reasons.append({
                "title": "High Component Coupling",
                "description": f"Coupling score is {coupling_criteria['score_percent']}% — components are too tightly interdependent for independent deployment.",
                "icon": "❌"
            })

        if len(java_files) < 10:
            not_recommended_reasons.append({
                "title": "Codebase Too Small",
                "description": f"With only {len(java_files)} Java files, microservices infrastructure overhead far exceeds the benefits.",
                "icon": "❌"
            })

        if len(controllers) == 0:
            not_recommended_reasons.append({
                "title": "No API Layer Detected",
                "description": "No REST controllers found — without an API layer, there's no natural service boundary to extract.",
                "icon": "❌"
            })
        elif len(controllers) == 1:
            not_recommended_reasons.append({
                "title": "Single API Endpoint",
                "description": "Only 1 controller detected — a single API endpoint doesn't benefit from microservice decomposition.",
                "icon": "❌"
            })

        # Not-suitable chunks info
        not_suitable_chunks = [cr for cr in chunk_results if cr["classification"] == "NOT_SUITABLE"]
        if not_suitable_chunks:
            not_recommended_reasons.append({
                "title": f"{len(not_suitable_chunks)} Module(s) Not Suitable",
                "description": f"Modules scoring below 50%: {', '.join(cr['chunk_name'] for cr in not_suitable_chunks[:3])}. These lack the structure needed for extraction.",
                "icon": "❌"
            })

        # Dynamic changes for NOT_RECOMMENDED
        changes_needed = []
        if len(controllers) == 0:
            changes_needed.append({"title": "Add REST API Layer", "description": "Create REST controllers for business operations to establish service boundaries.", "icon": "📋"})
        if not has_clear_layers:
            changes_needed.append({"title": "Introduce Layered Architecture", "description": f"Organize {len(java_files)} files into Controller → Service → Repository layers.", "icon": "📋"})
        if unique_domains < 3:
            changes_needed.append({"title": "Identify Domain Boundaries", "description": f"Currently {unique_domains} domain(s). Apply DDD to identify at least 3-5 bounded contexts.", "icon": "📋"})
        if not has_messaging:
            changes_needed.append({"title": "Add Async Communication", "description": "Introduce messaging (Kafka/RabbitMQ) to reduce synchronous coupling.", "icon": "📋"})
        if not has_docker:
            changes_needed.append({"title": "Containerize the Application", "description": "Add Dockerfile and docker-compose as a prerequisite for orchestration.", "icon": "📋"})
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 8: Generate suggested microservices from CHUNK RESULTS
    # Each eligible/refactorable chunk becomes a suggested microservice
    # ═══════════════════════════════════════════════════════════════════════════════
    suggested_services = []
    
    if score_percent >= 51 and chunk_results:
        for cr in chunk_results:
            if cr["classification"] in ("HIGHLY_SUITABLE", "GOOD_CANDIDATE", "REFACTOR_REQUIRED"):
                suggested_services.append({
                    "name": cr["chunk_name"],
                    "description": f"Handles all {cr['chunk_name'].replace(' Module', '').lower()}-related business logic. Score: {cr['score']}% ({cr['label']}).",
                    "components": cr["components"][:6]
                })
    
    # Add API Gateway only when 2+ business services
    if len(suggested_services) >= 2:
        gateway_components = [c for c in configs if "test" not in c.lower() and any(
            kw in c.lower() for kw in ["security", "cors", "swagger", "gateway", "auth", "token", "resolver"]
        )]
        if gateway_components:
            suggested_services.append({
                "name": "API Gateway",
                "description": "Handles authentication, CORS, security, and request routing across services.",
                "components": gateway_components[:5]
            })
    
    # Fallback: if no chunks but we have components
    if score_percent >= 51 and not suggested_services:
        all_components = [c for c in controllers + services_files if not is_config_or_utility(c)]
        all_components += repositories + entities
        if all_components:
            suggested_services.append({
                "name": "Core Application Service",
                "description": "Main application service containing all business logic.",
                "components": all_components[:6]
            })
    
    print(f"[MICROSERVICE] Suggested services: {len(suggested_services)} (from {len(chunk_results)} chunks)")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 9: Build signals for/against (dynamic)
    # ═══════════════════════════════════════════════════════════════════════════════
    signals_for = []
    signals_against = []
    
    if len(controllers) >= 3:
        signals_for.append(f"{len(controllers)} REST controllers indicate API-driven architecture")
    elif len(controllers) >= 1:
        signals_for.append(f"{len(controllers)} REST controller(s) provide API entry points")
    else:
        signals_against.append("No REST controllers detected - limited API surface")
    
    if len(services_files) >= 3:
        signals_for.append(f"{len(services_files)} service classes show business logic separation")
    elif len(services_files) < 2:
        signals_against.append(f"Only {len(services_files)} service classes - limited business logic separation")
    
    if unique_domains >= 3:
        signals_for.append(f"{unique_domains} distinct domains detected ({', '.join(list(domain_patterns)[:3])})")
    else:
        signals_against.append(f"Only {unique_domains} domain(s) detected - limited bounded contexts")
    
    if has_spring_boot:
        signals_for.append("Spring Boot framework supports microservices patterns")
    if has_messaging:
        signals_for.append("Messaging infrastructure enables event-driven architecture")
    if has_spring_cloud:
        signals_for.append("Spring Cloud dependencies indicate cloud-native readiness")
    
    if len(java_files) < 10:
        signals_against.append(f"Small codebase ({len(java_files)} files) may not justify microservices overhead")
    if len(entities) > 0 and len(repositories) == 0:
        signals_against.append("Entities without repositories suggest data access coupling")
    if not has_rest_api:
        signals_against.append("No REST API layer detected")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 10: Generate reasoning summary (dynamic, chunk-aware)
    # ═══════════════════════════════════════════════════════════════════════════════
    deduped_services_count = len(set(extract_domain_from_component(s) for s in services_files if extract_domain_from_component(s)))
    
    if score_percent >= 70:
        eligible_names = ', '.join(cr['chunk_name'] for cr in chunk_results if cr['score'] >= 70)[:80]
        reasoning = (
            f"The application scores {score_percent}% (weighted across {len(chunk_results)} module chunks) and is a good candidate for microservices. "
            f"Eligible modules: {eligible_names or 'all analyzed chunks'}. "
            f"It has {unique_domains} distinct domains, {len(controllers)} controllers, and {deduped_services_count} services. "
            f"Proceed with phased migration starting from highest-scoring chunks."
        )
    elif score_percent >= 51:
        refactor_names = ', '.join(cr['chunk_name'] for cr in chunk_results if cr['classification'] == 'REFACTOR_REQUIRED')[:80]
        reasoning = (
            f"The application scores {score_percent}% across {len(chunk_results)} analyzed modules. "
            f"Partial migration possible but significant restructuring required. "
            f"Modules needing refactoring: {refactor_names or 'multiple modules need improvement'}. "
            f"Focus on decoupling and modularization before full microservice adoption."
        )
    else:
        reasoning = (
            f"The application scores only {score_percent}% across {len(chunk_results)} module(s) and is not recommended for microservices. "
            f"Limited domain separation ({unique_domains} domains), {len(controllers)} controllers, "
            f"and insufficient architectural patterns. Consider refactoring before decomposition."
        )
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 15: FINAL SCORECARD OUTPUT — Build and return result
    # Includes: chunk-level results + overall application score + recommendation
    # ═══════════════════════════════════════════════════════════════════════════════
    result = {
        "success": True,
        "eligible": eligible,
        "eligibility_level": eligibility_level,
        "eligibility_label": eligibility_label,
        "score": score_percent,
        "confidence": confidence,
        "confidence_score": score_percent,
        "reasoning": reasoning,
        
        # Evaluation breakdown (application-level criteria)
        "evaluation_criteria": evaluation_criteria,
        
        # ═══ CHUNK-LEVEL RESULTS (per flowchart Step 15.1) ═══
        "chunk_results": chunk_results,
        "chunk_summary": {
            "total_chunks": len(chunk_results),
            "eligible_chunks": len([cr for cr in chunk_results if cr["score"] >= 70]),
            "refactor_chunks": len([cr for cr in chunk_results if 51 <= cr["score"] < 70]),
            "not_suitable_chunks": len([cr for cr in chunk_results if cr["score"] < 51]),
            "eligible_chunk_ratio": eligible_chunk_ratio,
            "overall_weighted_score": overall_weighted_score,
            "scoring_method": "Weighted Score (by component count)"
        },
        
        # Signals
        "signals_for": signals_for,
        "signals_against": signals_against,
        
        # Benefits (if eligible)
        "benefits_if_converted": benefits_if_converted,
        
        # Risks (if not converted)
        "risks_if_not_converted": risks_if_not_converted,
        
        # Changes needed (for intermediate/not recommended)
        "changes_needed": changes_needed,
        
        # Why not recommended (for <= 50%)
        "not_recommended_reasons": not_recommended_reasons,
        
        # Suggested services (from chunks)
        "suggested_services": suggested_services,
        
        # Metadata
        "repo_name": f"{owner}/{repo}",
        "java_files_count": len(java_files),
        "controllers_count": len(controllers),
        "services_count": deduped_services_count,
        "services_files_count": len(services_files),
        "entities_count": len(entities),
        "repositories_count": len(repositories),
        "domains_detected": list(domain_patterns)[:10],
        
        # Criteria option used
        "criteria_option": criteria_option,
        "has_database_layer": has_database_layer,
        
        # Score range reference (per flowchart Step 12)
        "score_ranges": {
            "not_suitable": "0-50% - Not Suitable, stay monolith / refactor first",
            "refactor_required": "51-69% - Refactor Required, major restructuring needed",
            "good_candidate": "70-80% - Good Candidate, proceed with phased migration",
            "highly_suitable": "81-100% - Highly Suitable, ideal for microservices"
        }
    }
    
    return result

import React from "react";
import {
  FaArrowUp,
  FaBook,
  FaCheckCircle,
  FaChevronDown,
  FaChevronRight,
  FaCode,
  FaDatabase,
  FaExclamationTriangle,
  FaFileAlt,
  FaFileCode,
  FaFileExcel,
  FaFileImage,
  FaFileWord,
  FaFolder,
  FaFolderOpen,
  FaFlask,
  FaInfoCircle,
  FaJava,
  FaLeaf,
  FaListAlt,
  FaProjectDiagram,
  FaTimesCircle,
  FaTools,
} from "react-icons/fa";
import type { DependencyInfo, RepoFile } from "../../../services/api";
import { buildWizardAccentVars, getFileAccent, getFrameworkAccent } from "../../../components/wizard/wizardUi";

type StyleMap = Record<string, React.CSSProperties>;

interface DetectedFramework {
  name: string;
  path: string;
  type: string;
}

interface FrameworkPreviewFile {
  name: string;
  path: string;
  content: string;
}

interface ProjectStructureInfo {
  has_pom_xml?: boolean;
  has_build_gradle?: boolean;
  has_src_main?: boolean;
  has_src_test?: boolean;
  has_build_gradle_kts?: boolean;
  jsp_count?: number;
  jsf_count?: number;
}

interface FrameworkSectionProps {
  styles: StyleMap;
  detectedFrameworks: DetectedFramework[];
  dependencies?: DependencyInfo[];
  viewingFrameworkFile: FrameworkPreviewFile | null;
  frameworkFileLoading: boolean;
  onClosePreview: () => void;
  onOpenFramework: (framework: DetectedFramework) => void;
}

interface ProjectStructureSummaryProps {
  styles: StyleMap;
  structure?: ProjectStructureInfo | null;
  detectedJavaVersion: string | null;
  detectedJavaStructureLabel: string;
}

interface TechnicalSpecificationCardProps {
  styles: StyleMap;
  disabled: boolean;
  buttonLabel: string;
  helperText: string;
  onGenerate: () => void;
}

interface DiscoveryFileExplorerProps {
  styles: StyleMap;
  repositoryName: string;
  currentPath: string;
  showFileExplorer: boolean;
  selectedFile: RepoFile | null;
  repoFiles: RepoFile[];
  fileLoading: boolean;
  fileContent: string;
  isEditing: boolean;
  editedContent: string;
  onToggleExplorer: () => void;
  onNavigateRoot: () => void;
  onNavigateBack: () => void;
  onFileClick: (file: RepoFile) => void;
  onCloseSelectedFile: () => void;
  onEditedContentChange: (value: string) => void;
}

interface DiscoveryNotJavaAlertProps {
  onChooseDifferentRepository: () => void;
}

interface DiscoveryNoFrameworkAlertProps {
  isVisible: boolean;
}

interface DiscoveryHighRiskWarningProps {
  isVisible: boolean;
  missingBuildFiles: boolean;
  missingJavaVersion: boolean;
  missingSrcMain: boolean;
  sourceVersionStatus: "detected" | "not_selected" | "unknown";
  suggestedJavaVersion: string;
  buildConversionLabel: string;
  buildConversionNote: string;
  onSuggestedJavaVersionChange: (value: string) => void;
  onConfirm: () => void;
  onChooseDifferentRepository: () => void;
}

const getDetectedComponentCategory = (type: string): "Framework" | "Library" => {
  const normalizedType = type.toLowerCase();

  if (normalizedType.includes("library")) {
    return "Library";
  }

  if (
    normalizedType.includes("framework") ||
    normalizedType.includes("orm") ||
    normalizedType.includes("testing")
  ) {
    return "Framework";
  }

  return "Library";
};

const getFrameworkIcon = (frameworkType: string): React.ReactNode => {
  if (frameworkType === "Testing Framework") return <FaFlask />;
  if (frameworkType === "Application Framework") return <FaLeaf />;
  if (frameworkType === "ORM Framework") return <FaDatabase />;
  if (frameworkType === "Logging") return <FaListAlt />;
  if (frameworkType === "Mocking Framework") return <FaProjectDiagram />;
  if (frameworkType === "JSON Processing") return <FaCode />;
  return <FaBook />;
};

const isDetected = (dependencies: DependencyInfo[] | undefined, predicate: (artifactId: string) => boolean) =>
  Boolean(dependencies?.some((dependency) => predicate(dependency.artifact_id)));

const getFileLanguage = (fileName: string) => {
  const ext = fileName.split(".").pop()?.toLowerCase();
  const languageMap: Record<string, string> = {
    java: "Java",
    xml: "XML",
    json: "JSON",
    yml: "YAML",
    yaml: "YAML",
    properties: "Properties",
    md: "Markdown",
    gradle: "Gradle",
    kt: "Kotlin",
    js: "JavaScript",
    ts: "TypeScript",
    html: "HTML",
    css: "CSS",
    sql: "SQL",
    sh: "Shell",
    bat: "Batch",
    txt: "Text",
  };

  return languageMap[ext || ""] || "Text";
};

const formatFileSize = (size: number) => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const getFileIcon = (file: RepoFile): React.ReactNode => {
  if (file.type === "dir") return <FaFolderOpen />;

  const ext = file.name.split(".").pop()?.toLowerCase();
  const iconMap: Record<string, React.ReactNode> = {
    java: <FaJava />,
    xml: <FaCode />,
    json: <FaCode />,
    yml: <FaTools />,
    yaml: <FaTools />,
    properties: <FaTools />,
    md: <FaFileAlt />,
    gradle: <FaTools />,
    kt: <FaCode />,
    js: <FaCode />,
    ts: <FaCode />,
    html: <FaFileCode />,
    css: <FaFileCode />,
    sql: <FaDatabase />,
    sh: <FaFileAlt />,
    txt: <FaFileWord />,
    xlsx: <FaFileExcel />,
    png: <FaFileImage />,
  };

  return iconMap[ext || ""] || <FaFileAlt />;
};

const renderDiscoverySectionTitle = (
  styles: StyleMap,
  title: string,
  accent: string,
  icon: React.ReactNode
) => (
  <div style={{ ...styles.sectionTitle, display: "flex", alignItems: "center", gap: 10 }}>
    <span
      className="wizard-icon-badge wizard-icon-badge-sm"
      style={buildWizardAccentVars(accent)}
    >
      {icon}
    </span>
    <span>{title}</span>
  </div>
);

const renderStructureStatusItem = (isPresent: boolean, label: string) => (
  <span
    className={`discovery-structure-pill ${isPresent ? "is-present" : "is-missing"}`}
    aria-label={`${label} ${isPresent ? "present" : "missing"}`}
  >
    {isPresent ? <FaCheckCircle /> : <FaTimesCircle />}
    <span>{label}</span>
  </span>
);

const renderStructureCountItem = (count: number | undefined, label: string) => {
  if (!count || count <= 0) return null;

  return (
    <span
      className={`discovery-structure-pill is-present`}
      aria-label={`${count} ${label} files`}
    >
      <FaFileCode />
      <span>{count} {label}</span>
    </span>
  );
};

export function DiscoveryFrameworkSection({
  styles,
  detectedFrameworks,
  dependencies,
  viewingFrameworkFile,
  frameworkFileLoading,
  onClosePreview,
  onOpenFramework,
}: FrameworkSectionProps) {
  return (
    <>
      {renderDiscoverySectionTitle(
        styles,
        "Detected Frameworks & Libraries",
        "#ec4899",
        <FaProjectDiagram />
      )}

      {viewingFrameworkFile && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              backgroundColor: "#fff",
              borderRadius: 12,
              width: "80%",
              maxWidth: 900,
              maxHeight: "85vh",
              overflow: "hidden",
              boxShadow: "0 25px 50px rgba(0,0,0,0.3)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "16px 20px",
                backgroundColor: "#f6f8fa",
                borderBottom: "1px solid #d0d7de",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 20 }}>File</span>
                <div>
                  <div style={{ fontWeight: 600, color: "#24292f" }}>{viewingFrameworkFile.name}</div>
                  <div style={{ fontSize: 12, color: "#57606a" }}>{viewingFrameworkFile.path}</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 11,
                    padding: "4px 10px",
                    backgroundColor: "#ddf4ff",
                    borderRadius: 12,
                    color: "#0969da",
                  }}
                >
                  Read Only
                </span>
                <button
                  onClick={onClosePreview}
                  style={{
                    background: "none",
                    border: "1px solid #d0d7de",
                    borderRadius: 6,
                    padding: "6px 12px",
                    cursor: "pointer",
                    fontSize: 14,
                    color: "#24292f",
                  }}
                >
                  Close
                </button>
              </div>
            </div>
            <div
              style={{
                backgroundColor: "#0d1117",
                overflow: "auto",
                maxHeight: "calc(85vh - 70px)",
              }}
            >
              {frameworkFileLoading ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 60,
                    color: "#8b949e",
                  }}
                >
                  <div style={styles.spinner}></div>
                  <span style={{ marginLeft: 12 }}>Loading file content...</span>
                </div>
              ) : (
                <pre
                  style={{
                    margin: 0,
                    padding: 20,
                    color: "#c9d1d9",
                    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                    fontSize: 13,
                    lineHeight: 1.6,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {viewingFrameworkFile.content || "// File content unavailable"}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}

      {detectedFrameworks.length > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12,
            marginBottom: 20,
          }}
        >
          {detectedFrameworks.map((framework, index) => {
            const category = getDetectedComponentCategory(framework.type);

            return (
              <div
                key={`${framework.path}-${index}`}
                onClick={() => onOpenFramework(framework)}
                className="ui-hover-card-surface"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "14px 16px",
                  backgroundColor: "#fff",
                  border: "1px solid #d0d7de",
                  borderRadius: 8,
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span
                    className="wizard-icon-badge wizard-icon-badge-md"
                    style={buildWizardAccentVars(getFrameworkAccent(framework.type))}
                  >
                    {getFrameworkIcon(framework.type)}
                  </span>
                  <div>
                    <div style={{ fontWeight: 600, color: "#24292f", fontSize: 14 }}>{framework.name}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, color: "#57606a" }}>{framework.type}</span>
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          letterSpacing: "0.04em",
                          textTransform: "uppercase",
                          padding: "2px 8px",
                          borderRadius: 999,
                          backgroundColor: category === "Framework" ? "#ede9fe" : "#e0f2fe",
                          color: category === "Framework" ? "#6d28d9" : "#075985",
                          border: category === "Framework" ? "1px solid #c4b5fd" : "1px solid #bae6fd",
                        }}
                      >
                        {category}
                      </span>
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span
                    style={{
                      fontSize: 11,
                      padding: "3px 8px",
                      backgroundColor: "#dcfce7",
                      borderRadius: 10,
                      color: "#166534",
                    }}
                  >
                    Detected
                  </span>
                  <span style={{ color: "#0969da", fontSize: 12 }}>View</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={styles.frameworkGrid}>
          <div style={styles.frameworkItem}>
            <span>Spring</span>
            <span>Spring Boot</span>
            {isDetected(dependencies, (artifactId) => artifactId.includes("spring")) && (
              <span style={styles.detectedBadge}>Detected</span>
            )}
          </div>
          <div style={styles.frameworkItem}>
            <span>ORM</span>
            <span>JPA/Hibernate</span>
            {isDetected(
              dependencies,
              (artifactId) => artifactId.includes("hibernate") || artifactId.includes("jpa")
            ) && <span style={styles.detectedBadge}>Detected</span>}
          </div>
          <div style={styles.frameworkItem}>
            <span>Test</span>
            <span>JUnit</span>
            {isDetected(dependencies, (artifactId) => artifactId.includes("junit")) && (
              <span style={styles.detectedBadge}>Detected</span>
            )}
          </div>
          <div style={styles.frameworkItem}>
            <span>Log</span>
            <span>Log4j/SLF4J</span>
            {isDetected(
              dependencies,
              (artifactId) => artifactId.includes("log4j") || artifactId.includes("slf4j")
            ) && <span style={styles.detectedBadge}>Detected</span>}
          </div>
        </div>
      )}
    </>
  );
}

export function DiscoveryFileExplorer({
  styles,
  repositoryName,
  currentPath,
  showFileExplorer,
  selectedFile,
  repoFiles,
  fileLoading,
  fileContent,
  isEditing,
  editedContent,
  onToggleExplorer,
  onNavigateRoot,
  onNavigateBack,
  onFileClick,
  onCloseSelectedFile,
  onEditedContentChange,
}: DiscoveryFileExplorerProps) {
  return (
    <>
      {renderDiscoverySectionTitle(styles, "Repository Files", "#f59e0b", <FaFolder />)}
      <div
        className="discovery-file-explorer"
        style={{
          border: "1px solid #d0d7de",
          borderRadius: 16,
          overflow: "hidden",
          marginBottom: 24,
          backgroundColor: "#fff",
          boxShadow: "0 16px 36px rgba(15, 23, 42, 0.06)",
        }}
      >
        <div
          className="discovery-file-explorer__header"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 16px",
            background: "linear-gradient(180deg, #fcfdff 0%, #f7faff 100%)",
            borderBottom: "1px solid #d0d7de",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              className="wizard-icon-badge wizard-icon-badge-sm"
              style={buildWizardAccentVars("#f59e0b")}
            >
              <FaFolderOpen />
            </span>
            <span style={{ fontWeight: 700, color: "#0f172a" }}>{repositoryName}</span>
            {currentPath && (
              <>
                <span style={{ color: "#94a3b8" }}>/</span>
                <span
                  style={{
                    color: "#2563eb",
                    fontWeight: 600,
                    background: "#eff6ff",
                    border: "1px solid #bfdbfe",
                    borderRadius: 999,
                    padding: "4px 10px",
                  }}
                >
                  {currentPath}
                </span>
              </>
            )}
            <span className="discovery-file-count">{repoFiles.length} items</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {currentPath && (
              <button
                onClick={onNavigateRoot}
                className="discovery-file-action"
                style={{
                  border: "1px solid #d0d7de",
                  borderRadius: 999,
                  padding: "6px 12px",
                  cursor: "pointer",
                  fontSize: 12,
                  color: "#1e293b",
                  backgroundColor: "#fff",
                  fontWeight: 600,
                }}
              >
                Root
              </button>
            )}
            <button
              onClick={onToggleExplorer}
              className="discovery-file-action"
              style={{
                border: "1px solid #d0d7de",
                borderRadius: 999,
                padding: "6px 12px",
                cursor: "pointer",
                fontSize: 12,
                color: "#1e293b",
                backgroundColor: "#fff",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              {showFileExplorer ? <FaChevronDown /> : <FaChevronRight />}
              {showFileExplorer ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>

        {showFileExplorer && (
          <div style={{ display: "flex", minHeight: 400 }}>
            <div
              className="custom-scrollbar"
              style={{
                width: selectedFile ? "40%" : "100%",
                borderRight: selectedFile ? "1px solid #d0d7de" : "none",
                overflowY: "auto",
                maxHeight: 500,
                background:
                  "linear-gradient(180deg, rgba(248, 250, 252, 0.9) 0%, rgba(255, 255, 255, 1) 18%)",
              }}
            >
              {currentPath && (
                <div
                  onClick={onNavigateBack}
                  className="discovery-file-parent-row"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "12px 16px",
                    borderBottom: "1px solid #d0d7de",
                    cursor: "pointer",
                    backgroundColor: "#f8fafc",
                  }}
                >
                  <span
                    className="wizard-icon-badge wizard-icon-badge-sm"
                    style={buildWizardAccentVars("#2563eb")}
                  >
                    <FaArrowUp />
                  </span>
                  <div>
                    <div style={{ color: "#0f172a", fontSize: 13, fontWeight: 700 }}>Back to parent folder</div>
                    <div style={{ color: "#64748b", fontSize: 12 }}>..</div>
                  </div>
                </div>
              )}

              {repoFiles.length > 0 ? (
                repoFiles.map((file, index) => (
                  <div
                    key={`${file.path}-${index}`}
                    onClick={() => onFileClick(file)}
                    className={`discovery-file-row ${
                      selectedFile?.path === file.path ? "is-selected" : "ui-hover-row"
                    }`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "12px 16px",
                      borderBottom: "1px solid #d0d7de",
                      cursor: "pointer",
                      backgroundColor: selectedFile?.path === file.path ? "#eff6ff" : "transparent",
                      transition: "background-color 0.15s ease, transform 0.15s ease",
                    }}
                  >
                    <span
                      className={`wizard-icon-badge wizard-icon-badge-sm ${
                        file.type === "dir" ? "discovery-folder-badge" : "discovery-file-badge"
                      }`}
                      style={buildWizardAccentVars(getFileAccent(file.name, file.type))}
                    >
                      {getFileIcon(file)}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          color: file.type === "dir" ? "#1d4ed8" : "#0f172a",
                          fontWeight: file.type === "dir" ? 700 : 500,
                          fontSize: 14,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {file.name}
                      </div>
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>
                        {file.type === "dir" ? "Folder" : getFileLanguage(file.name)}
                      </div>
                    </div>
                    {file.type === "file" && file.size > 0 ? (
                      <span style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                        {formatFileSize(file.size)}
                      </span>
                    ) : (
                      <span style={{ fontSize: 12, color: "#cbd5e1", fontWeight: 700 }}>-</span>
                    )}
                  </div>
                ))
              ) : (
                <div style={{ padding: 20, textAlign: "center", color: "#57606a" }}>No files found</div>
              )}
            </div>

            {selectedFile && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", backgroundColor: "#fff" }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "10px 16px",
                    background: "linear-gradient(180deg, #fcfdff 0%, #f8fafc 100%)",
                    borderBottom: "1px solid #d0d7de",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      className="wizard-icon-badge wizard-icon-badge-sm"
                      style={buildWizardAccentVars(getFileAccent(selectedFile.name, selectedFile.type))}
                    >
                      {getFileIcon(selectedFile)}
                    </span>
                    <span style={{ fontWeight: 600, color: "#24292f" }}>{selectedFile.name}</span>
                    <span
                      style={{
                        fontSize: 11,
                        padding: "3px 8px",
                        backgroundColor: "#eff6ff",
                        borderRadius: 999,
                        color: "#2563eb",
                        border: "1px solid #bfdbfe",
                        fontWeight: 700,
                      }}
                    >
                      {getFileLanguage(selectedFile.name)}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={onCloseSelectedFile}
                      className="discovery-file-action"
                      style={{
                        border: "1px solid #d0d7de",
                        borderRadius: 999,
                        padding: "6px 12px",
                        cursor: "pointer",
                        fontSize: 12,
                        color: "#1e293b",
                        backgroundColor: "#fff",
                        fontWeight: 600,
                      }}
                    >
                      Close
                    </button>
                  </div>
                </div>

                <div
                  className="custom-scrollbar"
                  style={{
                    flex: 1,
                    overflow: "auto",
                    backgroundColor: "#0d1117",
                    position: "relative",
                  }}
                >
                  {fileLoading ? (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        height: "100%",
                        color: "#8b949e",
                      }}
                    >
                      <div style={styles.spinner}></div>
                      <span style={{ marginLeft: 10 }}>Loading file...</span>
                    </div>
                  ) : isEditing ? (
                    <textarea
                      value={editedContent}
                      onChange={(event) => onEditedContentChange(event.target.value)}
                      style={{
                        width: "100%",
                        height: "100%",
                        minHeight: 350,
                        padding: 16,
                        backgroundColor: "#0d1117",
                        color: "#c9d1d9",
                        border: "none",
                        outline: "none",
                        fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                        fontSize: 13,
                        lineHeight: 1.5,
                        resize: "none",
                        boxSizing: "border-box",
                      }}
                    />
                  ) : (
                    <pre
                      style={{
                        margin: 0,
                        padding: 16,
                        color: "#c9d1d9",
                        fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                        fontSize: 13,
                        lineHeight: 1.5,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {fileContent || "// Empty file"}
                    </pre>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

export function DiscoveryProjectStructureSummary({
  styles,
  structure,
  detectedJavaVersion,
  detectedJavaStructureLabel,
}: ProjectStructureSummaryProps) {
  const structureItems: Array<{ key: string; node: React.ReactNode }> = [];
  if (structure?.has_pom_xml) structureItems.push({ key: "pom.xml", node: renderStructureStatusItem(true, "pom.xml") });
  if (structure?.has_build_gradle) structureItems.push({ key: "build.gradle", node: renderStructureStatusItem(true, "build.gradle") });
  if (structure?.has_src_main) structureItems.push({ key: "src/main", node: renderStructureStatusItem(true, "src/main") });
  if (structure?.has_src_test) structureItems.push({ key: "src/test", node: renderStructureStatusItem(true, "src/test") });
  if (detectedJavaVersion) structureItems.push({ key: "detected-java-version", node: renderStructureStatusItem(true, detectedJavaStructureLabel) });
  if (structure?.jsp_count && structure.jsp_count > 0) structureItems.push({ key: "jsp-count", node: renderStructureCountItem(structure.jsp_count, "JSP") });
  if (structure?.jsf_count && structure.jsf_count > 0) structureItems.push({ key: "jsf-count", node: renderStructureCountItem(structure.jsf_count, "JSF") });

  return (
    <div style={styles.structureBox}>
      <div style={{ ...styles.structureTitle, display: "flex", alignItems: "center", gap: 10 }}>
        <span
          className="wizard-icon-badge wizard-icon-badge-sm"
          style={buildWizardAccentVars("#2563eb")}
        >
          <FaListAlt />
        </span>
        <span>Project Structure Summary</span>
      </div>
      <div style={styles.structureGrid}>
        {structureItems.length > 0 ? (
          structureItems.map((item) => <React.Fragment key={item.key}>{item.node}</React.Fragment>)
        ) : (
          <div style={{ color: "#64748b" }}>No detected project structure elements</div>
        )}
      </div>
    </div>
  );
}

export function DiscoveryTechnicalSpecificationCard({
  styles,
  disabled,
  buttonLabel,
  helperText,
  onGenerate,
}: TechnicalSpecificationCardProps) {
  return (
    <div style={{ ...styles.documentCard, marginTop: 20 }}>
      <div style={styles.documentCardHeader}>
        <div style={styles.documentCardTitleRow}>
          <span
            className="wizard-icon-badge wizard-icon-badge-sm"
            style={buildWizardAccentVars("#2563eb")}
          >
            <FaFileAlt />
          </span>
          <div style={styles.documentCardTitle}>Technical Specification Document</div>
        </div>
        <div style={styles.documentCardSubtitle}>
          Generate a Technical specification document for this repository and download it directly as a PDF.
        </div>
      </div>
      <div style={styles.documentActionRow}>
        <button style={styles.primaryBtn} disabled={disabled} onClick={onGenerate}>
          {buttonLabel}
        </button>
      </div>
      <div style={styles.documentHelperText}>{helperText}</div>
    </div>
  );
}

export function DiscoveryNotJavaAlert({ onChooseDifferentRepository }: DiscoveryNotJavaAlertProps) {
  return (
    <div
      style={{
        background: "#fef2f2",
        border: "2px solid #ef4444",
        borderRadius: 12,
        padding: 20,
        marginBottom: 24,
        display: "flex",
        alignItems: "flex-start",
        gap: 16,
      }}
    >
      <span style={{ fontSize: 32, display: "inline-flex", color: "#dc2626" }}><FaExclamationTriangle /></span>
      <div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#991b1b", marginBottom: 8 }}>
          This is not a Java Project
        </div>
        <div style={{ fontSize: 14, color: "#b91c1c", lineHeight: 1.6 }}>
          The repository you connected does not appear to be a Java project. This tool is designed
          specifically for Java application migration. Please connect a repository that contains Java
          source code, Maven (pom.xml), or Gradle (build.gradle) configuration files.
        </div>
        <button
          style={{
            marginTop: 16,
            backgroundColor: "#ef4444",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "10px 20px",
            fontWeight: 600,
            cursor: "pointer",
            fontSize: 14,
          }}
          onClick={onChooseDifferentRepository}
        >
          Connect Different Repository
        </button>
      </div>
    </div>
  );
}

export function DiscoveryNoFrameworkAlert({ isVisible }: DiscoveryNoFrameworkAlertProps) {
  if (!isVisible) {
    return null;
  }

  return (
    <div
      style={{
        background: "#fef9c3",
        border: "2px solid #facc15",
        borderRadius: 12,
        padding: 20,
        marginBottom: 24,
        display: "flex",
        alignItems: "flex-start",
        gap: 16,
      }}
    >
      <span style={{ fontSize: 32, display: "inline-flex", color: "#ca8a04" }}><FaInfoCircle /></span>
      <div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#92400e", marginBottom: 8 }}>
          Java Project Detected (No Framework)
        </div>
        <div style={{ fontSize: 14, color: "#a16207", lineHeight: 1.6 }}>
          This repository contains Java source files but no recognized framework was detected. You
          can still proceed with migration, but some automation features may be limited.
        </div>
      </div>
    </div>
  );
}

export function DiscoveryHighRiskWarning({
  isVisible,
  missingBuildFiles,
  missingJavaVersion,
  missingSrcMain,
  sourceVersionStatus,
  suggestedJavaVersion,
  buildConversionLabel,
  buildConversionNote,
  onSuggestedJavaVersionChange,
  onConfirm,
  onChooseDifferentRepository,
}: DiscoveryHighRiskWarningProps) {
  if (!isVisible) {
    return null;
  }

  return (
    <div
      style={{
        background: "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)",
        border: "2px solid #f59e0b",
        borderRadius: 12,
        padding: 24,
        marginBottom: 24,
        boxShadow: "0 4px 12px rgba(245, 158, 11, 0.15)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
        <span style={{ fontSize: 40, display: "inline-flex", color: "#d97706" }}><FaExclamationTriangle /></span>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#92400e", marginBottom: 8 }}>
            High Risk Migration Detected
          </div>
          <div style={{ fontSize: 14, color: "#a16207", lineHeight: 1.7 }}>
            This project may be missing Java version configuration and may require additional setup:
          </div>
        </div>
      </div>

      <div
        style={{
          background: "rgba(255,255,255,0.7)",
          borderRadius: 8,
          padding: 16,
          marginBottom: 20,
        }}
      >
        <div style={{ fontWeight: 600, color: "#92400e", marginBottom: 12 }}>Missing Components:</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {missingBuildFiles && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 13,
                color: "#991b1b",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span><FaExclamationTriangle /></span> No pom.xml or build.gradle
            </div>
          )}
          {missingJavaVersion && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 13,
                color: "#991b1b",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span><FaExclamationTriangle /></span> Java version not detected
            </div>
          )}
          {missingSrcMain && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 13,
                color: "#991b1b",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span><FaExclamationTriangle /></span> Non-standard project structure
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          background: "rgba(255,255,255,0.7)",
          borderRadius: 8,
          padding: 16,
          marginBottom: 20,
        }}
      >
        <div style={{ fontWeight: 600, color: "#92400e", marginBottom: 12 }}>Suggested Configuration:</div>

        <div style={{ marginBottom: 16 }}>
          <label
            style={{ display: "block", fontSize: 13, fontWeight: 500, color: "#78350f", marginBottom: 6 }}
          >
            {sourceVersionStatus === "detected" ? "Java version automatically detected" : "Select Source Java Version:"}
          </label>
          {sourceVersionStatus === "detected" && suggestedJavaVersion !== "auto" ? (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                backgroundColor: "#f8fafc",
                minWidth: 200,
                color: "#0f172a",
              }}
            >
              Java {suggestedJavaVersion} detected from source code
            </div>
          ) : (
            <>
              <select
                value={suggestedJavaVersion}
                onChange={(event) => onSuggestedJavaVersionChange(event.target.value)}
                style={{
                  padding: "10px 14px",
                  borderRadius: 6,
                  border: "1px solid #d97706",
                  fontSize: 14,
                  backgroundColor: "#fff",
                  cursor: "pointer",
                  minWidth: 200,
                }}
              >
                <option value="auto">Auto-detect from code (Recommended)</option>
                <option value="7">Java 7 (Legacy)</option>
                <option value="8">Java 8 (LTS)</option>
                <option value="11">Java 11 (LTS)</option>
                <option value="17">Java 17 (LTS)</option>
                <option value="21">Java 21 (LTS)</option>
                <option value="22">Java 22</option>
                <option value="23">Java 23</option>
                <option value="24">Java 24</option>
                <option value="25">Java 25 (LTS)</option>
              </select>
              <div style={{ fontSize: 11, color: "#a16207", marginTop: 6 }}>
                Auto-detect analyzes your code to determine the correct Java version
              </div>
            </>
          )}
        </div>

        <div style={{ marginBottom: 16, padding: 16, borderRadius: 8, backgroundColor: "#eef2ff", border: "1px solid #c7d2fe" }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#1e3a8a" }}>{buildConversionLabel}</div>
          <div style={{ fontSize: 12, color: "#475569", marginTop: 8 }}>{buildConversionNote}</div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <button
          onClick={onConfirm}
          style={{
            backgroundColor: "#f59e0b",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "12px 24px",
            fontWeight: 600,
            cursor: "pointer",
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          {buildConversionLabel}
        </button>
        <button
          onClick={onChooseDifferentRepository}
          style={{
            backgroundColor: "#fff",
            color: "#92400e",
            border: "2px solid #f59e0b",
            borderRadius: 8,
            padding: "12px 24px",
            fontWeight: 600,
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          Choose Different Repository
        </button>
      </div>
    </div>
  );
}

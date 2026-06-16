import { useState } from "react";
import { readSessionJson, type PersistedWizardFormState, WIZARD_REPO_ANALYSIS_KEY } from "../utils/migrationWizardStorage";
import type {
  MicroserviceEligibilityResult,
  RepoAnalysis,
  RepoFile,
} from "../services/api";

type MicroserviceAccordionKey =
  | "signals"
  | "scores"
  | "services"
  | "concerns"
  | "strategy"
  | "observations";

export function useDiscoveryState(
  persistedFormState: PersistedWizardFormState | null,
  createDefaultMicroserviceAccordionState: () => Record<MicroserviceAccordionKey, boolean>
) {
  const [repoAnalysis, setRepoAnalysis] = useState<RepoAnalysis | null>(() =>
    readSessionJson<RepoAnalysis>(WIZARD_REPO_ANALYSIS_KEY)
  );
  const [repoFiles, setRepoFiles] = useState<RepoFile[]>([]);
  const [currentPath, setCurrentPath] = useState(persistedFormState?.currentPath ?? "");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisElapsedSeconds, setAnalysisElapsedSeconds] = useState(0);
  const [microserviceResult, setMicroserviceResult] = useState<MicroserviceEligibilityResult | null>(null);
  const [microserviceLoading, setMicroserviceLoading] = useState(false);
  const [microserviceAccordionState, setMicroserviceAccordionState] = useState<Record<MicroserviceAccordionKey, boolean>>(
    createDefaultMicroserviceAccordionState
  );
  const [isMicroserviceEligibilityCollapsed, setIsMicroserviceEligibilityCollapsed] = useState(false);
  const [showAllMicroserviceServices, setShowAllMicroserviceServices] = useState(false);
  const [activeScoreTooltip, setActiveScoreTooltip] = useState<string | null>(null);
  const [activeServiceTagTooltip, setActiveServiceTagTooltip] = useState<string | null>(null);
  const [microserviceExpandedSections, setMicroserviceExpandedSections] = useState<Record<string, boolean>>({});
  const [analysisStartedAtMs, setAnalysisStartedAtMs] = useState<number | null>(null);
  const [analysisCompletedSeconds, setAnalysisCompletedSeconds] = useState(
    persistedFormState?.analysisCompletedSeconds ?? 0
  );
  const [riskLevel, setRiskLevel] = useState(persistedFormState?.riskLevel ?? "");
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>(
    persistedFormState?.selectedFrameworks ?? []
  );
  const [isJavaProject, setIsJavaProject] = useState<boolean | null>(
    persistedFormState?.isJavaProject ?? null
  );
  const [selectedFile, setSelectedFile] = useState<RepoFile | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [editedContent, setEditedContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [pathHistory, setPathHistory] = useState<string[]>(
    persistedFormState?.pathHistory?.length ? persistedFormState.pathHistory : [""]
  );
  const [showFileExplorer, setShowFileExplorer] = useState(true);
  const [isHighRiskProject, setIsHighRiskProject] = useState(
    persistedFormState?.isHighRiskProject ?? false
  );
  const [highRiskConfirmed, setHighRiskConfirmed] = useState(
    persistedFormState?.highRiskConfirmed ?? false
  );
  const [suggestedJavaVersion, setSuggestedJavaVersion] = useState(
    persistedFormState?.suggestedJavaVersion ?? "auto"
  );
  const [detectedFrameworks, setDetectedFrameworks] = useState<{ name: string; path: string; type: string }[]>(
    persistedFormState?.detectedFrameworks ?? []
  );
  const [viewingFrameworkFile, setViewingFrameworkFile] = useState<{ name: string; path: string; content: string } | null>(null);
  const [frameworkFileLoading, setFrameworkFileLoading] = useState(false);
  const [repoPreviewInitialized, setRepoPreviewInitialized] = useState(false);
  const [microserviceAssessmentResolved, setMicroserviceAssessmentResolved] = useState(false);

  return {
    repoAnalysis,
    setRepoAnalysis,
    repoFiles,
    setRepoFiles,
    currentPath,
    setCurrentPath,
    analysisLoading,
    setAnalysisLoading,
    analysisElapsedSeconds,
    setAnalysisElapsedSeconds,
    microserviceResult,
    setMicroserviceResult,
    microserviceLoading,
    setMicroserviceLoading,
    microserviceAccordionState,
    setMicroserviceAccordionState,
    isMicroserviceEligibilityCollapsed,
    setIsMicroserviceEligibilityCollapsed,
    showAllMicroserviceServices,
    setShowAllMicroserviceServices,
    activeScoreTooltip,
    setActiveScoreTooltip,
    activeServiceTagTooltip,
    setActiveServiceTagTooltip,
    microserviceExpandedSections,
    setMicroserviceExpandedSections,
    analysisStartedAtMs,
    setAnalysisStartedAtMs,
    analysisCompletedSeconds,
    setAnalysisCompletedSeconds,
    riskLevel,
    setRiskLevel,
    selectedFrameworks,
    setSelectedFrameworks,
    isJavaProject,
    setIsJavaProject,
    selectedFile,
    setSelectedFile,
    fileContent,
    setFileContent,
    editedContent,
    setEditedContent,
    isEditing,
    setIsEditing,
    fileLoading,
    setFileLoading,
    pathHistory,
    setPathHistory,
    showFileExplorer,
    setShowFileExplorer,
    isHighRiskProject,
    setIsHighRiskProject,
    highRiskConfirmed,
    setHighRiskConfirmed,
    suggestedJavaVersion,
    setSuggestedJavaVersion,
    detectedFrameworks,
    setDetectedFrameworks,
    viewingFrameworkFile,
    setViewingFrameworkFile,
    frameworkFileLoading,
    setFrameworkFileLoading,
    repoPreviewInitialized,
    setRepoPreviewInitialized,
    microserviceAssessmentResolved,
    setMicroserviceAssessmentResolved,
  };
}

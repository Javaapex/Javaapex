import { useState } from "react";
import type { MigrationPreview, MigrationResult, FossaScanResult } from "../services/api";
import { readSessionJson, WIZARD_MIGRATION_JOB_KEY } from "../utils/migrationWizardStorage";

type GeneratedDocumentKind = "brd";
type DocumentPrefetchStatus = "idle" | "loading" | "ready" | "error";

interface DiffLineEntry {
  type: "add" | "remove" | "context" | "hunk";
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
}

interface CodeChangeEntry {
  fileName: string;
  filePath: string;
  changeType: "modified" | "added" | "deleted";
  additions: number;
  deletions: number;
  oldContent: string;
  newContent: string;
  diffLines: DiffLineEntry[];
}

interface PrefetchedBrdDocument {
  filename: string;
  html: string;
}

const REPORT_DIFFS_PAGE_SIZE = 25;

export function useMigrationExecution() {
  const [loading, setLoading] = useState(false);
  const [migrationTimerNow, setMigrationTimerNow] = useState(() => Date.now());
  const [migrationJob, setMigrationJob] = useState<MigrationResult | null>(() =>
    readSessionJson<MigrationResult>(WIZARD_MIGRATION_JOB_KEY)
  );
  const [migrationDetailLoadedJobId, setMigrationDetailLoadedJobId] = useState<string | null>(null);
  const [migrationLogs, setMigrationLogs] = useState<string[]>([]);
  const [fossaResult, setFossaResult] = useState<FossaScanResult | null>(null);
  const [fossaLoading, setFossaLoading] = useState(false);
  const [rerunTestsLoading, setRerunTestsLoading] = useState(false);
  const [migrationPreview, setMigrationPreview] = useState<MigrationPreview | null>(null);
  const [codeChanges, setCodeChanges] = useState<CodeChangeEntry[]>([]);
  const [selectedDiffFile, setSelectedDiffFile] = useState<string | null>(null);
  const [showCodeChanges, setShowCodeChanges] = useState(true);
  const [visibleReportDiffCount, setVisibleReportDiffCount] = useState(REPORT_DIFFS_PAGE_SIZE);
  const [reportDependencyPage, setReportDependencyPage] = useState(1);
  const [reportAccordionState, setReportAccordionState] = useState({
    summary: true,
    files: true,
    dependencies: true,
    sonar: true,
    fossa: true,
    issues: true,
  });
  const [documentGenerationLoading, setDocumentGenerationLoading] = useState<GeneratedDocumentKind | null>(null);
  const [documentPrefetchStatus, setDocumentPrefetchStatus] = useState<DocumentPrefetchStatus>("idle");
  const [prefetchedBrdDocument, setPrefetchedBrdDocument] = useState<PrefetchedBrdDocument | null>(null);
  const [animationProgress, setAnimationProgress] = useState(0);

  return {
    loading,
    setLoading,
    migrationTimerNow,
    setMigrationTimerNow,
    migrationJob,
    setMigrationJob,
    migrationDetailLoadedJobId,
    setMigrationDetailLoadedJobId,
    migrationLogs,
    setMigrationLogs,
    fossaResult,
    setFossaResult,
    fossaLoading,
    setFossaLoading,
    rerunTestsLoading,
    setRerunTestsLoading,
    migrationPreview,
    setMigrationPreview,
    codeChanges,
    setCodeChanges,
    selectedDiffFile,
    setSelectedDiffFile,
    showCodeChanges,
    setShowCodeChanges,
    visibleReportDiffCount,
    setVisibleReportDiffCount,
    reportDependencyPage,
    setReportDependencyPage,
    reportAccordionState,
    setReportAccordionState,
    documentGenerationLoading,
    setDocumentGenerationLoading,
    documentPrefetchStatus,
    setDocumentPrefetchStatus,
    prefetchedBrdDocument,
    setPrefetchedBrdDocument,
    animationProgress,
    setAnimationProgress,
  };
}

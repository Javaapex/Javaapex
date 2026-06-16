import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  getLocalProjectCapabilities,
  uploadLocalProject,
  uploadLocalProjectChunk,
  type LocalProjectAnalysisResponse,
  type LocalProjectCapabilities,
  type RepoAnalysis,
  type RepoFile,
  type RepoInfo,
} from "../services/api";
import {
  readPersistedValue,
  readSessionJson,
  WIZARD_REPO_URL_KEY,
  WIZARD_SELECTED_REPO_KEY,
} from "../utils/migrationWizardStorage";

type AccessTokenValidationState = "idle" | "validating" | "valid" | "invalid";

type TargetRepoNamesByApproach = {
  fork: string;
  branch: string;
  local: string;
};

type TargetRepoNameEditedByApproach = {
  fork: boolean;
  branch: boolean;
  local: boolean;
};

interface UseRepositoryConnectParams {
  persistedIsPrivateRepo?: boolean;
  persistedPatToken?: string;
  setRepoAnalysis: Dispatch<SetStateAction<RepoAnalysis | null>>;
  setRepoFiles: Dispatch<SetStateAction<RepoFile[]>>;
  setStep: Dispatch<SetStateAction<number>>;
  setError: Dispatch<SetStateAction<string>>;
  resetRepositorySelectionState: () => void;
  setTargetRepoNamesByApproach: Dispatch<SetStateAction<TargetRepoNamesByApproach>>;
  setTargetRepoNameEditedByApproach: Dispatch<SetStateAction<TargetRepoNameEditedByApproach>>;
  setTargetRepoNameError: Dispatch<SetStateAction<string>>;
  buildLocalRepoRef: (value: string) => string;
  getPathBasename: (value: string) => string;
  isLocalRepoRef: (value: string | null | undefined) => boolean;
  loadZipSync: () => Promise<typeof import("fflate")["zipSync"]>;
}

const MAX_LOCAL_PROJECT_UPLOAD_FILES = 25000;
const MAX_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 1024 * 1024 * 1024;
const AUTO_ZIP_LOCAL_PROJECT_UPLOAD_FILES = 15000;
const AUTO_ZIP_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 150 * 1024 * 1024;
const CHUNK_UPLOAD_SIZE_BYTES = 60 * 1024 * 1024;
const WARN_LOCAL_PROJECT_UPLOAD_FILES = 500;
const WARN_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 150 * 1024 * 1024;

const isEnterpriseGithub = (url: string) => {
  const match = url.match(/^https?:\/\/(www\.)?github\.([^.]+)\.com\//i);
  return match && match[2] !== "" && match[2] !== "com";
};

const normalizeGithubUrl = (url: string): { valid: boolean; normalizedUrl: string; message: string } => {
  if (!url.trim()) {
    return { valid: false, normalizedUrl: "", message: "URL is required" };
  }

  let normalized = url.trim();
  // Strip URL fragments (#...) and query strings (?...) — never part of a repo path
  normalized = normalized.replace(/[#?].*$/, "");
  normalized = normalized.replace(/\/tree\/[^/]+.*$/, "");
  normalized = normalized.replace(/\/blob\/[^/]+.*$/, "");
  normalized = normalized.replace(/\/src\/.*$/, "");
  normalized = normalized.replace(/\/$/, "");
  normalized = normalized.replace(/\.git$/, "");

  const isGithubUrl = /^https?:\/\/(www\.)?github(\.[^/]+)?\.com\/[^/]+\/[^/\s]+$/.test(normalized);
  const isGitlabUrl = /^https?:\/\/(www\.)?gitlab\.com\/[^/]+\/[^/\s]+$/.test(normalized);
  const isShortFormat = /^[^/]+\/[^/\s]+$/.test(normalized);

  if (isGithubUrl || isGitlabUrl || isShortFormat) {
    if (url !== normalized) {
      return {
        valid: true,
        normalizedUrl: normalized,
        message: "URL normalized (removed tree/blob paths)",
      };
    }
    return { valid: true, normalizedUrl: normalized, message: "" };
  }

  return {
    valid: false,
    normalizedUrl: "",
    message: "Invalid URL format. Use: https://github.com/owner/repo, https://github.<enterprise>.com/owner/repo, or owner/repo",
  };
};

export function useRepositoryConnect({
  persistedIsPrivateRepo,
  persistedPatToken,
  setRepoAnalysis,
  setRepoFiles,
  setStep,
  setError,
  resetRepositorySelectionState,
  setTargetRepoNamesByApproach,
  setTargetRepoNameEditedByApproach,
  setTargetRepoNameError,
  buildLocalRepoRef,
  getPathBasename,
  isLocalRepoRef,
  loadZipSync,
}: UseRepositoryConnectParams) {
  const [repoUrl, setRepoUrl] = useState(() => {
    if (typeof window === "undefined") return "";
    return readPersistedValue(WIZARD_REPO_URL_KEY) || "";
  });
  const [selectedRepo, setSelectedRepo] = useState<RepoInfo | null>(() =>
    readSessionJson<RepoInfo>(WIZARD_SELECTED_REPO_KEY)
  );
  const [githubToken, setGithubToken] = useState("");
  const [isPrivateRepo, setIsPrivateRepo] = useState(persistedIsPrivateRepo ?? false);
  const [patToken, setPatToken] = useState(persistedPatToken ?? "");
  const [repoAccessCheckLoading, setRepoAccessCheckLoading] = useState(false);
  const [accessTokenValidationState, setAccessTokenValidationState] =
    useState<AccessTokenValidationState>("idle");
  const [accessTokenValidationMessage, setAccessTokenValidationMessage] = useState("");
  const [localProjectCapabilities, setLocalProjectCapabilities] = useState<LocalProjectCapabilities | null>(null);
  const [localProjectCapabilitiesLoading, setLocalProjectCapabilitiesLoading] = useState(false);
  const [localProjectUploadFiles, setLocalProjectUploadFiles] = useState<File[]>([]);
  const [localProjectUploadLoading, setLocalProjectUploadLoading] = useState(false);
  const [localProjectUploadCompressing, setLocalProjectUploadCompressing] = useState(false);
  const [localProjectUploadError, setLocalProjectUploadError] = useState("");
  const [localProjectUploadWarning, setLocalProjectUploadWarning] = useState("");

  const urlValidation = repoUrl ? normalizeGithubUrl(repoUrl) : { valid: false, normalizedUrl: "", message: "" };
  const showEnterpriseToken = repoUrl && isEnterpriseGithub(urlValidation.normalizedUrl || repoUrl);
  const activeAccessToken = (showEnterpriseToken ? githubToken : patToken).trim();
  const repositoryNeedsAuthentication = Boolean(showEnterpriseToken || isPrivateRepo);
  const currentToken = useMemo(() => {
    if (showEnterpriseToken) return githubToken.trim();
    if (isPrivateRepo) return patToken.trim() || githubToken.trim();
    if (githubToken.trim()) return githubToken.trim();
    if (patToken.trim()) return patToken.trim();
    return "";
  }, [githubToken, patToken, showEnterpriseToken, isPrivateRepo]);
  const shouldShowPatInput = showEnterpriseToken || isPrivateRepo;

  const resetAccessTokenValidationState = () => {
    setAccessTokenValidationState("idle");
    setAccessTokenValidationMessage("");
  };

  const handleRepositoryContinue = async () => {
    if (!urlValidation.valid) return;

    const normalizedUrl = urlValidation.normalizedUrl;
    const token = currentToken.trim();

    if (showEnterpriseToken && !token) {
      setError("");
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage("Enter a GitHub Personal Access Token to analyze this GitHub Enterprise repository.");
      return;
    }

    if (isPrivateRepo && !token) {
      setError("");
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage("Enter a GitHub Personal Access Token with repo scope to analyze this private repository.");
      return;
    }

    resetRepositorySelectionState();
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoNameError("");
    setSelectedRepo({
      name: normalizedUrl.split("/").pop() || "",
      full_name: normalizedUrl
        .replace(/^https?:\/\/(www\.)?github\.com\//, "")
        .replace(/^https?:\/\/(www\.)?gitlab\.com\//, ""),
      url: normalizedUrl,
      default_branch: "main",
      language: "Java",
      description: "",
    });
    setStep(2);
  };

  const shouldCompressLocalProjectUpload = (files: File[]) => {
    if (files.length === 1 && files[0].name.toLowerCase().endsWith(".zip")) {
      return false;
    }
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    return (
      files.length > AUTO_ZIP_LOCAL_PROJECT_UPLOAD_FILES ||
      totalSize > AUTO_ZIP_LOCAL_PROJECT_UPLOAD_SIZE_BYTES
    );
  };

  const zipLocalProjectFiles = async (files: File[]): Promise<Blob> => {
    const entries: Record<string, Uint8Array> = {};
    for (const file of files) {
      const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
      const arrayBuffer = await file.arrayBuffer();
      entries[relativePath || file.name] = new Uint8Array(arrayBuffer);
    }
    const zipSync = await loadZipSync();
    const zipped = zipSync(entries, { level: 3 });
    const zipBytes = new Uint8Array(zipped.byteLength);
    zipBytes.set(zipped);
    return new Blob([zipBytes], { type: "application/zip" });
  };

  const handleLocalProjectFilesChange = (files: FileList | null) => {
    if (!files) {
      setLocalProjectUploadFiles([]);
      setLocalProjectUploadError("");
      setLocalProjectUploadWarning("");
      return;
    }

    const fileArray = Array.from(files);
    const totalSize = fileArray.reduce((sum, file) => sum + file.size, 0);

    if (fileArray.length > MAX_LOCAL_PROJECT_UPLOAD_FILES || totalSize > MAX_LOCAL_PROJECT_UPLOAD_SIZE_BYTES) {
      setLocalProjectUploadFiles(fileArray);
      setLocalProjectUploadError(
        `Selected folder is too large to upload directly (${fileArray.length} files, ${(totalSize / (1024 * 1024)).toFixed(1)} MB). Please upload a ZIP archive instead.`
      );
      setLocalProjectUploadWarning("");
      setError("");
      return;
    }

    const shouldCompress = shouldCompressLocalProjectUpload(fileArray);
    let warningMessage = "";
    if (shouldCompress) {
      warningMessage = `Selected folder contains ${fileArray.length} files and ${(totalSize / (1024 * 1024)).toFixed(1)} MB. It will be compressed to ZIP before uploading to improve reliability.`;
    } else if (fileArray.length > WARN_LOCAL_PROJECT_UPLOAD_FILES || totalSize > WARN_LOCAL_PROJECT_UPLOAD_SIZE_BYTES) {
      warningMessage = `Selected folder contains ${fileArray.length} files and ${(totalSize / (1024 * 1024)).toFixed(1)} MB. Upload may take a long time, but it is allowed.`;
    }

    setLocalProjectUploadFiles(fileArray);
    setLocalProjectUploadError("");
    setLocalProjectUploadWarning(warningMessage);
    setError("");

    if (selectedRepo && isLocalRepoRef(selectedRepo.url)) {
      setSelectedRepo(null);
      setRepoAnalysis(null);
    }
  };

  const handleLocalProjectUpload = async () => {
    if (localProjectUploadFiles.length === 0 || localProjectUploadError) return;

    setLocalProjectUploadLoading(true);
    setLocalProjectUploadCompressing(false);
    setLocalProjectUploadError("");
    setLocalProjectUploadWarning("");
    setError("");

    const localFiles = localProjectUploadFiles;
    const shouldCompress = shouldCompressLocalProjectUpload(localFiles);
    const uploadFiles = async (zip: boolean) => {
      const formData = new FormData();
      if (zip) {
        setLocalProjectUploadCompressing(true);
        const zipBlob = await zipLocalProjectFiles(localFiles);

        if (zipBlob.size > CHUNK_UPLOAD_SIZE_BYTES) {
          const totalChunks = Math.ceil(zipBlob.size / CHUNK_UPLOAD_SIZE_BYTES);
          const uploadId = globalThis.crypto?.randomUUID?.() ?? `upload-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
          let finalResponse: LocalProjectAnalysisResponse | null = null;

          for (let index = 0; index < totalChunks; index++) {
            const start = index * CHUNK_UPLOAD_SIZE_BYTES;
            const end = Math.min(start + CHUNK_UPLOAD_SIZE_BYTES, zipBlob.size);
            const chunkBlob = zipBlob.slice(start, end);
            const result = await uploadLocalProjectChunk(
              uploadId,
              index + 1,
              totalChunks,
              chunkBlob,
              "local-project.zip",
            );

            if (index === totalChunks - 1) {
              finalResponse = result as LocalProjectAnalysisResponse;
            }
          }

          if (!finalResponse) {
            throw new Error("Failed to complete chunked upload");
          }

          return finalResponse;
        }

        formData.append("zip_file", zipBlob, "local-project.zip");
        setLocalProjectUploadCompressing(false);
      } else {
        localFiles.forEach((file) => formData.append("files", file, file.webkitRelativePath || file.name));
      }

      return uploadLocalProject(formData);
    };

    let result: LocalProjectAnalysisResponse | undefined;
    let attemptedZipRetry = false;
    try {
      result = await uploadFiles(shouldCompress);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to upload local project";
      const isNetworkFailure =
        message === "Failed to fetch" ||
        message.includes("ERR_HTTP2_PROTOCOL_ERROR") ||
        message.includes("NetworkError");

      if (!shouldCompress && !attemptedZipRetry && isNetworkFailure && localFiles.length > 1) {
        attemptedZipRetry = true;
        try {
          result = await uploadFiles(true);
        } catch (retryErr) {
          const retryMessage = retryErr instanceof Error ? retryErr.message : "Failed to upload local project";
          setLocalProjectUploadError(
            retryMessage === "Failed to fetch"
              ? "Upload failed due to browser or network limits. Try uploading a ZIP archive directly."
              : retryMessage
          );
        }
      } else {
        setLocalProjectUploadError(
          message === "Failed to fetch"
            ? "Upload failed due to browser or network limits. Try uploading a ZIP archive directly."
            : message
        );
      }
    } finally {
      setLocalProjectUploadCompressing(false);
      setLocalProjectUploadLoading(false);
    }

    if (!result) return;

    const uploadedRepoUrl = result.project_path.startsWith("local://")
      ? result.project_path
      : buildLocalRepoRef(result.project_path);

    resetRepositorySelectionState();
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoNameError("");
    setSelectedRepo({
      name: result.project_name || getPathBasename(localProjectUploadFiles[0]?.webkitRelativePath || localProjectUploadFiles[0]?.name || "uploaded-project"),
      full_name: uploadedRepoUrl,
      url: uploadedRepoUrl,
      default_branch: "local",
      language: "Java",
      description: "Uploaded local project",
    });
    setRepoAnalysis(result.analysis);
    setRepoFiles([]);
    setStep(2);
  };

  useEffect(() => {
    let cancelled = false;
    setLocalProjectCapabilitiesLoading(true);
    getLocalProjectCapabilities()
      .then((capabilities) => {
        if (!cancelled) {
          setLocalProjectCapabilities(capabilities);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLocalProjectCapabilities(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLocalProjectCapabilitiesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return {
    repoUrl,
    setRepoUrl,
    selectedRepo,
    setSelectedRepo,
    githubToken,
    setGithubToken,
    isPrivateRepo,
    setIsPrivateRepo,
    patToken,
    setPatToken,
    repoAccessCheckLoading,
    setRepoAccessCheckLoading,
    accessTokenValidationState,
    setAccessTokenValidationState,
    accessTokenValidationMessage,
    setAccessTokenValidationMessage,
    localProjectCapabilities,
    localProjectCapabilitiesLoading,
    localProjectUploadFiles,
    setLocalProjectUploadFiles,
    localProjectUploadLoading,
    localProjectUploadCompressing,
    localProjectUploadError,
    setLocalProjectUploadError,
    localProjectUploadWarning,
    setLocalProjectUploadWarning,
    urlValidation,
    showEnterpriseToken,
    activeAccessToken,
    repositoryNeedsAuthentication,
    currentToken,
    shouldShowPatInput,
    resetAccessTokenValidationState,
    handleRepositoryContinue,
    handleLocalProjectFilesChange,
    handleLocalProjectUpload,
  };
}

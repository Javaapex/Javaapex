import React, { useState, useEffect, useCallback } from 'react';
import { 
  analyzeBusinessLogicWithLLM, 
  getFileImprovementSuggestion,
  type FileAnalysisResult,
  type HuggingFaceBusinessLogicResponse
} from '../services/api';

interface CodeQualityRefactoringCardProps {
  javaFiles: string[];
  repoUrl: string;
  githubToken: string;
  sourceVersion: string;
  targetVersion: string;
}

interface AnalysisState {
  loading: boolean;
  error: string | null;
  results: FileAnalysisResult[] | null;
  llmAvailable: boolean;
}

export default function CodeQualityRefactoringCard({
  javaFiles,
  repoUrl,
  githubToken,
  sourceVersion,
  targetVersion
}: CodeQualityRefactoringCardProps) {
  const [analysis, setAnalysis] = useState<AnalysisState>({
    loading: false,
    error: null,
    results: null,
    llmAvailable: false
  });
  
  const [selectedFile, setSelectedFile] = useState<FileAnalysisResult | null>(null);
  const [showSuggestions, setShowSuggestions] = useState<Record<string, boolean>>({});
  const [improvedCode, setImprovedCode] = useState<Record<string, string>>({});
  const [loadingSuggestion, setLoadingSuggestion] = useState<string | null>(null);

  // Trigger analysis when versions change
  const runAnalysis = useCallback(async () => {
    if (!repoUrl || javaFiles.length === 0) return;
    
    setAnalysis(prev => ({ ...prev, loading: true, error: null }));
    
    try {
      const response = await analyzeBusinessLogicWithLLM({
        repo_url: repoUrl,
        token: githubToken,
        source_java_version: sourceVersion,
        target_java_version: targetVersion,
        java_files: javaFiles.slice(0, 10) // Limit to 10 files
      });
      
      setAnalysis({
        loading: false,
        error: null,
        results: response.file_results,
        llmAvailable: response.llm_available
      });
    } catch (err: any) {
      setAnalysis({
        loading: false,
        error: err.message || 'Failed to analyze with LLM',
        results: null,
        llmAvailable: false
      });
    }
  }, [repoUrl, githubToken, sourceVersion, targetVersion, javaFiles]);

  // Run analysis on mount and when versions change
  useEffect(() => {
    if (parseInt(targetVersion) > parseInt(sourceVersion)) {
      runAnalysis();
    }
  }, [sourceVersion, targetVersion, runAnalysis]);

  // Get AI improvement suggestion for an issue
  const getImprovementSuggestion = async (issue: any, fileResult: FileAnalysisResult) => {
    const issueKey = `${fileResult.file_name}-${issue.line_number}`;
    setLoadingSuggestion(issueKey);
    
    try {
      const response = await getFileImprovementSuggestion({
        code_snippet: issue.code_snippet || issue.description,
        issue_description: issue.description
      });
      
      setImprovedCode(prev => ({
        ...prev,
        [issueKey]: response.improved_code
      }));
      setShowSuggestions(prev => ({
        ...prev,
        [issueKey]: true
      }));
    } catch (err) {
      console.error('Failed to get improvement suggestion:', err);
    } finally {
      setLoadingSuggestion(null);
    }
  };

  // Get severity color
  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high': return '#dc2626';
      case 'medium': return '#f59e0b';
      case 'low': return '#22c55e';
      default: return '#6b7280';
    }
  };

  // Get severity background color
  const getSeverityBgColor = (severity: string) => {
    switch (severity) {
      case 'high': return '#fef2f2';
      case 'medium': return '#fffbeb';
      case 'low': return '#f0fdf4';
      default: return '#f3f4f6';
    }
  };

  // Calculate totals
  const totalIssues = analysis.results?.reduce((sum, file) => sum + file.issues.length, 0) || 0;
  const totalOldPatterns = analysis.results?.reduce((sum, file) => sum + file.old_patterns_found.length, 0) || 0;
  const totalLines = analysis.results?.reduce((sum, file) => sum + file.total_lines, 0) || 0;

  if (analysis.loading) {
    return (
      <div style={{
        background: '#f8fafc',
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        padding: 24,
        marginTop: 16
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 24,
            height: 24,
            border: '3px solid #e2e8f0',
            borderTop: '3px solid #3b82f6',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite'
          }} />
          <span style={{ color: '#64748b', fontSize: 14 }}>
            🤖 Hugging Face LLM is analyzing your code for Java {sourceVersion} → {targetVersion} migration...
          </span>
        </div>
      </div>
    );
  }

  if (analysis.error) {
    return (
      <div style={{
        background: '#fef2f2',
        border: '1px solid #fecaca',
        borderRadius: 12,
        padding: 16,
        marginTop: 16
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 20 }}>⚠️</span>
          <span style={{ fontWeight: 600, color: '#991b1b' }}>Analysis Error</span>
        </div>
        <p style={{ color: '#b91c1c', fontSize: 13, margin: 0 }}>{analysis.error}</p>
        <button
          onClick={runAnalysis}
          style={{
            marginTop: 12,
            padding: '8px 16px',
            background: '#dc2626',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 13
          }}
        >
          Retry Analysis
        </button>
      </div>
    );
  }

  if (!analysis.results || analysis.results.length === 0) {
    return (
      <div style={{
        background: '#f0fdf4',
        border: '1px solid #86efac',
        borderRadius: 12,
        padding: 20,
        marginTop: 16
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 24 }}>✅</span>
          <div>
            <div style={{ fontWeight: 600, color: '#166534' }}>No Issues Found</div>
            <div style={{ fontSize: 13, color: '#22c55e', marginTop: 4 }}>
              Hugging Face LLM didn't detect any migration issues for Java {sourceVersion} → {targetVersion}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      background: '#fff',
      border: '1px solid #e2e8f0',
      borderRadius: 12,
      padding: 20,
      marginTop: 16,
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 20,
        paddingBottom: 16,
        borderBottom: '1px solid #e2e8f0'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 24 }}>🤖</span>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#1e293b' }}>
              Hugging Face LLM Code Analysis
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
              AI-powered analysis for Java {sourceVersion} → {targetVersion}
            </div>
          </div>
        </div>
        
        {/* Summary Stats */}
        <div style={{ display: 'flex', gap: 16 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#dc2626' }}>{totalIssues}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Issues Found</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#f59e0b' }}>{totalOldPatterns}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Old Patterns</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#3b82f6' }}>{analysis.results.length}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Files Analyzed</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#22c55e' }}>{totalLines}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Lines of Code</div>
          </div>
        </div>
      </div>

      {/* File Results */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {analysis.results.map((fileResult, fileIndex) => (
          <div
            key={fileIndex}
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 8,
              overflow: 'hidden'
            }}
          >
            {/* File Header */}
            <div
              onClick={() => setSelectedFile(selectedFile?.file_path === fileResult.file_path ? null : fileResult)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '14px 16px',
                cursor: 'pointer',
                background: selectedFile?.file_path === fileResult.file_path ? '#eff6ff' : '#f8fafc',
                borderBottom: selectedFile?.file_path === fileResult.file_path ? '1px solid #bfdbfe' : 'none'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 18 }}>☕</span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b' }}>
                    {fileResult.file_name}
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {fileResult.total_lines} lines • {fileResult.issues.length} issues • {fileResult.old_patterns_found.length} old patterns
                  </div>
                </div>
              </div>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {fileResult.issues.length > 0 && (
                  <span style={{
                    padding: '4px 10px',
                    backgroundColor: '#fef2f2',
                    color: '#dc2626',
                    borderRadius: 12,
                    fontSize: 11,
                    fontWeight: 600
                  }}>
                    {fileResult.issues.length} issues
                  </span>
                )}
                <span style={{ fontSize: 14, color: '#64748b' }}>
                  {selectedFile?.file_path === fileResult.file_path ? '▼' : '▶'}
                </span>
              </div>
            </div>

            {/* File Details */}
            {selectedFile?.file_path === fileResult.file_path && (
              <div style={{ padding: 16 }}>
                {/* Issues Section */}
                {fileResult.issues.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: '#374151',
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6
                    }}>
                      🐛 Issues Found ({fileResult.issues.length})
                    </div>
                    
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {fileResult.issues.map((issue, issueIndex) => {
                        const issueKey = `${fileResult.file_name}-${issue.line_number}`;
                        const isShowingSuggestion = showSuggestions[issueKey];
                        
                        return (
                          <div
                            key={issueIndex}
                            style={{
                              background: getSeverityBgColor(issue.severity),
                              border: `1px solid ${getSeverityColor(issue.severity)}30`,
                              borderRadius: 6,
                              padding: 12
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                              <span style={{
                                fontSize: 11,
                                padding: '2px 8px',
                                backgroundColor: getSeverityColor(issue.severity),
                                color: '#fff',
                                borderRadius: 4,
                                fontWeight: 600,
                                textTransform: 'uppercase'
                              }}>
                                {issue.severity}
                              </span>
                              
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 13, fontWeight: 500, color: '#1e293b' }}>
                                  Line {issue.line_number}: {issue.type}
                                </div>
                                <div style={{ fontSize: 12, color: '#4b5563', marginTop: 4 }}>
                                  {issue.description}
                                </div>
                                
                                {issue.code_snippet && (
                                  <code style={{
                                    display: 'block',
                                    marginTop: 8,
                                    padding: 8,
                                    background: '#1e293b',
                                    color: '#e5e7eb',
                                    borderRadius: 4,
                                    fontSize: 11,
                                    fontFamily: 'monospace',
                                    overflowX: 'auto'
                                  }}>
                                    {issue.code_snippet}
                                  </code>
                                )}
                                
                                {issue.suggested_fix && (
                                  <div style={{
                                    marginTop: 8,
                                    padding: 8,
                                    background: '#ecfdf5',
                                    borderRadius: 4,
                                    fontSize: 12,
                                    color: '#065f46'
                                  }}>
                                    <strong>💡 Suggestion:</strong> {issue.suggested_fix}
                                  </div>
                                )}
                                
                                {/* AI Improvement Button */}
                                <div style={{ marginTop: 10 }}>
                                  <button
                                    onClick={() => getImprovementSuggestion(issue, fileResult)}
                                    disabled={loadingSuggestion === issueKey}
                                    style={{
                                      padding: '6px 12px',
                                      background: '#3b82f6',
                                      color: '#fff',
                                      border: 'none',
                                      borderRadius: 4,
                                      cursor: loadingSuggestion === issueKey ? 'not-allowed' : 'pointer',
                                      fontSize: 12,
                                      opacity: loadingSuggestion === issueKey ? 0.6 : 1
                                    }}
                                  >
                                    {loadingSuggestion === issueKey ? 'Loading...' : '🤖 Get AI Improvement'}
                                  </button>
                                </div>
                                
                                {/* AI Improved Code */}
                                {isShowingSuggestion && improvedCode[issueKey] && (
                                  <div style={{
                                    marginTop: 12,
                                    padding: 12,
                                    background: '#f0f9ff',
                                    border: '1px solid #7dd3fc',
                                    borderRadius: 6
                                  }}>
                                    <div style={{
                                      fontSize: 12,
                                      fontWeight: 600,
                                      color: '#0369a1',
                                      marginBottom: 8
                                    }}>
                                      🤖 Hugging Face LLM Suggested Improvement:
                                    </div>
                                    <code style={{
                                      display: 'block',
                                      padding: 10,
                                      background: '#1e293b',
                                      color: '#4ade80',
                                      borderRadius: 4,
                                      fontSize: 11,
                                      fontFamily: 'monospace',
                                      overflowX: 'auto',
                                      whiteSpace: 'pre-wrap'
                                    }}>
                                      {improvedCode[issueKey]}
                                    </code>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Old Patterns Section */}
                {fileResult.old_patterns_found.length > 0 && (
                  <div>
                    <div style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: '#374151',
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6
                    }}>
                      📋 Old Patterns Found ({fileResult.old_patterns_found.length})
                    </div>
                    
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {fileResult.old_patterns_found.map((pattern, patternIndex) => (
                        <div
                          key={patternIndex}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: 10,
                            background: '#fffbeb',
                            border: '1px solid #fcd34d',
                            borderRadius: 6
                          }}
                        >
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 500, color: '#92400e' }}>
                              {pattern.pattern}
                            </div>
                            <div style={{ fontSize: 11, color: '#a16207', marginTop: 2 }}>
                              {pattern.message}
                            </div>
                          </div>
                          <span style={{
                            padding: '2px 8px',
                            backgroundColor: '#fef3c7',
                            color: '#92400e',
                            borderRadius: 10,
                            fontSize: 11,
                            fontWeight: 600
                          }}>
                            {pattern.occurrences}×
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Refresh Button */}
      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <button
          onClick={runAnalysis}
          disabled={analysis.loading}
          style={{
            padding: '8px 16px',
            background: '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: analysis.loading ? 'not-allowed' : 'pointer',
            fontSize: 13,
            opacity: analysis.loading ? 0.6 : 1
          }}
        >
          🔄 Refresh Analysis
        </button>
      </div>
    </div>
  );
}

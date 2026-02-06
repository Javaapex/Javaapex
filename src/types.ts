export interface MigrationRequest {
  gitRepoUrl: string;
  sourceJavaVersion: string;
  targetJavaVersion: string;
  email: string;
}

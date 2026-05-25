param(
    [string]$ImageName = "javaapex-backend:local",
    [int]$Port = 10000
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or not available on PATH."
}

$backendRoot = $PSScriptRoot
$envFile = Join-Path $backendRoot ".env"

Write-Host "Building backend Docker image: $ImageName"
docker build -t $ImageName $backendRoot

$runArgs = @("run", "--rm", "-p", "$Port`:10000")
if (Test-Path -LiteralPath $envFile) {
    $runArgs += @("--env-file", $envFile)
}
$runArgs += $ImageName

Write-Host "Starting backend container on http://localhost:$Port"
docker @runArgs

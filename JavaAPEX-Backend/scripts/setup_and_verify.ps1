<#
  setup_and_verify.ps1 - idempotent toolchain + Velocity Layer 1 verification.

  Implements the JavaAPEX functional-test closure steps 1-5:
    1. Detect JDK (>=11) + Maven; skip install if already present.
    2. Install JDK 17 + Maven with a no-admin fallback chain:
         a) winget   b) choco   c) portable Temurin/Maven .zip under
            C:\Users\<you>\tools\ with user-scope setx (no admin).
    3. Refresh env (process-scope) and re-verify.
    4. Test Maven Central reachability (mvn dependency:resolve). On a
       connection/timeout/blocked-host error, install the Ford Nexus
       settings.xml template and try 'mvn dependency:go-offline'.
    5. Generate the Velocity Layer 1 project and run 'mvn test'; report
       pass/fail + compile errors.

  Safe to re-run. Never requires elevation unless a step genuinely cannot
  proceed (explicitly reported). Logging: [STEP] / [OK] / [FAIL] / [WARN].

  Usage:
    powershell -ExecutionPolicy Bypass -File .\setup_and_verify.ps1
#>
[CmdletBinding()]
param(
  [string]$BackendDir = "$PSScriptRoot",
  [string]$ToolsRoot  = "$env:USERPROFILE\tools",
  [string]$JdkZipUrl  = "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jdk_x64_windows_hotspot_17.0.11_9.zip",
  [string]$MvnZipUrl  = "https://dlcdn.apache.org/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.zip"
)

$ErrorActionPreference = 'Stop'
function Step($m){ Write-Host "[STEP] $m" -ForegroundColor Cyan }
function Ok  ($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "[FAIL] $m" -ForegroundColor Red }

# If invoked from scripts/, the backend dir is the parent.
if ((Split-Path -Leaf $BackendDir) -eq 'scripts') { $BackendDir = Split-Path -Parent $BackendDir }

function Test-Cmd([string]$exe, [string]$verArg){
  try { & $exe $verArg 2>&1 | Out-String } catch { return $null }
}

function Get-JavaMajor([string]$verText){
  if (-not $verText) { return 0 }
  if ($verText -match 'version "(\d+)(?:\.(\d+))?') {
    $maj = [int]$Matches[1]
    if ($maj -eq 1 -and $Matches[2]) { return [int]$Matches[2] }  # 1.8 -> 8
    return $maj
  }
  return 0
}

function Add-UserPath([string]$dir){
  if (-not (Test-Path $dir)) { return }
  $cur = [Environment]::GetEnvironmentVariable('Path','User')
  if ($cur -notlike "*$dir*") {
    [Environment]::SetEnvironmentVariable('Path', ($cur.TrimEnd(';') + ";$dir"), 'User')
    Ok "Added to user PATH: $dir"
  }
  if ($env:Path -notlike "*$dir*") { $env:Path = "$dir;$env:Path" }  # process scope now
}

# ---------------------------------------------------------------------------
# STEP 1 - detect existing toolchain
# ---------------------------------------------------------------------------
Step "1. Detecting existing toolchain (java, mvn)"
$javaVer = Test-Cmd 'java' '-version'
$mvnVer  = Test-Cmd 'mvn'  '-v'
$javaMajor = Get-JavaMajor $javaVer
$haveJava = $javaMajor -ge 11
$haveMvn  = [bool]($mvnVer -match 'Apache Maven')

if ($haveJava) { Ok "JDK $javaMajor detected" } else { Warn "No usable JDK (>=11) found" }
if ($haveMvn)  { Ok "Maven detected" }          else { Warn "Maven not found" }

# ---------------------------------------------------------------------------
# STEP 2 - install if needed (no-admin fallback chain)
# ---------------------------------------------------------------------------
if (-not ($haveJava -and $haveMvn)) {
  Step "2. Installing JDK 17 + Maven (fallback chain: winget -> choco -> portable)"

  $installed = $false

  # a) winget
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    try {
      if (-not $haveJava) { winget install --id Microsoft.OpenJDK.17 -e --accept-source-agreements --accept-package-agreements --scope user }
      if (-not $haveMvn)  { winget install --id Apache.Maven -e --accept-source-agreements --accept-package-agreements --scope user }
      $installed = $true; Ok "winget install attempted"
    } catch { Warn "winget path failed: $($_.Exception.Message)" }
  } else { Warn "winget not available" }

  # b) chocolatey
  if (-not $installed -and (Get-Command choco -ErrorAction SilentlyContinue)) {
    try { choco install temurin17 maven -y; $installed = $true; Ok "choco install attempted" }
    catch { Warn "choco path failed: $($_.Exception.Message)" }
  } elseif (-not $installed) { Warn "choco not available" }

  # c) portable manual install (no admin)
  if (-not $installed) {
    Warn "Falling back to portable .zip install under $ToolsRoot (no admin)"
    New-Item -ItemType Directory -Force -Path $ToolsRoot | Out-Null
    try {
      if (-not $haveJava) {
        $jdkZip = Join-Path $ToolsRoot 'jdk17.zip'
        Invoke-WebRequest -Uri $JdkZipUrl -OutFile $jdkZip
        Expand-Archive -Path $jdkZip -DestinationPath $ToolsRoot -Force
        $jdkHome = (Get-ChildItem $ToolsRoot -Directory -Filter 'jdk-17*' | Select-Object -First 1).FullName
        [Environment]::SetEnvironmentVariable('JAVA_HOME', $jdkHome, 'User'); $env:JAVA_HOME = $jdkHome
        Add-UserPath (Join-Path $jdkHome 'bin')
        Ok "Portable JDK 17 at $jdkHome"
      }
      if (-not $haveMvn) {
        $mvnZip = Join-Path $ToolsRoot 'maven.zip'
        Invoke-WebRequest -Uri $MvnZipUrl -OutFile $mvnZip
        Expand-Archive -Path $mvnZip -DestinationPath $ToolsRoot -Force
        $mvnHome = (Get-ChildItem $ToolsRoot -Directory -Filter 'apache-maven-*' | Select-Object -First 1).FullName
        [Environment]::SetEnvironmentVariable('M2_HOME', $mvnHome, 'User'); $env:M2_HOME = $mvnHome
        Add-UserPath (Join-Path $mvnHome 'bin')
        Ok "Portable Maven at $mvnHome"
      }
    } catch {
      Fail "Portable install failed (likely the download host is also firewalled): $($_.Exception.Message)"
      Fail "STOP: cannot obtain a JDK/Maven without network or a pre-provisioned toolchain. Escalate to IT for a corporate JDK 17 + Maven image."
      exit 2
    }
  }

  # ------ STEP 3 - refresh + re-verify ------
  Step "3. Refreshing environment and re-verifying"
  $javaVer = Test-Cmd 'java' '-version'; $mvnVer = Test-Cmd 'mvn' '-v'
  $javaMajor = Get-JavaMajor $javaVer
  $haveJava = $javaMajor -ge 11; $haveMvn = [bool]($mvnVer -match 'Apache Maven')
  if ($haveJava -and $haveMvn) { Ok "Toolchain verified: JDK $javaMajor + Maven" }
  else { Fail "Toolchain still not usable after install. Open a NEW shell and re-run (PATH changes need a fresh session)."; exit 3 }
} else {
  Ok "2-3. Toolchain already present (JDK $javaMajor + Maven) - skipping install"
}

Write-Host ("java -version:`n" + (Test-Cmd 'java' '-version'))
Write-Host ("mvn -v:`n"        + (Test-Cmd 'mvn'  '-v'))

# ---------------------------------------------------------------------------
# STEP 4 - Maven Central reachability + mirror fallback
# ---------------------------------------------------------------------------
Step "4. Generating Velocity Layer 1 project + testing Maven Central reachability"
$genScript = Join-Path $BackendDir 'scripts\velocity_layer1_gen_harness.py'
$outDir    = Join-Path $BackendDir '.velocity_layer1_out'
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Fail "python not found - needed to drive the generators."; exit 4 }
& $py $genScript $outDir | Out-Host

Push-Location $outDir
try {
  $resolve = & mvn -B "-Dvelocity.template.dir=templates" dependency:resolve 2>&1 | Out-String
  Write-Host $resolve
  $blocked = $resolve -match 'No such host is known|UnknownHost|Connection timed out|Connection refused|Could not transfer artifact|Cannot access central'
  if ($blocked) {
    Fail "Maven Central UNREACHABLE (degradation reason 2.2)."
    $settings = Join-Path $env:USERPROFILE '.m2\settings.xml'
    if (-not (Test-Path $settings)) {
      New-Item -ItemType Directory -Force -Path (Split-Path $settings) | Out-Null
      Copy-Item (Join-Path $BackendDir 'docs\ford-nexus-settings.xml') $settings
      Warn "Installed Ford Nexus settings.xml template -> $settings"
      Warn "EDIT the placeholder mirror URL, then re-run this script."
    } else {
      Warn "settings.xml already exists at $settings (left untouched)."
    }
    Warn "Attempting 'mvn dependency:go-offline' (works only if a mirror/cache is reachable)..."
    $goff = & mvn -B dependency:go-offline 2>&1 | Out-String
    Write-Host $goff
    if ($goff -match 'BUILD SUCCESS') { Ok "go-offline succeeded - cache warmed." }
    else {
      Fail "Cannot resolve dependencies. See docs\VELOCITY_LAYER1_OFFLINE_RUNBOOK.md to warm ~/.m2 on a connected machine."
      Pop-Location; exit 5
    }
  } else {
    Ok "Maven Central (or configured mirror) reachable."
  }

  # -------------------------------------------------------------------------
  # STEP 5 - compile + run the generated tests
  # -------------------------------------------------------------------------
  Step "5. Compiling and running generated Layer 1 tests (mvn test)"
  $testOut = & mvn -B "-Dvelocity.template.dir=templates" test 2>&1 | Out-String
  Write-Host $testOut
  $summary = ($testOut -split "`n" | Where-Object { $_ -match 'Tests run:' } | Select-Object -Last 1)
  if ($testOut -match 'BUILD SUCCESS') {
    Ok "mvn test PASSED. $summary"
  } else {
    Fail "mvn test FAILED. $summary"
    $compileErrs = ($testOut -split "`n" | Where-Object { $_ -match 'ERROR.*\.java|cannot find symbol|package .* does not exist' })
    if ($compileErrs) { Warn "Compile errors detected:"; $compileErrs | ForEach-Object { Write-Host "   $_" } }
    Pop-Location; exit 6
  }
} finally { Pop-Location }

Ok "All steps completed."

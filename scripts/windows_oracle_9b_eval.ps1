param(
  [string]$PromptPack = 'D:\src\training\evals\oracle_z3cli_promotion_holdout_v1.jsonl',
  [string]$Out = '',
  [string]$Model = 'oracle-9b-router',
  [string]$ModelPath = 'gguf/zelda/oracle-9b-candidate-v5-nothink-q4km.gguf',
  [string]$Identifier = 'oracle-9b-router',
  [string]$Workspace = 'D:\src\hobby\z3cli',
  [string]$ZeldaWorkspace = 'D:\src\hobby\oracle-of-secrets',
  [string]$AsarPath = '',
  [string]$StudioApiBase = 'http://127.0.0.1:1234/v1',
  [int]$Port = 1234,
  [int]$ContextLength = 12288,
  [int]$Parallel = 1,
  [string]$Gpu = 'max',
  [int]$Ttl = 3600,
  [int]$StartupTimeout = 180,
  [int]$RowTimeout = 240,
  [switch]$ForceOverwrite,
  [switch]$SkipLoad,
  [switch]$SkipServerStart,
  [switch]$RequireMesen
)

$ErrorActionPreference = 'Stop'
Set-Location $Workspace

if (-not $Out) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $leaf = [IO.Path]::GetFileNameWithoutExtension($PromptPack)
  $Out = "reports\oracle-promotion-evals\${Model}_${leaf}_${stamp}.jsonl"
}

$env:UV_PROJECT_ENVIRONMENT = Join-Path $Workspace '.venv-win'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:Z3CLI_ZELDA_WORKSPACE = $ZeldaWorkspace
$env:LMSTUDIO_BASE_URL = $StudioApiBase
# Force the LM Studio protocol layer to fall back to direct API checks when afs-hostd
# is not running locally on Windows.
$env:Z3CLI_LMSTUDIO_HOSTD_URL = 'http://127.0.0.1:1'
# Avoid slow/hanging model-memory estimation during z3cli --serve readiness.
$env:Z3CLI_SKIP_MODEL_MEMORY_ESTIMATES = '1'

$asarCandidates = @(
  $AsarPath,
  'D:\src\third_party\asar-repo\build\windows-vs\asar\bin\Release\asar.exe',
  'D:\src\hobby\yaze\build\windows-vs-z3ed\asar\asar\bin\Release\asar.exe',
  'D:\src\Code-backup\asar\build\asar\bin\asar.exe'
) | Where-Object { $_ -and (Test-Path $_) }
if ($asarCandidates.Count -gt 0) {
  $env:Z3CLI_ASAR_PATH = $asarCandidates[0]
  Write-Host "ASAR path: $env:Z3CLI_ASAR_PATH"
} else {
  Write-Host 'ASAR path: not found; hard-gate rows with compile_final_asar will fail.'
}

$mesen = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'Mesen|mesen' } | Select-Object -First 1
if ($RequireMesen -and -not $mesen) {
  throw 'RequireMesen was set, but no Mesen/Mesen2 process is running.'
}
if ($mesen) {
  Write-Host "Mesen process: $($mesen.ProcessName) pid=$($mesen.Id)"
} else {
  Write-Host 'Mesen process: not detected; emulator rows should only assert graceful unavailable behavior.'
}

$outDir = Split-Path -Parent $Out
if ($outDir) {
  New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
if ((Test-Path $Out) -and -not $ForceOverwrite) {
  throw "Output already exists: $Out. Pass -ForceOverwrite to replace it."
}
if (Test-Path $Out) {
  Remove-Item $Out
}

if (-not $SkipServerStart) {
  Write-Host "Starting LM Studio server on port $Port"
  lms server start --port $Port
}

if (-not $SkipLoad) {
  Write-Host "Loading $ModelPath as $Identifier"
  lms load $ModelPath `
    --identifier $Identifier `
    --context-length $ContextLength `
    --parallel $Parallel `
    --gpu $Gpu `
    --ttl $Ttl `
    -y
}

$evalArgs = @(
  'scripts/run_z3cli_oracle_promotion_eval.py',
  '--prompt-pack', $PromptPack,
  '--model', $Model,
  '--mode', 'manual',
  '--workspace', $Workspace,
  '--studio-api-base', $StudioApiBase,
  '--no-auto-load',
  '--no-auto-start-server',
  '--tools',
  '--auto-approve-tools',
  '--reset-between-rows',
  '--startup-timeout', [string]$StartupTimeout,
  '--row-timeout', [string]$RowTimeout,
  '--out', $Out
)

Write-Host "Running eval pack $PromptPack"
uv run python @evalArgs
Write-Host "WROTE $Out"
Get-Content $Out -Tail 1 | ForEach-Object { $_ }

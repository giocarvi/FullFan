param(
  [string]$AnalysisDate = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$DownloadsDir = 'C:\Users\GC\Downloads',
  [string]$RepoDir = 'C:\Users\GC\Documents\Codex\2026-07-07\pu\work\FullFan-git',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$python = 'C:\Users\GC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$logDir = Join-Path $RepoDir 'outputs\daily'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logPath = Join-Path $logDir "xui_fenix_daily_$($AnalysisDate)_$timestamp.log"

function Write-Log {
  param([string]$Message)
  $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
  Write-Output $line
  Add-Content -Path $logPath -Value $line -Encoding UTF8
}

function Invoke-PythonLogged {
  param([string]$ScriptPath)

  $command = "`"$python`" `"$ScriptPath`" 2>&1"
  $lines = & cmd.exe /d /c $command
  $exitCode = $LASTEXITCODE

  foreach ($line in $lines) {
    Write-Log "$line"
  }

  if ($exitCode -ne 0) {
    throw "Script fallo con codigo $exitCode`: $ScriptPath"
  }
}

try {
  Write-Log "Iniciando analisis diario XUI vs Fenix. Fecha=$AnalysisDate"
  if ($DryRun) {
    Write-Log "MODO PRUEBA activo: se simula la recreacion, no se elimina ni crea en XUI."
  }

  if (-not (Test-Path $python)) {
    throw "No se encontro Python empaquetado en: $python"
  }

  $fenixFile = Join-Path $DownloadsDir "clientes_fenix_$AnalysisDate.xlsx"
  if (-not (Test-Path $fenixFile)) {
    $sameDayFiles = Get-ChildItem -Path $DownloadsDir -File -Filter "clientes_fenix_$AnalysisDate*.xlsx" -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending
    if ($sameDayFiles.Count -gt 0) {
      $fenixFile = $sameDayFiles[0].FullName
    }
  }

  if (-not (Test-Path $fenixFile)) {
    $latestExport = Get-ChildItem -Path $DownloadsDir -File -Filter "clientes_fenix_*.xlsx" -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($null -eq $latestExport) {
      throw "No se encontro ningun export de Fenix en $DownloadsDir. Descarga primero clientes_fenix_YYYY-MM-DD.xlsx"
    }
    $fenixFile = $latestExport.FullName
    Write-Log "No se encontro export exacto del dia. Usando export mas reciente como fuente: $fenixFile"
    Write-Log "Se mantiene fecha de analisis solicitada: $AnalysisDate"
  }

  if ([string]::IsNullOrWhiteSpace($env:XUI_USER)) {
    $env:XUI_USER = [Environment]::GetEnvironmentVariable('XUI_USER', 'User')
  }
  if ([string]::IsNullOrWhiteSpace($env:XUI_PASS)) {
    $env:XUI_PASS = [Environment]::GetEnvironmentVariable('XUI_PASS', 'User')
  }

  if ([string]::IsNullOrWhiteSpace($env:XUI_USER) -or [string]::IsNullOrWhiteSpace($env:XUI_PASS)) {
    throw "Faltan variables XUI_USER y/o XUI_PASS en el entorno de Windows."
  }

  $day = [int]([DateTime]::ParseExact($AnalysisDate, 'yyyy-MM-dd', $null).Day)
  $outXlsx = Join-Path $logDir "analisis_xui_fenix_alineacion_$AnalysisDate.xlsx"
  if (Test-Path $outXlsx) {
    try {
      Remove-Item -LiteralPath $outXlsx -Force
    }
    catch {
      $outXlsx = Join-Path $logDir "analisis_xui_fenix_alineacion_$($AnalysisDate)_$timestamp.xlsx"
      Write-Log "El reporte principal esta abierto o bloqueado. Se usara archivo alterno: $outXlsx"
    }
  }

  $env:XUI_OWNER = 'giocarvi'
  $env:XUI_RESELLER_ID = '3652'
  $env:FENIX_EXPORT_XLSX = $fenixFile
  $env:ANALYSIS_DATE = $AnalysisDate
  $env:ALIGN_DAY = "$day"
  $env:ANALYSIS_OUT_XLSX = $outXlsx

  Push-Location $RepoDir
  try {
    Invoke-PythonLogged (Join-Path $RepoDir 'scripts\analyze_xui_fenix_alignment.py')
  }
  finally {
    Pop-Location
  }

  if (-not (Test-Path $outXlsx)) {
    throw "El analisis termino, pero no se encontro el archivo de salida: $outXlsx"
  }

  Write-Log "OK. Reporte generado: $outXlsx"

  $candidatesXlsx = Join-Path $logDir "candidatos_aplicar_dia_$day.xlsx"
  if (Test-Path $candidatesXlsx) {
    try {
      Remove-Item -LiteralPath $candidatesXlsx -Force
    }
    catch {
      $candidatesXlsx = Join-Path $logDir "candidatos_aplicar_dia_$($day)_$timestamp.xlsx"
      Write-Log "El archivo de candidatos esta abierto o bloqueado. Se usara archivo alterno: $candidatesXlsx"
    }
  }
  $env:INPUT_XLSX = $outXlsx
  $env:INPUT_SHEET = "Vencen dia $day"
  $env:OUTPUT_XLSX = $candidatesXlsx
  $env:SKIP_ONLINE = '1'
  $env:ONLY_ACTIVE_FENIX = '1'
  $env:ONLY_FENIX_SOURCE = '1'

  Write-Log "Preparando candidatos para recreacion exacta del dia $day..."
  Push-Location $RepoDir
  try {
    Invoke-PythonLogged (Join-Path $RepoDir 'scripts\prepare_day_candidates_for_exact_apply.py')
  }
  finally {
    Pop-Location
  }

  if (-not (Test-Path $candidatesXlsx)) {
    throw "No se genero archivo de candidatos: $candidatesXlsx"
  }

  $env:XUI_CANDIDATES_XLSX = $candidatesXlsx
  $env:XUI_APPLY_LIMIT = '0'
  if ($DryRun) {
    $env:XUI_DRY_RUN = '1'
  }
  else {
    Remove-Item Env:\XUI_DRY_RUN -ErrorAction SilentlyContinue
  }

  Write-Log "Ejecutando recreacion XUI exacta para candidatos compatibles con paquetes..."
  Push-Location $RepoDir
  try {
    Invoke-PythonLogged (Join-Path $RepoDir 'scripts\recreate_xui_lines_for_fenix_day.py')
  }
  finally {
    Pop-Location
  }

  $postOutXlsx = Join-Path $logDir "analisis_xui_fenix_post_alineacion_$AnalysisDate.xlsx"
  if (Test-Path $postOutXlsx) {
    try {
      Remove-Item -LiteralPath $postOutXlsx -Force
    }
    catch {
      $postOutXlsx = Join-Path $logDir "analisis_xui_fenix_post_alineacion_$($AnalysisDate)_$timestamp.xlsx"
      Write-Log "El reporte posterior esta abierto o bloqueado. Se usara archivo alterno: $postOutXlsx"
    }
  }

  $env:ANALYSIS_OUT_XLSX = $postOutXlsx
  Write-Log "Generando analisis posterior XUI vs Fenix despues de la recreacion..."
  Push-Location $RepoDir
  try {
    Invoke-PythonLogged (Join-Path $RepoDir 'scripts\analyze_xui_fenix_alignment.py')
  }
  finally {
    Pop-Location
  }

  Write-Log "OK. Reporte posterior generado: $postOutXlsx"
  Write-Log "OK. Ciclo diario completado: analisis inicial + candidatos + recreacion + analisis posterior."
  exit 0
}
catch {
  Write-Log "ERROR: $($_.Exception.Message)"
  exit 1
}

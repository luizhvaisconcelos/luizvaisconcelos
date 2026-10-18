# Setup: Claude Code + Ollama local (RTX 3090) - Windows
# Uso: powershell -ExecutionPolicy Bypass -File .\setup.ps1
param(
    [string]$Model = "qwen3.8-27b-ag-TurboFCFusion-MTP:latest",
    [int]$Ctx = 32768
)
$ErrorActionPreference = "Stop"

# 1. Pre-requisitos
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama nao encontrado no PATH." }
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw "Claude Code nao encontrado. Instale: irm https://claude.ai/install.ps1 | iex" }
Write-Host "Ollama: $(ollama --version)"
if (-not (ollama list | Select-String -SimpleMatch $Model)) { throw "Modelo '$Model' nao existe em 'ollama list'." }

# 2. Variaveis do SERVIDOR Ollama (persistentes, escopo usuario). Escuta so em localhost.
$srv = @{
    OLLAMA_CONTEXT_LENGTH   = "$Ctx"
    OLLAMA_FLASH_ATTENTION  = "1"
    OLLAMA_KV_CACHE_TYPE    = "q8_0"
    OLLAMA_HOST             = "127.0.0.1:11434"
}
$srv.GetEnumerator() | ForEach-Object { [Environment]::SetEnvironmentVariable($_.Key, $_.Value, "User") }

# 3. Reinicia o Ollama para aplicar
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
$app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
$srv.GetEnumerator() | ForEach-Object { Set-Item -Path "Env:$($_.Key)" -Value $_.Value }
if (Test-Path $app) { Start-Process $app } else { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version | Out-Null; break } catch { Start-Sleep 1 }
}

# 4. Launcher claude-local (env vars so valem para este processo, nao afetam o claude normal)
$bin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
@"
@echo off
set ANTHROPIC_BASE_URL=http://127.0.0.1:11434
set ANTHROPIC_AUTH_TOKEN=ollama
set ANTHROPIC_API_KEY=
set ANTHROPIC_MODEL=$Model
set ANTHROPIC_SMALL_FAST_MODEL=$Model
set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
claude %*
"@ | Set-Content -Encoding ASCII (Join-Path $bin "claude-local.cmd")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$bin*") { [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User") }

# 5. Teste do endpoint compativel com Anthropic
Write-Host "Testando /v1/messages ..."
$body = @{ model = $Model; max_tokens = 32; messages = @(@{ role = "user"; content = "responda apenas: ok" }) } | ConvertTo-Json -Depth 5
try {
    $r = Invoke-RestMethod -Uri http://127.0.0.1:11434/v1/messages -Method Post -ContentType "application/json" `
        -Headers @{ "x-api-key" = "ollama"; "anthropic-version" = "2023-06-01" } -Body $body -TimeoutSec 300
    Write-Host "OK: $($r.content[0].text)" -ForegroundColor Green
} catch {
    Write-Host "FALHOU: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Se for 404: atualize o Ollama ou use LiteLLM como proxy. Envie a saida de 'ollama --version'."
}
Write-Host "`nPronto. Abra um NOVO terminal e rode: claude-local"

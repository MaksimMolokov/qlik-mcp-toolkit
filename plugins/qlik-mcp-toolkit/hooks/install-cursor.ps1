# First-time / repair install for Cursor. No Git, no admin.
# irm https://raw.githubusercontent.com/MaksimMolokov/qlik-mcp-toolkit/main/hooks/install-cursor.ps1 | iex
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "MaksimMolokov/qlik-mcp-toolkit"
$ZipUrl = "https://github.com/$Repo/archive/refs/heads/main.zip"
$CursorHome = Join-Path $HOME ".cursor"
$LocalPlugin = Join-Path $CursorHome "plugins\local\qlik-mcp-toolkit"
$UserHooks = Join-Path $CursorHome "hooks"
$UserHooksJson = Join-Path $CursorHome "hooks.json"
$UserMcp = Join-Path $CursorHome "mcp.json"
$CopyNames = @(
  "skills", "rules", "hooks", "plugins", "plugin.json", "README.md", "CHANGELOG.md",
  ".cursor-plugin", ".claude-plugin", ".mcp.json", ".agents"
)

function Get-PluginVersion([string]$dir) {
  foreach ($rel in @(".cursor-plugin\plugin.json", "plugin.json")) {
    $p = Join-Path $dir $rel
    if (Test-Path $p) {
      try {
        $v = (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json).version
        if ($v) { return [string]$v }
      } catch { }
    }
  }
  return $null
}

function Copy-PluginTree([string]$src, [string]$dest) {
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  foreach ($name in $CopyNames) {
    $from = Join-Path $src $name
    $to = Join-Path $dest $name
    if (-not (Test-Path $from)) { continue }
    if (Test-Path $to) { Remove-Item $to -Recurse -Force }
    Copy-Item $from $to -Recurse -Force
  }
  $gitDir = Join-Path $dest ".git"
  if (Test-Path $gitDir) { Remove-Item $gitDir -Recurse -Force }
}

function Find-MarketplaceSnapshot {
  $cache = Join-Path $CursorHome "plugins\cache"
  if (-not (Test-Path $cache)) { return $null }
  $best = $null
  $bestKey = @(-1)
  Get-ChildItem $cache -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $toolkit = Join-Path $_.FullName "qlik-mcp-toolkit"
    if (-not (Test-Path $toolkit)) { return }
    Get-ChildItem $toolkit -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      if (-not (Test-Path (Join-Path $_.FullName ".cursor-plugin\plugin.json"))) { return }
      $ver = Get-PluginVersion $_.FullName
      $parts = @(0)
      if ($ver) { $parts = @($ver.Split(".") | ForEach-Object { [int]$_ }) }
      $key = @($parts + $_.LastWriteTimeUtc.Ticks)
      $cmp = 0
      if ($null -eq $best) { $cmp = 1 }
      else {
        $n = [Math]::Max($key.Count, $bestKey.Count)
        for ($i = 0; $i -lt $n; $i++) {
          $a = if ($i -lt $key.Count) { [int64]$key[$i] } else { 0 }
          $b = if ($i -lt $bestKey.Count) { [int64]$bestKey[$i] } else { 0 }
          if ($a -ne $b) { $cmp = [Math]::Sign($a - $b); break }
        }
      }
      if ($cmp -gt 0) { $best = $_.FullName; $bestKey = $key }
    }
  }
  return $best
}

Write-Host "qlik-mcp-toolkit: установка для Cursor без Git..."

$gitAvailable = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
$isDevClone = Test-Path (Join-Path $LocalPlugin ".git")
$tmp = $null
if ($isDevClone -and $gitAvailable) {
  Write-Host "Это git-клон разработчика — файлы плагина не перезаписываю. Обновляю хуки и пин MCP."
  $version = Get-PluginVersion $LocalPlugin
  if (-not $version) { $version = "2.3.0.6" }
} else {
  $source = $null
  try {
    Write-Host "Качаю $ZipUrl"
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("qlik-mcp-toolkit-" + [guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zipPath = Join-Path $tmp "main.zip"
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
    $source = Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like "qlik-mcp-toolkit*" } | Select-Object -First 1 -ExpandProperty FullName
    if (-not $source) { throw "В zip нет корня плагина" }
  } catch {
    Write-Host "GitHub недоступен ($($_.Exception.Message)). Пробую кэш маркетплейса."
    $source = Find-MarketplaceSnapshot
    if (-not $source) { throw "Нет ни GitHub zip, ни снимка маркетплейса" }
    Write-Host "Беру снимок маркетплейса: $source"
  }
  Copy-PluginTree $source $LocalPlugin
  $version = Get-PluginVersion $LocalPlugin
  if (-not $version) { $version = "2.3.0.6" }
}
$pinParts = $version.Split(".")
if ($pinParts.Count -ge 3) { $pin = ($pinParts[0..2] -join ".") } else { $pin = "2.3.0" }
Write-Host "Плагин $version -> $LocalPlugin (пин MCP $pin)"

$hooksSrc = Join-Path $LocalPlugin "hooks"
New-Item -ItemType Directory -Force -Path $UserHooks | Out-Null
foreach ($name in @(
  "update-qlik-mcp.py", "update-qlik-mcp.cmd", "update-qlik-mcp.sh",
  "sync_qlik_mcp_env.py", "sync-qlik-mcp-env.cmd", "sync-qlik-mcp-env.sh",
  "hooks.codex.json", "install-cursor.ps1"
)) {
  $from = Join-Path $hooksSrc $name
  if (Test-Path $from) { Copy-Item $from (Join-Path $UserHooks $name) -Force }
}

$hookEntry = @{
  version = 1
  hooks = @{
    sessionStart = @(
      @{ command = "./hooks/sync-qlik-mcp-env.cmd"; timeout = 15 },
      @{ command = "./hooks/update-qlik-mcp.cmd"; timeout = 150 }
    )
  }
}
$hookJson = $hookEntry | ConvertTo-Json -Depth 6
function Needs-HooksRewrite([string]$path) {
  if (-not (Test-Path $path)) { return $true }
  $raw = Get-Content $path -Raw -Encoding UTF8
  if ($raw -match "workspaceOpen") { return $true }
  if ($raw -notmatch "update-qlik-mcp") { return $true }
  return $false
}
if (Needs-HooksRewrite $UserHooksJson) {
  Set-Content -Path $UserHooksJson -Value $hookJson -Encoding UTF8
}
if (Needs-HooksRewrite (Join-Path $UserHooks "hooks.json")) {
  Set-Content -Path (Join-Path $UserHooks "hooks.json") -Value $hookJson -Encoding UTF8
}

if (Test-Path $UserMcp) {
  $raw = Get-Content $UserMcp -Raw -Encoding UTF8
  $pinned = "qlik-sense-mcp-server==$pin"
  $updated = [regex]::Replace($raw, "qlik-sense-mcp-server(?:==[0-9.]+)?", $pinned)
  $updated = $updated -replace '"command"\s*:\s*"qlik-sense-mcp-server(\.exe)?"', '"command": "uvx"'
  if ($updated -ne $raw) {
    Set-Content -Path $UserMcp -Value $updated -Encoding UTF8
    Write-Host "Записал пин $pinned в $UserMcp"
  } else {
    Write-Host "MCP-конфиг уже содержит $pinned или сервер qlik ещё не заведён."
  }
} else {
  Write-Host "Нет $UserMcp — сначала Add qlik MCP server, потом запустите скрипт ещё раз."
}

if ($tmp -and (Test-Path $tmp)) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "Готово. Git не нужен."
Write-Host "1) Полностью закройте Cursor (все окна) и откройте снова."
Write-Host "2) Settings -> Plugins: включите qlik-mcp-toolkit (Local)."
Write-Host "3) Settings -> MCP: перезапустите сервер qlik, если он уже был запущен."

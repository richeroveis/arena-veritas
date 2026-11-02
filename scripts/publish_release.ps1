# Publish the release: main branch, studionet-v1 tag, gh-pages build, Pages config.
# Reads GITHUB_TOKEN from this project's own .env. Never prints the token, and
# every command's output passes through a sanitizer that strips the token and its
# base64 form. Requires frontend/dist to exist (cd frontend && npm run build).
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot/..

$line = (Get-Content .env | Where-Object { $_ -match '^GITHUB_TOKEN=' } | Select-Object -First 1)
if (-not $line) { Write-Error "GITHUB_TOKEN missing from .env"; exit 1 }
$tok = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
if ($tok.Length -lt 20) { Write-Error "GITHUB_TOKEN looks empty or truncated"; exit 1 }
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("x-access-token:$tok"))
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "never"
$Repo = "https://github.com/richeroveis/arena-veritas.git"
$Api = "https://api.github.com/repos/richeroveis/arena-veritas"
$Hdr = @{
  Authorization      = "Basic $b64"
  Accept             = "application/vnd.github+json"
  "X-Requested-With" = "XMLHttpRequest"
}
$GitAuth = @("-c", "http.extraHeader=Authorization: Basic $b64")

function Show($text) { "$text" -replace [regex]::Escape($tok), "***" -replace [regex]::Escape($b64), "***" }

"== 1. pushing main =="
git @GitAuth push origin main 2>&1 | ForEach-Object { Show $_ }
"main push exit=$LASTEXITCODE"

"== 2. pushing tag studionet-v1 =="
git @GitAuth push --force origin refs/tags/studionet-v1 2>&1 | ForEach-Object { Show $_ }
"tag push exit=$LASTEXITCODE"

"== 3. publishing gh-pages from frontend/dist =="
if (-not (Test-Path frontend/dist/index.html)) { Write-Error "frontend/dist missing, run npm run build first"; exit 1 }
$stage = "scripts/ghp-build"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item frontend/dist/* $stage/ -Recurse
# The legacy Pages build runs Jekyll unless this file exists, which can drop assets.
New-Item -ItemType File -Path "$stage/.nojekyll" -Force | Out-Null
Push-Location $stage
git init -q -b gh-pages . 2>&1 | ForEach-Object { Show $_ }
git add -A
git -c user.name="tidex22" -c user.email="tidex22@users.noreply.github.com" `
  commit -q -m "ArenaVeritas broadcast control room build for studionet-v1" 2>&1 | ForEach-Object { Show $_ }
"staged files:"
git ls-files | ForEach-Object { "  $_" }
git @GitAuth push --force $Repo HEAD:refs/heads/gh-pages 2>&1 | ForEach-Object { Show $_ }
"gh-pages push exit=$LASTEXITCODE"
Pop-Location

"== 4. pages configuration =="
$body = @{ build_type = "legacy"; source = @{ branch = "gh-pages"; path = "/" } } | ConvertTo-Json
try {
  $cur = Invoke-RestMethod -Uri "$Api/pages" -Headers $Hdr -Method Get
  "existing: build_type=$($cur.build_type) source=$($cur.source.branch):$($cur.source.path) url=$($cur.html_url)"
} catch {
  $status = try { $_.Exception.Response.StatusCode.value__ } catch { "n/a" }
  "not configured yet (get status=$status), creating"
  try {
    $res = Invoke-WebRequest -Uri "$Api/pages" -Headers $Hdr -Method Post -Body $body -ContentType "application/json"
    "create status=$($res.StatusCode)"
  } catch {
    "create failed: " + (Show ($_.ErrorDetails.Message))
  }
}

try {
  $pages = Invoke-RestMethod -Uri "$Api/pages" -Headers $Hdr -Method Get
  "pages now: source=$($pages.source.branch):$($pages.source.path) status=$($pages.status) url=$($pages.html_url)"
} catch { "pages read failed: " + (Show ($_.ErrorDetails.Message)) }

"== 5. remote refs =="
git @GitAuth ls-remote $Repo 'refs/heads/main' 'refs/heads/gh-pages' 'refs/tags/studionet-v1*' 2>&1 | ForEach-Object { Show $_ }
"done"

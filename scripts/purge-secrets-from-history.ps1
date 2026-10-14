<#
.SYNOPSIS
  Gate-0 secret purge: removes the leaked backend/.env from git HISTORY and
  scrubs the leaked secret VALUES out of every other historical blob.

.DESCRIPTION
  The incident (see SECURITY.md): commit de191c6 committed backend/.env with live
  credentials and it was pushed. a4d6499 untracked the file and fixed the admin
  password in README.md / .env.production.example *in the working tree*, but the
  old blobs (and the whole backend/.env) still exist in history.

  Untracking alone does not un-leak anything. This script does the two things
  that actually remove the values from reachable history:

    1. --path backend/.env --invert-paths   (delete the file everywhere in history)
    2. --replace-text <generated>           (blank the secret values in ALL blobs,
                                             e.g. the admin password that also sat
                                             in README.md and .env.production.example)

  ROTATION (SECURITY.md step 1) is still mandatory and is NOT done here - a value
  a third party already read stays valid until you rotate it at the source.

  Default is a SAFE dry run: it prepares everything, reports what it finds, and
  prints the exact command. Pass -Execute to actually rewrite history (still no
  push; it prints the force-push commands for you to run deliberately).

.NOTES
  Requires git-filter-repo (pip install git-filter-repo). It intentionally does
  NOT use the deprecated `git filter-branch`.
#>
[CmdletBinding()]
param(
  # Rewrite history. Without this the script only prepares + reports.
  [switch]$Execute
)

$ErrorActionPreference = 'Stop'
Set-Location (git rev-parse --show-toplevel)

$Repo       = (git rev-parse --show-toplevel)
$LeakedPath = 'backend/.env'
$LeakCommit = 'de191c6'                      # commit that added the file
$Sensitive  = @(
  'KETSA_WANDE_TOKEN',
  'SUPABASE_SERVICE_ROLE_KEY',
  'KETSA_RESEND_API_KEY',
  'KETSA_AUTH0_CLIENT_SECRET',
  'KETSA_ADMIN_PASSWORD'
)
$ScrubFile = Join-Path $Repo '.git-secrets-to-scrub.txt'   # gitignored
$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'

function Info($m) { Write-Host "[purge] $m" }
function Warn($m) { Write-Host "[purge] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[purge] $m" -ForegroundColor Red; exit 1 }

# --- resolve the git-filter-repo entry point (PATH, then the backend venv) ----
function Resolve-FilterRepo {
  $cmd = Get-Command git-filter-repo -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($cand in @('backend\.venv\Scripts\git-filter-repo.exe',
                      'backend\venv\Scripts\git-filter-repo.exe')) {
    if (Test-Path $cand) { return (Resolve-Path $cand).Path }
  }
  return $null
}

# --- 0. safety: clean tree (+ backup only when actually rewriting) ------------
$dirty = git status --porcelain
if ($dirty) {
  Die "working tree is not clean - commit or stash first:`n$dirty"
}
if ($Execute) {
  Info "creating backup tag + bundle before any rewrite"
  & git tag -f "pre-secret-purge-$Stamp" | Out-Null
  $bundleDir = Join-Path (Split-Path $Repo -Parent) "_ketsa-backup-$Stamp"
  New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
  & git bundle create (Join-Path $bundleDir 'ketsa.bundle') --all | Out-Null
  Info "backup tag: pre-secret-purge-$Stamp"
  Info "backup bundle: $bundleDir\ketsa.bundle"
} else {
  Info "(dry run) would create backup tag pre-secret-purge-$Stamp + a bundle"
}

# --- 1. build the replace-text file from the leaked blob (values never printed) -
Info "building replace-text from $LeakCommit`:$LeakedPath"
$blob = & git show "$LeakCommit`:$LeakedPath"
if (-not $blob) { Die "could not read $LeakCommit`:$LeakedPath" }

$lines = New-Object System.Collections.Generic.List[string]
$found = 0
foreach ($raw in $blob) {
  if ($raw -match '^\s*#' -or $raw -match '^\s*$') { continue }
  if ($raw -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    $k = $Matches[1]; $v = $Matches[2].Trim()
    if (($Sensitive -contains $k) -and $v.Length -ge 6) {
      $lines.Add("$v==>")     # literal value -> blank
      $found++
      Info ("  will scrub {0} (len={1})" -f $k, $v.Length)
    }
  }
}
if ($found -eq 0) { Die "no sensitive values found in $LeakCommit`:$LeakedPath" }
[System.IO.File]::WriteAllLines($ScrubFile, $lines, (New-Object System.Text.UTF8Encoding($false)))
Info "wrote $ScrubFile ($found values). It is gitignored - never commit it."

# --- 2. report every reachable commit that still contains the file ------------
$fileCommits = (& git log --all --oneline -- $LeakedPath) -join "`n"
Info "commits touching $LeakedPath (to be removed from history):"
if ($fileCommits) { $fileCommits -split "`n" | ForEach-Object { "        $_" } } else { "        (none)" }

# --- 3. execute or print ------------------------------------------------------
$fr = Resolve-FilterRepo
if (-not $fr) {
  Warn "git-filter-repo not found. Install it, then re-run -Execute:"
  "        pip install git-filter-repo"
  "        (or: pipx install git-filter-repo)"
}

$relScrub = '.git-secrets-to-scrub.txt'
$frCmd = "git filter-repo --force --invert-paths --path $LeakedPath --replace-text $relScrub"

Info "The rewrite command is:"
"        $frCmd"

if (-not $Execute) {
  Warn "DRY RUN - nothing rewritten. Re-run with -Execute (after confirming the backup)."
  Warn "Remember: rotating the credentials is mandatory regardless (SECURITY.md step 1)."
  exit 0
}

if (-not $fr) { Die "-Execute requested but git-filter-repo is not installed." }

Info "rewriting history ..."
if ($fr -like '*.exe') {
  & $fr --force --invert-paths --path $LeakedPath --replace-text $relScrub
} else {
  & git filter-repo --force --invert-paths --path $LeakedPath --replace-text $relScrub
}
if ($LASTEXITCODE -ne 0) { Die "git-filter-repo exited $LASTEXITCODE" }

Info "done. git-filter-repo drops 'origin' on purpose. Next, deliberately:"
"        git remote add origin https://github.com/tuyishime812/ketsa.git"
"        git push origin --force --all"
"        git push origin --force --tags"
"      Then: git log --all -- $LeakedPath   # expect no output"
"      Finally delete $ScrubFile and the backup bundle once verified."

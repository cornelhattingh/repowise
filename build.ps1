#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build RepoWise Python packages and/or the web UI.

.DESCRIPTION
    Builds the RepoWise monorepo components. By default builds everything.

.PARAMETER PythonOnly
    Build only the Python packages (uv sync).

.PARAMETER WebOnly
    Build only the web UI (Next.js).

.PARAMETER SkipInstall
    Skip dependency installation (uv sync / npm install) before building.

.EXAMPLE
    .\build.ps1                  # Build everything
    .\build.ps1 -PythonOnly      # Build Python only
    .\build.ps1 -WebOnly         # Build web UI only
    .\build.ps1 -SkipInstall     # Build without reinstalling dependencies
#>

param(
    [switch]$PythonOnly,
    [switch]$WebOnly,
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "'$Name' not found. Please install it and ensure it is on PATH."
    }
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

if (-not $WebOnly) { Assert-Command "uv" }
if (-not $PythonOnly) { Assert-Command "npm" }

# ---------------------------------------------------------------------------
# Python build
# ---------------------------------------------------------------------------

if (-not $WebOnly) {
    Write-Step "Building Python packages"

    Push-Location $Root
    try {
        if (-not $SkipInstall) {
            Write-Step "Installing Python dependencies (uv sync)"
            uv sync --all-packages
            if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)" }
        }

        Write-Step "Python packages ready"
    }
    finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# Web UI build
# ---------------------------------------------------------------------------

if (-not $PythonOnly) {
    Write-Step "Building web UI"

    Push-Location (Join-Path $Root "packages/web")
    try {
        if (-not $SkipInstall) {
            Write-Step "Installing Node dependencies (npm install)"
            Push-Location $Root
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
            Pop-Location
        }

        Write-Step "Running Next.js build"
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Next.js build failed (exit $LASTEXITCODE)" }

        Write-Step "Web UI build complete"
    }
    finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green

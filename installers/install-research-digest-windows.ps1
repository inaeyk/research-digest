[CmdletBinding()]
param(
    [ValidateSet("Install", "Uninstall")]
    [string] $Action = "Install",
    [string] $Distribution,
    [switch] $RemoveSchedule,
    [switch] $PurgeData,
    [string] $Confirm
)

$ErrorActionPreference = "Stop"
$Version = "0.5.0"
$ReleaseUrl = "https://github.com/inaeyk/research-digest/releases/download/v$Version"
$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "research-digest-installer-" + [guid]::NewGuid().ToString("N")
)

# BEGIN RESEARCH DIGEST INSTALLER ENVIRONMENT
function Get-ResearchDigestInstallerEnvironment {
    param([string[]] $LoginEnvironment)
    $LoginPathLines = @($LoginEnvironment | Where-Object { $_ -like 'PATH=*' })
    if ($LoginPathLines.Count -ne 1) {
        throw "The selected WSL login environment returned an ambiguous PATH."
    }
    $LoginPath = $LoginPathLines[0].Substring('PATH='.Length)
    $InstallerEnvironment = @("PATH=$LoginPath")
    $PreservedEnvironmentNames = @(
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "RESEARCH_DIGEST_DATA_DIR",
        "RESEARCH_DIGEST_CONFIG_DIR",
        "RESEARCH_DIGEST_DB",
        "RESEARCH_DIGEST_PYTHON",
        "RESEARCH_DIGEST_ANALYZER",
        "OPENAI_MODEL",
        "RESEARCH_DIGEST_CODEX_MODEL",
        "RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS"
    )
    foreach ($Name in $PreservedEnvironmentNames) {
        $EnvironmentMatches = @($LoginEnvironment | Where-Object { $_ -like "$Name=*" })
        if ($EnvironmentMatches.Count -gt 1) {
            throw "The selected WSL login environment returned ambiguous $Name values."
        }
        if ($EnvironmentMatches.Count -eq 1) {
            $InstallerEnvironment += $EnvironmentMatches[0]
        }
    }
    return $InstallerEnvironment
}
# END RESEARCH DIGEST INSTALLER ENVIRONMENT

function Get-InstalledWslDistributions {
    $Output = & wsl.exe --list --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "WSL2 is required and wsl.exe could not list installed distributions."
    }
    return @(
        $Output |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { $_ -ne "" }
    )
}

try {
    $Distributions = @(Get-InstalledWslDistributions)
    if ($Distribution) {
        $ExactMatches = @($Distributions | Where-Object { $_ -ceq $Distribution })
        if ($ExactMatches.Count -ne 1) {
            throw "The requested WSL distribution '$Distribution' is not installed."
        }
        $Distribution = $ExactMatches[0]
    }
    elseif ($Distributions.Count -eq 1) {
        $Distribution = $Distributions[0]
    }
    elseif ($Distributions.Count -eq 0) {
        throw "WSL2 is installed, but no WSL distribution is available."
    }
    else {
        throw (
            "More than one WSL distribution is installed. Rerun with " +
            "-Distribution followed by the exact name from 'wsl.exe --list --quiet'."
        )
    }

    New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null
    $ManifestPath = Join-Path $TemporaryDirectory "SHA256SUMS"
    $InstallerPath = Join-Path $TemporaryDirectory "install-research-digest.py"
    Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseUrl/SHA256SUMS" -OutFile $ManifestPath
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "$ReleaseUrl/install-research-digest.py" `
        -OutFile $InstallerPath

    $ManifestLine = Get-Content -LiteralPath $ManifestPath | Where-Object {
        $_ -match '^[0-9a-fA-F]{64}\s+\*?install-research-digest\.py$'
    }
    if (@($ManifestLine).Count -ne 1) {
        throw "SHA256SUMS has no unique installer entry; nothing was installed."
    }
    $ExpectedHash = ($ManifestLine -split '\s+')[0].ToLowerInvariant()
    $ActualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash.ToLowerInvariant()
    if ($ActualHash -ne $ExpectedHash) {
        throw "Installer SHA-256 verification failed; nothing was installed."
    }
    if ($Action -eq "Install") {
        $WheelPath = Join-Path $TemporaryDirectory "research_digest-0.5.0-py3-none-any.whl"
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "$ReleaseUrl/research_digest-0.5.0-py3-none-any.whl" `
            -OutFile $WheelPath
    }

    $InstallerWslPath = (& wsl.exe -d $Distribution --exec wslpath -a $InstallerPath).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $InstallerWslPath) {
        throw "Could not translate the verified installer path into the selected WSL distribution."
    }
    $PasswdLine = (& wsl.exe -d $Distribution --exec /bin/sh -c 'getent passwd "$(id -u)"').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $PasswdLine.Contains(":")) {
        throw "Could not identify the target WSL user's login shell."
    }
    $LoginShell = ($PasswdLine -split ':')[-1]
    if (-not $LoginShell.StartsWith("/")) {
        throw "The target WSL user's login shell path is invalid."
    }
    $LoginEnvironment = @(& wsl.exe -d $Distribution --exec $LoginShell -lic env)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the selected WSL user's login environment."
    }
    $InstallerEnvironment = @(
        Get-ResearchDigestInstallerEnvironment -LoginEnvironment $LoginEnvironment
    )
    $DiscoveryScript = @'
emit_runtime() {
    resolved=$1
    "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1 || return 1
    codex_path=$(command -v codex 2>/dev/null || true)
    printf 'RD_PYTHON=%s\n' "$resolved"
    if [ -n "$codex_path" ] && [ -x "$codex_path" ]; then
        printf 'RD_CODEX=%s\n' "$codex_path"
    fi
    return 0
}
if [ -n "${RESEARCH_DIGEST_PYTHON:-}" ]; then
    case "$RESEARCH_DIGEST_PYTHON" in
        /*) resolved=$RESEARCH_DIGEST_PYTHON ;;
        *) resolved=$(command -v "$RESEARCH_DIGEST_PYTHON" 2>/dev/null || true) ;;
    esac
    [ -n "$resolved" ] && [ -x "$resolved" ] || exit 2
    emit_runtime "$resolved" || exit 2
    exit 0
fi
for candidate in python3 python3.14 python3.13 python3.12 python3.11 /usr/local/bin/python3.14 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11; do
    resolved=$(command -v "$candidate" 2>/dev/null || true)
    [ -n "$resolved" ] || continue
    emit_runtime "$resolved" || continue
    exit 0
done
exit 2
'@
    $DiscoveryOutput = @(
        & wsl.exe -d $Distribution --exec env @InstallerEnvironment /bin/sh -c $DiscoveryScript
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or newer is required inside the selected WSL distribution."
    }
    $PythonLines = @($DiscoveryOutput | Where-Object { $_ -like 'RD_PYTHON=*' })
    $CodexLines = @($DiscoveryOutput | Where-Object { $_ -like 'RD_CODEX=*' })
    if ($PythonLines.Count -ne 1 -or $CodexLines.Count -gt 1) {
        throw "The selected WSL login environment returned ambiguous runtime discovery data."
    }
    if ($Action -eq "Install" -and $CodexLines.Count -ne 1) {
        throw (
            "Codex CLI was not found in the selected WSL user's login environment. " +
            "Install and authenticate Codex before installing Research Digest."
        )
    }
    $Python = $PythonLines[0].Substring('RD_PYTHON='.Length)

    $InstallerArguments = @($InstallerWslPath, $Action.ToLowerInvariant())
    if ($Action -eq "Install") {
        $AssetsWslPath = (& wsl.exe -d $Distribution --exec wslpath -a $TemporaryDirectory).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $AssetsWslPath) {
            throw "Could not translate the verified release-asset directory into WSL."
        }
        $InstallerArguments += @(
            "--asset-dir", $AssetsWslPath, "--distro", $Distribution
        )
    }
    if ($Action -eq "Uninstall") {
        if ($RemoveSchedule) {
            $InstallerArguments += "--remove-schedule"
        }
        if ($PurgeData) {
            $InstallerArguments += "--purge-data"
        }
        if ($Confirm) {
            $InstallerArguments += @("--confirm", $Confirm)
        }
    }
    & wsl.exe -d $Distribution --exec env @InstallerEnvironment $Python @InstallerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Research Digest installation inside WSL did not complete."
    }
}
finally {
    if (Test-Path -LiteralPath $TemporaryDirectory) {
        Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
    }
}

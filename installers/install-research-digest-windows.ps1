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

# BEGIN RESEARCH DIGEST WSL DISTRIBUTION
function Get-InstalledWslDistributions {
    $Output = & wsl.exe --list --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "WSL2 is required and wsl.exe could not list installed distributions."
    }
    return @(
        $Output |
            Where-Object { $null -ne $_ } |
            ForEach-Object { ([string] $_ -replace "`0", "").Trim() } |
            Where-Object { $_ -ne "" }
    )
}

function Resolve-ResearchDigestWslDistribution {
    param([string] $RequestedDistribution)
    $Distributions = @(Get-InstalledWslDistributions)
    if ($RequestedDistribution) {
        $ExactMatches = @(
            $Distributions | Where-Object { $_ -ceq $RequestedDistribution }
        )
        if ($ExactMatches.Count -ne 1) {
            throw (
                "The requested WSL distribution '$RequestedDistribution' is not installed."
            )
        }
        return $ExactMatches[0]
    }
    if ($Distributions.Count -eq 1) {
        return $Distributions[0]
    }
    if ($Distributions.Count -eq 0) {
        throw "WSL2 is installed, but no WSL distribution is available."
    }
    throw (
        "More than one WSL distribution is installed. Rerun with " +
        "-Distribution followed by the exact name from 'wsl.exe --list --quiet'."
    )
}
# END RESEARCH DIGEST WSL DISTRIBUTION

# BEGIN RESEARCH DIGEST WSL LOGIN SHELL
function Get-ResearchDigestWslLoginShell {
    param([string] $Distribution)

    $UidLines = @(& wsl.exe -d $Distribution --exec id -u)
    $UidExitCode = $LASTEXITCODE
    if ($UidExitCode -ne 0) {
        throw (
            "Could not determine the target WSL user's UID in distribution " +
            "'$Distribution': 'id -u' exited with code $UidExitCode."
        )
    }
    $UidValues = @(
        $UidLines |
            Where-Object { $null -ne $_ } |
            ForEach-Object { ([string] $_).Trim() } |
            Where-Object { $_ -ne "" }
    )
    if ($UidValues.Count -ne 1) {
        throw (
            "Could not determine the target WSL user's UID in distribution " +
            "'$Distribution': 'id -u' did not return exactly one numeric UID."
        )
    }
    $UidOutput = $UidValues[0]
    [long] $NumericUid = 0
    if (
        $UidOutput -notmatch '^(0|[1-9][0-9]{0,9})$' -or
        -not [long]::TryParse($UidOutput, [ref] $NumericUid) -or
        $NumericUid -gt 4294967294
    ) {
        throw (
            "Could not determine the target WSL user's UID in distribution " +
            "'$Distribution': 'id -u' did not return exactly one numeric UID."
        )
    }

    $PasswdLines = @(& wsl.exe -d $Distribution --exec getent passwd $UidOutput)
    $PasswdExitCode = $LASTEXITCODE
    if ($PasswdExitCode -ne 0) {
        throw (
            "Could not identify the target WSL user's login shell in distribution " +
            "'$Distribution': 'getent passwd $UidOutput' exited with code " +
            "$PasswdExitCode."
        )
    }
    $PasswdRows = @(
        $PasswdLines |
            Where-Object { $null -ne $_ } |
            ForEach-Object { ([string] $_).Trim() } |
            Where-Object { $_ -ne "" }
    )
    if ($PasswdRows.Count -ne 1) {
        throw (
            "Could not identify the target WSL user's login shell in distribution " +
            "'$Distribution': getent did not return exactly one passwd row."
        )
    }
    $PasswdFields = @($PasswdRows[0] -split ':')
    if (
        $PasswdFields.Count -ne 7 -or
        -not $PasswdFields[0] -or
        $PasswdFields[2] -cne $UidOutput -or
        $PasswdFields[3] -notmatch '^[0-9]+$' -or
        -not $PasswdFields[5].StartsWith('/') -or
        -not $PasswdFields[6].StartsWith('/')
    ) {
        throw (
            "Could not identify the target WSL user's login shell in distribution " +
            "'$Distribution': getent returned an invalid passwd row."
        )
    }
    return $PasswdFields[6]
}
# END RESEARCH DIGEST WSL LOGIN SHELL

try {
    $Distribution = Resolve-ResearchDigestWslDistribution `
        -RequestedDistribution $Distribution

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

    $InstallerWslPathOutput = @(
        & wsl.exe -d $Distribution --exec wslpath -a $InstallerPath
    )
    $InstallerWslPathExitCode = $LASTEXITCODE
    if ($InstallerWslPathExitCode -ne 0 -or $InstallerWslPathOutput.Count -ne 1) {
        throw "Could not translate the verified installer path into the selected WSL distribution."
    }
    $InstallerWslPath = [string] $InstallerWslPathOutput[0]
    if ([string]::IsNullOrWhiteSpace($InstallerWslPath)) {
        throw "Could not translate the verified installer path into the selected WSL distribution."
    }
    $InstallerWslPath = $InstallerWslPath.Trim()
    $LoginShell = Get-ResearchDigestWslLoginShell -Distribution $Distribution
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
        $AssetsWslPathOutput = @(
            & wsl.exe -d $Distribution --exec wslpath -a $TemporaryDirectory
        )
        $AssetsWslPathExitCode = $LASTEXITCODE
        if ($AssetsWslPathExitCode -ne 0 -or $AssetsWslPathOutput.Count -ne 1) {
            throw "Could not translate the verified release-asset directory into WSL."
        }
        $AssetsWslPath = [string] $AssetsWslPathOutput[0]
        if ([string]::IsNullOrWhiteSpace($AssetsWslPath)) {
            throw "Could not translate the verified release-asset directory into WSL."
        }
        $AssetsWslPath = $AssetsWslPath.Trim()
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

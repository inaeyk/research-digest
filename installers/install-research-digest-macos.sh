#!/bin/sh
set -eu

version="0.5.0"
release_url="https://github.com/inaeyk/research-digest/releases/download/v${version}"

if [ "$(uname -s)" != "Darwin" ]; then
    printf '%s\n' "Research Digest's macOS installer requires macOS." >&2
    exit 2
fi

python_version() {
    "$1" -c '
import sys
print(".".join(str(value) for value in sys.version_info[:3]))
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
' 2>/dev/null
}

resolve_command() {
    case "$1" in
        */*) [ -x "$1" ] && printf '%s\n' "$1" || true ;;
        *) command -v "$1" 2>/dev/null || true ;;
    esac
}

selected_python=""
unsupported_version=""
if [ -n "${RESEARCH_DIGEST_PYTHON:-}" ]; then
    candidate=$(resolve_command "$RESEARCH_DIGEST_PYTHON")
    if [ -z "$candidate" ]; then
        printf '%s\n' \
            "Research Digest could not find RESEARCH_DIGEST_PYTHON=$RESEARCH_DIGEST_PYTHON." \
            "No private runtime was created." >&2
        exit 2
    fi
    if found_version=$(python_version "$candidate"); then
        selected_python=$candidate
    else
        unsupported_version=${found_version:-unknown}
    fi
else
    for name in \
        python3 python3.14 python3.13 python3.12 python3.11 \
        /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 \
        /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
        /usr/local/bin/python3.14 /usr/local/bin/python3.13 \
        /usr/local/bin/python3.12 /usr/local/bin/python3.11
    do
        candidate=$(resolve_command "$name")
        [ -n "$candidate" ] || continue
        if found_version=$(python_version "$candidate"); then
            selected_python=$candidate
            break
        fi
        [ -n "$unsupported_version" ] || unsupported_version=${found_version:-unknown}
    done
fi

if [ -z "$selected_python" ]; then
    printf '%s\n' \
        "Research Digest requires Python 3.11 or newer." \
        "Install a current Python from python.org or Homebrew, or set" \
        "RESEARCH_DIGEST_PYTHON=/opt/homebrew/bin/python3.12 and rerun this script." \
        "No private runtime was created." >&2
    exit 2
fi

installer_tmp=$(mktemp -d "${TMPDIR:-/tmp}/research-digest-installer.XXXXXX")
cleanup() {
    rm -f -- \
        "$installer_tmp/install-research-digest.py" \
        "$installer_tmp/research_digest-0.5.0-py3-none-any.whl" \
        "$installer_tmp/SHA256SUMS"
    rmdir -- "$installer_tmp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$installer_tmp/SHA256SUMS" "$release_url/SHA256SUMS"
curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$installer_tmp/install-research-digest.py" \
    "$release_url/install-research-digest.py"

expected=$(
    awk '$2 == "install-research-digest.py" { print $1 }' \
        "$installer_tmp/SHA256SUMS"
)
case "$expected" in
    ""|*[!0-9a-fA-F]*)
        printf '%s\n' "SHA256SUMS has no valid installer entry; nothing was installed." >&2
        exit 1
        ;;
esac
if [ "${#expected}" -ne 64 ]; then
    printf '%s\n' "SHA256SUMS has no valid installer entry; nothing was installed." >&2
    exit 1
fi
actual=$(shasum -a 256 "$installer_tmp/install-research-digest.py" | awk '{ print $1 }')
if [ "$actual" != "$expected" ]; then
    printf '%s\n' "Installer SHA-256 verification failed; nothing was installed." >&2
    exit 1
fi

printf 'Using Python %s at %s\n' "$(python_version "$selected_python")" "$selected_python"
action=${1:-install}
if [ "$#" -gt 0 ]; then
    shift
fi
case "$action" in
    install)
        curl --fail --location --proto '=https' --tlsv1.2 \
            --output "$installer_tmp/research_digest-0.5.0-py3-none-any.whl" \
            "$release_url/research_digest-0.5.0-py3-none-any.whl"
        "$selected_python" "$installer_tmp/install-research-digest.py" \
            install --asset-dir "$installer_tmp" "$@"
        ;;
    uninstall)
        "$selected_python" "$installer_tmp/install-research-digest.py" uninstall "$@"
        ;;
    *)
        printf '%s\n' "Usage: $0 [install|uninstall] [options]" >&2
        exit 2
        ;;
esac

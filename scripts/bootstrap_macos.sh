#!/bin/sh
set -eu

minimum_python="3.11"
project_root=${RESEARCH_DIGEST_PROJECT_ROOT:-"$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"}

python_version() {
    "$1" -c '
import sys
print(".".join(str(value) for value in sys.version_info[:3]))
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
' 2>/dev/null
}

resolve_command() {
    case "$1" in
        */*) printf '%s\n' "$1" ;;
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
            "No virtual environment was created." >&2
        exit 2
    fi
    if version=$(python_version "$candidate"); then
        selected_python=$candidate
    else
        unsupported_version=${version:-unknown}
    fi
else
    for name in python3 python3.14 python3.13 python3.12 python3.11; do
        candidate=$(resolve_command "$name")
        [ -n "$candidate" ] || continue
        if version=$(python_version "$candidate"); then
            selected_python=$candidate
            break
        fi
        [ -n "$unsupported_version" ] || unsupported_version=${version:-unknown}
    done
fi

if [ -z "$selected_python" ]; then
    if [ -n "$unsupported_version" ]; then
        found=" Found Python $unsupported_version."
    else
        found=""
    fi
    printf '%s\n' \
        "Research Digest requires Python $minimum_python or newer.$found" \
        "Install a current Python from python.org or Homebrew, or set" \
        "RESEARCH_DIGEST_PYTHON=/absolute/path/to/python3.12 and rerun this script." \
        "No virtual environment was created." >&2
    exit 2
fi

selected_version=$(python_version "$selected_python")
printf 'Using Python %s at %s\n' "$selected_version" "$selected_python"

"$selected_python" -m venv "$project_root/.venv"
"$project_root/.venv/bin/python" -m pip install -e "$project_root"

printf '%s\n' \
    "Research Digest environment is ready." \
    "Next: $project_root/.venv/bin/research-digest install-launcher"

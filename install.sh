#!/usr/bin/env bash
set -euo pipefail

REPO="Bowen-0x00/agy-skills"
REF="${AGY_SKILLS_REF:-main}"
INSTALL_DIR="${AGY_SKILLS_PREFIX:-$HOME/.local/bin}"
BIN_NAME="agy-skills"
UNINSTALL=0

usage() {
  cat <<'EOF'
agy-skills installer

Usage:
  install.sh [--prefix DIR] [--ref BRANCH_OR_TAG] [--uninstall]

Options:
  --prefix DIR   Installation directory (default: ~/.local/bin)
  --ref REF      Git ref/branch/tag to download from (default: main)
  --uninstall    Remove installed agy-skills binary
  -h, --help     Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)
      INSTALL_DIR="${2:?--prefix requires a directory}"
      shift 2
      ;;
    --ref)
      REF="${2:?--ref requires a git ref}"
      shift 2
      ;;
    --uninstall)
      UNINSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

TARGET="$INSTALL_DIR/$BIN_NAME"

if [ "$UNINSTALL" -eq 1 ]; then
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    rm -f "$TARGET"
    echo "Removed $TARGET"
  else
    echo "Not installed at $TARGET"
  fi
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 (>= 3.10) is required." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Error: Python 3.10+ is required, found {sys.version.split()[0]}.")
PY

URL="https://raw.githubusercontent.com/${REPO}/${REF}/src/agy_skills/cli.py"
mkdir -p "$INSTALL_DIR"
TMP_FILE="$(mktemp "${INSTALL_DIR}/.agy-skills.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

echo "Downloading agy-skills (${REF}) from ${URL}..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$TMP_FILE"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP_FILE" "$URL"
else
  echo "Error: curl or wget is required to download agy-skills." >&2
  exit 1
fi

if ! head -n 1 "$TMP_FILE" | grep -q "python3"; then
  echo "Error: downloaded file does not look like a valid Python executable." >&2
  exit 1
fi

chmod +x "$TMP_FILE"
mv "$TMP_FILE" "$TARGET"
trap - EXIT

echo "Installed to: $TARGET"
"$TARGET" --version

case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo ""
    echo "Note: $INSTALL_DIR is not currently in your PATH."
    echo "Add the following line to your shell profile (~/.bashrc or ~/.zshrc):"
    echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
    ;;
esac

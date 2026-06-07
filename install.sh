#!/usr/bin/env bash
#
# Ingress - Simple & Comprehensive Installer
# Supports: Linux (apt/dnf/pacman), macOS (brew), basic Windows (via WSL or manual)
# User's system (Linux with python3.11) is fully supported.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/veilriven-design/ingress-osint/main/install.sh | bash
#   or
#   bash install.sh
#
# What it does:
# - Detects OS and installs core system dependencies (python >=3.10 preferred, pip, git, etc.)
# - Installs media tools (exiftool + ffmpeg) by enabling required repos on RPM-based systems (EPEL + RPM Fusion free+nonfree)
# - Creates a virtual environment (prefers python3.11+ on RHEL 8 family)
# - Installs Ingress with full features ([full] extras)
# - Sets up initial SQLite DB
# - Makes 'ingress' command available (via venv activation or symlink)
# - Prints next steps and security notes
#
# For full power (Postgres, Telegram, etc.) see README after install.
#
# Run with: bash install.sh [--dev] [--no-system-deps]
#
# When run from inside a full local checkout (with src/ingress + correct pyproject.toml),
# it will install *from the current tree* (editable) instead of cloning the public remote.
# This makes the installer useful both for end-users (curl | bash) and for local dev.
#

set -euo pipefail

INSTALL_DIR="${HOME}/.local/share/ingress"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"
REPO_URL="https://github.com/veilriven-design/ingress-osint.git"
BRANCH="main"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[ingress-install]${NC} $1"; }
warn() { echo -e "${YELLOW}[ingress-install]${NC} $1"; }
err() { echo -e "${RED}[ingress-install]${NC} $1" >&2; }

# Parse args
DEV_MODE=false
NO_SYSTEM_DEPS=false
for arg in "$@"; do
  case $arg in
    --dev) DEV_MODE=true ;;
    --no-system-deps) NO_SYSTEM_DEPS=true ;;
  esac
done

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  OS="linux"
  if command -v apt-get &> /dev/null; then
    PKG_MGR="apt"
  elif command -v dnf &> /dev/null; then
    PKG_MGR="dnf"
  elif command -v pacman &> /dev/null; then
    PKG_MGR="pacman"
  else
    PKG_MGR="unknown"
  fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
  OS="macos"
  PKG_MGR="brew"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
  OS="windows"
  warn "Windows detected. Recommended: Use WSL2 + Ubuntu, or install manually."
  PKG_MGR="manual"
else
  warn "Unknown OS. Proceeding with manual assumptions."
  PKG_MGR="manual"
fi

log "Detected OS: $OS ($PKG_MGR)"

# Select a Python >= 3.10 if available (critical on RHEL 8 family where 'python3' is 3.6).
# The project declares requires-python = ">=3.10".
PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  PY="python3"
fi

# System dependencies
if [ "$NO_SYSTEM_DEPS" = false ]; then
  log "Installing system dependencies..."
  case "$PKG_MGR" in
    apt)
      sudo apt-get update -qq
      sudo apt-get install -y -qq python3 python3-pip python3-venv git postgresql-client
      # Media tools (exiftool + ffmpeg) are installed for full 'ingress analyze' support.
      if ! sudo apt-get install -y -qq exiftool ffmpeg; then
        warn "Could not install exiftool and/or ffmpeg via apt. Media analysis will have reduced functionality."
      fi
      ;;
    dnf)
      # Core packages first (must succeed).
      sudo dnf install -y python3 python3-pip python3-virtualenv git postgresql || {
        err "Failed to install core packages via dnf. Aborting."
        exit 1
      }
      # On RHEL/Alma/Rocky 8 (where default python3 is 3.6), try to get Python 3.11 from modules/AppStream.
      if [ "$PY" = "python3" ] && ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        log "Default python3 is too old on this RHEL-family system; attempting to install python3.11..."
        sudo dnf module enable -y python311 2>/dev/null || true
        sudo dnf install -y python3.11 python3.11-pip python3.11-devel 2>/dev/null || true
        if command -v python3.11 >/dev/null 2>&1 && python3.11 -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
          PY="python3.11"
          log "Using python3.11 for venv creation."
        fi
      fi
      # Media tools: exiftool (EPEL) + full ffmpeg (RPM Fusion free + nonfree).
      # The user has indicated that enabling free/nonfree repos is acceptable.
      log "Installing media tools (exiftool + ffmpeg)..."

      # EPEL is required for exiftool on RHEL 8 family.
      sudo dnf install -y epel-release 2>/dev/null || true
      if ! sudo dnf install -y exiftool; then
        warn "Could not install exiftool even with EPEL enabled."
      fi

      # Enable RPM Fusion (both free and nonfree) and install full ffmpeg.
      # This is the reliable way to get a complete ffmpeg on EL8 (with all codecs etc.).
      if ! command -v ffmpeg >/dev/null 2>&1; then
        log "Enabling RPM Fusion free + nonfree repositories for ffmpeg..."
        # --nogpgcheck for the initial release RPMs to avoid interactive GPG prompts in scripts.
        if ! sudo dnf install -y --nogpgcheck \
          "https://download1.rpmfusion.org/free/el/rpmfusion-free-release-8.noarch.rpm" \
          "https://download1.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-8.noarch.rpm"; then
          warn "Failed to enable one or both RPM Fusion repositories."
        fi

        if ! sudo dnf install -y ffmpeg; then
          warn "ffmpeg installation failed after enabling RPM Fusion."
        fi
      fi

      # Report status
      if command -v exiftool >/dev/null 2>&1 && command -v ffmpeg >/dev/null 2>&1; then
        log "Media tools ready: exiftool and ffmpeg installed."
      elif command -v exiftool >/dev/null 2>&1; then
        warn "exiftool is available but ffmpeg is not. Video analysis will be limited."
      elif command -v ffmpeg >/dev/null 2>&1; then
        warn "ffmpeg is available but exiftool is not. Full EXIF/metadata will be limited."
      else
        warn "Media tools (exiftool + ffmpeg) could not be installed. 'ingress analyze' will have reduced functionality."
      fi
      ;;
    pacman)
      sudo pacman -Syu --noconfirm python python-pip git postgresql
      # Media tools for full analysis support.
      if ! sudo pacman -S --noconfirm exiftool ffmpeg; then
        warn "Could not install exiftool and/or ffmpeg. Media analysis will have reduced functionality."
      fi
      ;;
    brew)
      brew update
      brew install python git
      # Media tools for full analysis support.
      if ! brew install exiftool ffmpeg; then
        warn "Could not install exiftool and/or ffmpeg via Homebrew. Media analysis will have reduced functionality."
      fi
      ;;
    *)
      warn "Please manually install: python3, pip, venv, git, exiftool, ffmpeg (and optionally postgresql)"
      ;;
  esac
fi

# Create dirs (venv + launcher live here even for local-source installs)
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# Detect if we're being run from inside a local source tree.
# If so, prefer installing from here (editable) instead of (re)cloning the public remote.
# This makes `bash install.sh` useful for developers and for users who have a full checkout.
SRC_DIR=""
if [ -f "pyproject.toml" ] && [ -d "src/ingress" ]; then
  if grep -q 'name = "ingress-osint"' pyproject.toml 2>/dev/null; then
    SRC_DIR="$(pwd -P 2>/dev/null || pwd)"
    log "Detected local Ingress source tree at $SRC_DIR"
  fi
fi

# Clone or update the canonical copy *only* if we didn't detect a local source tree.
if [ -z "$SRC_DIR" ]; then
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing clone..."
    cd "$INSTALL_DIR"
    git pull origin "$BRANCH" --quiet || true
    SRC_DIR="$INSTALL_DIR"
  else
    log "Cloning Ingress from $REPO_URL ..."
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    SRC_DIR="$INSTALL_DIR"
  fi

  # Sanity check the cloned tree (the public repo is sometimes a stub during development).
  if [ ! -s "$SRC_DIR/pyproject.toml" ] || ! grep -q 'name = "ingress-osint"' "$SRC_DIR/pyproject.toml" 2>/dev/null; then
    err "Cloned tree is missing or has an invalid pyproject.toml (public repo may be empty/stub)."
    err "Re-run this script from inside your full local checkout of the source."
    exit 1
  fi
else
  log "Will install from local source (no clone)."
fi

# At this point SRC_DIR points at a tree with a valid pyproject.toml.

# Create venv (use a Python >= 3.10 when we found one; the venv's python will be used for everything after)
if [ ! -d "$VENV_DIR" ]; then
  log "Creating virtual environment with $PY ..."
  "$PY" -m venv "$VENV_DIR" || {
    # Fallback: some distros ship venv separately or need python3-venv equivalent already installed.
    if command -v python3 >/dev/null 2>&1; then
      warn "Primary python ($PY) venv creation failed; retrying with python3 -m venv"
      python3 -m venv "$VENV_DIR"
    else
      err "Failed to create venv. Ensure python3-venv / python3.11-venv (or equivalent) is installed."
      exit 1
    fi
  }
fi

# Activate and install from the chosen source tree (local checkout or the cloned copy)
log "Installing Ingress (full features) from $SRC_DIR ..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools -q
(
  cd "$SRC_DIR"
  if [ "$DEV_MODE" = true ]; then
    pip install -e ".[full,dev]" -q
  else
    pip install -e ".[full]" -q
  fi
)

# Initial setup (prime a DB under the managed INSTALL_DIR for the installed 'ingress' command)
log "Running initial setup (SQLite DB + schema)..."
mkdir -p "$INSTALL_DIR/data"
"$VENV_DIR/bin/python" -c "
import os
os.chdir('$INSTALL_DIR')
from ingress.storage import ensure_schema
from ingress.config import get_db_url
ensure_schema()
print('DB ready at:', get_db_url())
"

# Create launcher
cat > "$BIN_DIR/ingress" << 'EOF'
#!/usr/bin/env bash
INSTALL_DIR="${HOME}/.local/share/ingress"
VENV_DIR="${INSTALL_DIR}/venv"
source "$VENV_DIR/bin/activate"
exec python -m ingress.cli "$@"
EOF
chmod +x "$BIN_DIR/ingress"

# Ensure ~/.local/bin in PATH (common for user installs)
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  warn "Add \$HOME/.local/bin to your PATH for 'ingress' command."
  echo '  export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc 2>/dev/null || true
  echo '  export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc 2>/dev/null || true
fi

log "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Reload your shell or: source ~/.bashrc"
echo "  2. Run: ingress --help"
echo "  3. Try: ingress demo"
echo "  4. Ingest: ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/"
echo "  5. Watch data: ingress watch   (or modify demo to use DB)"
echo ""
echo "For full features (Telegram, Postgres, media analysis):"
echo "  - Get Telegram API creds: https://my.telegram.org"
if ! command -v exiftool >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "  - Media tools still missing for full 'ingress analyze' support:"
  echo "      exiftool (EXIF/metadata) and ffmpeg (video via ffprobe)"
  echo "    The installer attempted to set them up (EPEL + RPM Fusion on RHEL 8 family)."
  echo "    You may need to enable the repos manually and run: sudo dnf install exiftool ffmpeg"
else
  echo "  - exiftool + ffmpeg detected (full media analysis available)."
fi
echo "  - Postgres: docker compose up -d db ; alembic upgrade head"
echo ""
echo "Security: This is an OSINT tool. Only use on public data. Respect ToS and laws."
echo "Uninstaller: rm -rf $INSTALL_DIR ; rm $BIN_DIR/ingress"
echo ""
log "Welcome to Ingress — military signals as they enter the open domains."
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
# - Detects OS and installs system dependencies (python3, pip, git, exiftool, ffmpeg, etc.)
# - Creates a virtual environment
# - Installs Ingress with full features ([full] extras)
# - Sets up initial SQLite DB
# - Makes 'ingress' command available (via venv activation or symlink)
# - Prints next steps and security notes
#
# For full power (Postgres, Telegram, etc.) see README after install.
#
# Run with: bash install.sh [--dev] [--no-system-deps]

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

# System dependencies
if [ "$NO_SYSTEM_DEPS" = false ]; then
  log "Installing system dependencies..."
  case "$PKG_MGR" in
    apt)
      sudo apt-get update -qq
      sudo apt-get install -y -qq python3 python3-pip python3-venv git exiftool ffmpeg postgresql-client
      ;;
    dnf)
      sudo dnf install -y python3 python3-pip python3-virtualenv git exiftool ffmpeg postgresql
      ;;
    pacman)
      sudo pacman -Syu --noconfirm python python-pip git exiftool ffmpeg postgresql
      ;;
    brew)
      brew update
      brew install python git exiftool ffmpeg
      ;;
    *)
      warn "Please manually install: python3, pip, venv, git, exiftool, ffmpeg (and optionally postgresql)"
      ;;
  esac
fi

# Create dirs
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# Clone or update repo
if [ -d "$INSTALL_DIR/.git" ]; then
  log "Updating existing clone..."
  cd "$INSTALL_DIR"
  git pull origin "$BRANCH" --quiet || true
else
  log "Cloning Ingress..."
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# Create venv
if [ ! -d "$VENV_DIR" ]; then
  log "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Activate and install
log "Installing Ingress (full features)..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools -q
if [ "$DEV_MODE" = true ]; then
  pip install -e ".[full,dev]" -q
else
  pip install -e ".[full]" -q
fi

# Initial setup
log "Running initial setup (SQLite DB + schema)..."
mkdir -p data
"$VENV_DIR/bin/python" -c "
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
echo "  4. Real ingest: ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/"
echo "  5. Watch real data: ingress watch   (or modify demo to use DB)"
echo ""
echo "For full features (Telegram, Postgres, media analysis):"
echo "  - Get Telegram API creds: https://my.telegram.org"
echo "  - Install system tools if missing: exiftool, ffmpeg"
echo "  - Postgres: docker compose up -d db ; alembic upgrade head"
echo ""
echo "Security: This is an OSINT tool. Only use on public data. Respect ToS and laws."
echo "Uninstaller: rm -rf $INSTALL_DIR ; rm $BIN_DIR/ingress"
echo ""
log "Welcome to Ingress — military signals as they enter the open domains."
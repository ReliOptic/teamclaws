#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# TeamClaws v3.2 — One-command installer for Ubuntu 22.04+ (GCP Free Tier)
#
# Usage (after GitHub upload):
#   curl -fsSL https://raw.githubusercontent.com/ReliOptic/teamclaws/main/setup.sh | bash
#
# Or local:
#   bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/ReliOptic/teamclaws"
INSTALL_DIR="$HOME/teamclaws"
VENV_DIR="$INSTALL_DIR/.venv"
BIN_LINK="/usr/local/bin/teamclaws"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[TeamClaws]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── 1. Check OS ───────────────────────────────────────────────────────────
info "Checking system..."
if [[ "$(uname -s)" != "Linux" ]]; then
    error "This installer is for Linux (Ubuntu 22.04+). Got: $(uname -s)"
fi

# ── 2. Install system dependencies ───────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    2>/dev/null || error "apt-get failed. Run with sudo or fix package manager."
success "System packages ready"

# ── 3. Check Python version ───────────────────────────────────────────────
PYTHON=$(command -v python3)
PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo $PY_VER | cut -d. -f1)
PY_MINOR=$(echo $PY_VER | cut -d. -f2)

if [[ $PY_MAJOR -lt 3 ]] || [[ $PY_MAJOR -eq 3 && $PY_MINOR -lt 10 ]]; then
    error "Python 3.10+ required. Found: $PY_VER"
fi
success "Python $PY_VER found"

# ── 4. Download / update TeamClaws ────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning TeamClaws to $INSTALL_DIR..."
    git clone --depth=1 "$REPO_URL" "$INSTALL_DIR"
fi
success "TeamClaws code ready at $INSTALL_DIR"

# ── 5. Create virtual environment ────────────────────────────────────────
info "Setting up Python virtual environment..."
$PYTHON -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q
pip install -e "$INSTALL_DIR" -q
success "Python dependencies installed"

# ── 6. Setup .env ─────────────────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn ".env created from template. Edit it now:"
    warn "  nano $INSTALL_DIR/.env"
    warn "  Add at least one API key (GROQ_API_KEY recommended — free tier)"
else
    info ".env already exists, skipping"
fi

# ── 7. Create data directories ───────────────────────────────────────────
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/logs" "$INSTALL_DIR/workspace"
success "Data directories created"

# ── 8. Create teamclaws wrapper script ───────────────────────────────────
WRAPPER="$INSTALL_DIR/bin/teamclaws"
mkdir -p "$INSTALL_DIR/bin"
cat > "$WRAPPER" << WRAPEOF
#!/usr/bin/env bash
# TeamClaws CLI wrapper
set -a
[[ -f "$INSTALL_DIR/.env" ]] && source "$INSTALL_DIR/.env"
set +a
source "$VENV_DIR/bin/activate"
exec python -m multiclaws "\$@"
WRAPEOF
chmod +x "$WRAPPER"

# Create system-wide symlink (requires sudo)
if sudo ln -sf "$WRAPPER" "$BIN_LINK" 2>/dev/null; then
    success "Installed to $BIN_LINK — run: teamclaws"
else
    warn "Could not create $BIN_LINK (no sudo?)"
    warn "Add to PATH manually: export PATH=\"$INSTALL_DIR/bin:\$PATH\""
    # Try user-local bin
    mkdir -p "$HOME/.local/bin"
    ln -sf "$WRAPPER" "$HOME/.local/bin/teamclaws"
    success "Installed to ~/.local/bin/teamclaws"
fi

# ── 9. Systemd service (optional, auto-start on boot) ────────────────────
if command -v systemctl &>/dev/null; then
    SERVICE_FILE="/etc/systemd/system/teamclaws.service"
    if [[ ! -f "$SERVICE_FILE" ]]; then
        info "Installing systemd service (optional auto-start)..."
        sudo tee "$SERVICE_FILE" > /dev/null << SERVICEEOF
[Unit]
Description=TeamClaws v3.2 Multi-Agent System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$VENV_DIR/bin/python -m multiclaws watchdog
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF
        sudo systemctl daemon-reload
        success "Systemd service installed (not started)"
        info "  Start now:       sudo systemctl start teamclaws"
        info "  Enable on boot:  sudo systemctl enable teamclaws"
    fi
fi

# ── 10. Final instructions ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  TeamClaws v3.2 installed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Add your API key(s):"
echo "     nano $INSTALL_DIR/.env"
echo "     # Recommended: GROQ_API_KEY (free tier at groq.com)"
echo ""
echo "  2. Start chatting:"
echo "     teamclaws chat"
echo ""
echo "  3. Run a Dream Team specialist:"
echo "     teamclaws preset code-reviewer --input 'review this code: ...'"
echo "     teamclaws preset --list"
echo ""
echo "  4. Check status:"
echo "     teamclaws status"
echo "     teamclaws cost"
echo ""
echo -e "${CYAN}  Docs: $INSTALL_DIR/docs/${NC}"
echo ""

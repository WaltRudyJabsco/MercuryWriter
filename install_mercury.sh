#!/usr/bin/env bash
set -euo pipefail

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin)
    DEFAULT_INSTALL_DIR="$HOME/Applications/Mercury-Writer"
    LAUNCHER_NAME="Launch Mercury.command"
    ;;
  Linux)
    DEFAULT_INSTALL_DIR="$HOME/.local/share/mercury-writer"
    LAUNCHER_NAME="launch-mercury.sh"
    ;;
  *)
    echo "Mercury Writer installer currently supports macOS and Linux."
    exit 1
    ;;
esac

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

say() { printf "\n%s\n" "$*"; }

ask_yes_no() {
  local prompt="$1" default="${2:-N}" reply
  if [[ "$default" == "Y" ]]; then
    read -r -p "$prompt [Y/n] " reply || true
    reply="${reply:-Y}"
  else
    read -r -p "$prompt [y/N] " reply || true
    reply="${reply:-N}"
  fi
  [[ "$reply" =~ ^[Yy]$ ]]
}

# macOS and Linux are supported. Homebrew is used when available on either platform.

say "Mercury Writer installer"

echo "Default install location:"
echo "  $DEFAULT_INSTALL_DIR"
echo
echo "Press RETURN to accept the default."
echo "Or type a different full folder path and press RETURN."
echo

read -r -p "Install location [$DEFAULT_INSTALL_DIR]: " INSTALL_DIR || true
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

if [[ "$INSTALL_DIR" == "~" ]]; then
  INSTALL_DIR="$HOME"
elif [[ "$INSTALL_DIR" == "~/"* ]]; then
  INSTALL_DIR="$HOME/${INSTALL_DIR#~/}"
fi

HTML_FILE="$(find "$SOURCE_DIR" -maxdepth 1 -type f -name 'Mercury_Writer*.html' | sort | tail -n 1 || true)"
if [[ -f "$SOURCE_DIR/mercury_server.py" ]]; then
  SERVER_FILE="$SOURCE_DIR/mercury_server.py"
else
  SERVER_FILE="$(find "$SOURCE_DIR" -maxdepth 1 -type f -name 'mercury_server*.py' | sort | tail -n 1 || true)"
fi

if [[ -z "$HTML_FILE" || -z "${SERVER_FILE:-}" ]]; then
  echo "ERROR: Mercury application files were not found beside this installer."
  exit 1
fi

say "Installing Mercury Writer"
mkdir -p "$INSTALL_DIR"
cp "$HTML_FILE" "$INSTALL_DIR/"
cp "$SERVER_FILE" "$INSTALL_DIR/mercury_server.py"
cp "$SOURCE_DIR/mercury" "$INSTALL_DIR/mercury"
chmod 755 "$INSTALL_DIR/mercury"
for extra in README.txt README.md LICENSE mercury_ai.json; do
  [[ -f "$SOURCE_DIR/$extra" ]] && cp "$SOURCE_DIR/$extra" "$INSTALL_DIR/$extra"
done

if ! command -v brew >/dev/null 2>&1; then
  say "Homebrew is not installed."
  if ask_yes_no "Install Homebrew now?" "Y"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    [[ -x /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [[ -x /usr/local/bin/brew ]] && eval "$(/usr/local/bin/brew shellenv)"
  else
    echo "Automatic dependency setup requires Homebrew."
    exit 1
  fi
fi

say "Checking Python 3"
command -v python3 >/dev/null 2>&1 || brew install python
echo "$(python3 --version 2>&1)"

say "Checking Ollama"
command -v ollama >/dev/null 2>&1 || brew install ollama
brew services start ollama >/dev/null 2>&1 || true

say "Local AI model"
echo "  1) Qwen3 4B"
echo "  2) Qwen3 8B"
echo "  3) Both"
echo "  4) Skip model download"
echo
echo "Press RETURN for option 1."
read -r -p "Model choice [1]: " MODEL_CHOICE || true
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "$MODEL_CHOICE" in
  2) ollama pull qwen3:8b ;;
  3) ollama pull qwen3:4b; ollama pull qwen3:8b ;;
  4) echo "Skipping model download." ;;
  *) ollama pull qwen3:4b ;;
esac

say "Optional Web Search"

echo "Mercury's local AI does not require an online account."
echo
echo "If you want Mercury's AI assistant to search the web for"
echo "current information, Web Search requires an Ollama API key."
echo
echo "If you created an Ollama account and prepared an API key"
echo "before installation, choose Y and paste the key now."
echo
echo "If you do not have an API key, choose N."
echo "You can add one later."
echo

if ask_yes_no "Configure Mercury Web Search now?" "N"; then
  read -r -s -p "Paste your Ollama API key: " OLLAMA_KEY
  echo

  if [[ -n "$OLLAMA_KEY" ]]; then
    SECRETS_FILE="$HOME/.zsh_secrets"
    touch "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"

    TMPFILE="$(mktemp)"
    grep -v '^[[:space:]]*export[[:space:]]\+OLLAMA_API_KEY=' "$SECRETS_FILE" > "$TMPFILE" || true
    cat "$TMPFILE" > "$SECRETS_FILE"
    rm -f "$TMPFILE"

    printf '\nexport OLLAMA_API_KEY=%q\n' "$OLLAMA_KEY" >> "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"

    echo
    echo "Web Search configured."
    echo "Your Ollama API key has been saved to ~/.zsh_secrets."
    echo "The secrets file is protected with chmod 600."
    echo "Mercury will load it automatically when you launch the app."
  else
    echo
    echo "No API key was entered. Skipping Web Search setup."
    echo "You can configure it later."
  fi
else
  echo
  echo "Skipping Web Search setup."
  echo "Mercury and its local AI will still work normally."
fi

say "Creating launcher"

LAUNCHER="$INSTALL_DIR/$LAUNCHER_NAME"

cat > "$LAUNCHER" <<'EOF'
#!/usr/bin/env bash

MERCURY_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SERVER="$MERCURY_DIR/mercury_server.py"
LOG="$MERCURY_DIR/mercury-launch.log"

export PATH="/opt/homebrew/bin:/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin:$PATH"

clear
echo "Mercury Writer"
echo "=============="
echo
echo "Application folder:"
echo "  $MERCURY_DIR"
echo

cd "$MERCURY_DIR" || {
  echo "ERROR: Could not enter the Mercury Writer folder."
  read -r -p "Press Return to close this window..."
  exit 1
}

if [[ ! -f "$SERVER" ]]; then
  echo "ERROR: mercury_server.py was not found:"
  echo "  $SERVER"
  read -r -p "Press Return to close this window..."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: Python 3 was not found."
  read -r -p "Press Return to close this window..."
  exit 1
fi

if [[ -f "$HOME/.zsh_secrets" ]]; then
  KEY_LINE="$(grep -E '^[[:space:]]*export[[:space:]]+OLLAMA_API_KEY=' "$HOME/.zsh_secrets" | tail -n 1 || true)"
  [[ -n "$KEY_LINE" ]] && eval "$KEY_LINE"
fi

echo "Python: $(python3 --version 2>&1)"
if command -v ollama >/dev/null 2>&1 && ollama list >/dev/null 2>&1; then
  echo "Local Ollama: reachable"
else
  echo "Local Ollama: not reachable (Mercury will also try configured remote AI hosts)"
fi

echo
echo "Starting Mercury Writer..."
echo "Leave this terminal open while Mercury is running."
echo
echo "Open:"
echo "  http://127.0.0.1:8765"
echo
echo "Press Control-C here to stop Mercury."
echo
echo "------------------------------------------------------------"
echo

python3 "$SERVER" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}

echo
echo "------------------------------------------------------------"
echo "Mercury Writer server stopped (exit status $STATUS)."
echo "Launch log: $LOG"
echo
read -r -p "Press Return to close this window..."
exit "$STATUS"
EOF

chmod 755 "$LAUNCHER"
if [[ "$OS_NAME" == "Darwin" ]]; then
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/mercury" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/mercury" "\$@"
EOF
  chmod 755 "$HOME/.local/bin/mercury"
fi

if [[ "$OS_NAME" == "Linux" ]]; then
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/mercury-writer" <<EOF
#!/usr/bin/env bash
exec "$LAUNCHER"
EOF
  chmod 755 "$HOME/.local/bin/mercury-writer"

  cat > "$HOME/.local/bin/mercury" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/mercury" "\$@"
EOF
  chmod 755 "$HOME/.local/bin/mercury"

  cat > "$HOME/.local/bin/mercurycast" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

MERCURY_DIR="$HOME/.local/share/mercury-writer"
SERVER="$MERCURY_DIR/mercury_server.py"
LOG="$MERCURY_DIR/mercury-server.log"
LOCAL_URL="http://127.0.0.1:8765"

usage() {
  cat <<USAGE
Mercury Writer Tailscale launcher

Usage:
  mercurycast           Start Mercury if needed and expose it privately with Tailscale Serve
  mercurycast status    Show Mercury and Tailscale Serve status
  mercurycast stop      Stop Mercury's Tailscale Serve mapping
  mercurycast local     Start Mercury locally without changing Tailscale Serve
USAGE
}

mercury_running() {
  curl -fsS "$LOCAL_URL" >/dev/null 2>&1
}

start_mercury() {
  if mercury_running; then
    echo "Mercury Writer: already running at $LOCAL_URL"
    return
  fi

  if [[ ! -f "$SERVER" ]]; then
    echo "Mercury Writer server not found:"
    echo "  $SERVER"
    exit 1
  fi

  # Import only Mercury's protected web-search key if present.
  if [[ -f "$HOME/.zsh_secrets" ]]; then
    KEY_LINE="$(grep -E '^[[:space:]]*export[[:space:]]+OLLAMA_API_KEY=' "$HOME/.zsh_secrets" | tail -n 1 || true)"
    [[ -n "$KEY_LINE" ]] && eval "$KEY_LINE"
  fi

  echo "Starting Mercury Writer..."
  (
    cd "$MERCURY_DIR"
    nohup python3 "$SERVER" >"$LOG" 2>&1 &
  )

  for _ in {1..20}; do
    if mercury_running; then
      echo "Mercury Writer: running at $LOCAL_URL"
      return
    fi
    sleep 0.25
  done

  echo "Mercury Writer did not become ready."
  echo "Log:"
  echo "  $LOG"
  exit 1
}

show_status() {
  if mercury_running; then
    echo "Mercury Writer: running at $LOCAL_URL"
  else
    echo "Mercury Writer: not running"
  fi
  echo
  if command -v tailscale >/dev/null 2>&1; then
    tailscale serve status || true
  else
    echo "Tailscale: command not found"
  fi
}

case "${1:-start}" in
  start)
    start_mercury
    if ! command -v tailscale >/dev/null 2>&1; then
      echo "Tailscale is not installed or not on PATH."
      exit 1
    fi
    echo "Publishing Mercury privately on your tailnet..."
    tailscale serve --bg 8765
    echo
    show_status
    ;;
  local)
    start_mercury
    ;;
  status)
    show_status
    ;;
  stop)
    if command -v tailscale >/dev/null 2>&1; then
      # Reset only if Mercury owns the root mapping. This mirrors the simple
      # single-root Serve setup used by Mercury; LOOK/Future Crash need not depend on it.
      tailscale serve reset
      echo "Tailscale Serve configuration reset."
      echo "Mercury itself may still be running locally at $LOCAL_URL"
    else
      echo "Tailscale: command not found"
      exit 1
    fi
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
EOF
  chmod 755 "$HOME/.local/bin/mercurycast"

  mkdir -p "$HOME/.config/mercury"
  cat > "$HOME/.config/mercury/service.json" <<EOF
{
  "name": "Mercury Writer",
  "service": "mercury",
  "local_url": "http://127.0.0.1:8765",
  "port": 8765,
  "launcher": "$HOME/.local/bin/mercury-writer",
  "cast_command": "$HOME/.local/bin/mercurycast",
  "status_command": "$HOME/.local/bin/mercurycast status"
}
EOF

  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/mercury-writer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mercury Writer
Comment=Local-first writing studio
Exec=$HOME/.local/bin/mercury-writer
Terminal=true
Categories=Office;TextEditor;
EOF
fi

if [[ ! -x "$LAUNCHER" ]]; then
  echo
  echo "ERROR: Could not make the launcher executable:"
  echo "  $LAUNCHER"
  exit 1
fi

say "Installation complete"
echo "Mercury Writer is installed at:"
echo "  $INSTALL_DIR"
echo
echo "Double-click:"
echo "  Launch Mercury.command"
echo
echo "The launcher will keep Terminal open while the server is running."
echo
echo "The installer has already set the launcher executable permission."

# Mercury 1.4 explicit offline documents zone; outside app install.
MERCURY_CONFIG="$INSTALL_DIR/mercury_config.json"
if [[ ! -f "$MERCURY_CONFIG" ]]; then printf '{\n  "documents_dir": "%s/Mercury Writer Documents"\n}\n' "$HOME" > "$MERCURY_CONFIG"; fi
mkdir -p "$HOME/Mercury Writer Documents"

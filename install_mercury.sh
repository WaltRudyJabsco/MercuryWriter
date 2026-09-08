#!/usr/bin/env bash
set -euo pipefail

DEFAULT_INSTALL_DIR="$HOME/Applications/Mercury-Writer"
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS only."
  exit 1
fi

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
for extra in README.txt README.md LICENSE; do
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
LAUNCHER="$INSTALL_DIR/Launch Mercury.command"
cat > "$LAUNCHER" <<'EOF'
#!/bin/bash

MERCURY_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SERVER="$MERCURY_DIR/mercury_server.py"
LOG="$MERCURY_DIR/mercury-launch.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

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

# Import only the API key from Mercury's protected secrets file.
# Do not source the user's entire shell configuration.
if [[ -f "$HOME/.zsh_secrets" ]]; then
  KEY_LINE="$(grep -E '^[[:space:]]*export[[:space:]]+OLLAMA_API_KEY=' "$HOME/.zsh_secrets" | tail -n 1 || true)"
  [[ -n "$KEY_LINE" ]] && eval "$KEY_LINE"
fi

echo "Python: $(python3 --version 2>&1)"
if command -v ollama >/dev/null 2>&1 && ollama list >/dev/null 2>&1; then
  echo "Ollama: service reachable"
else
  echo "Ollama: WARNING — service not reachable"
fi

echo
echo "Starting Mercury Writer..."
echo "Leave this Terminal window open while Mercury is running."
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

# Verify the launcher really is executable before declaring success.
if [[ ! -x "$LAUNCHER" ]]; then
  echo
  echo "ERROR: Could not make the launcher executable:"
  echo "  $LAUNCHER"
  echo
  echo "You can repair it manually with:"
  echo "  chmod 755 \"$LAUNCHER\""
  exit 1
fi

echo "Launcher permissions set:"
ls -l "$LAUNCHER"

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

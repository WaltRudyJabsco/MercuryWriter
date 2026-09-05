#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Mercury Writer"
DEFAULT_INSTALL_DIR="$HOME/Applications/Mercury-Writer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
echo "This will:"
echo "  • copy Mercury Writer into your home Applications folder"
echo "  • install Python 3 and Ollama if needed"
echo "  • start Ollama"
echo "  • download a local Qwen3 model"
echo "  • optionally configure an Ollama Web Search API key"
echo
echo "Mercury itself has no pip/npm dependencies."

read -r -p "Install location [$DEFAULT_INSTALL_DIR]: " INSTALL_DIR || true
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

HTML_FILE="$(find "$SCRIPT_DIR" -maxdepth 1 -type f -name 'Mercury_Writer*.html' | sort | tail -n 1 || true)"
SERVER_FILE=""
if [[ -f "$SCRIPT_DIR/mercury_server.py" ]]; then
  SERVER_FILE="$SCRIPT_DIR/mercury_server.py"
else
  SERVER_FILE="$(find "$SCRIPT_DIR" -maxdepth 1 -type f -name 'mercury_server*.py' | sort | tail -n 1 || true)"
fi

if [[ -z "$HTML_FILE" || -z "$SERVER_FILE" ]]; then
  echo
  echo "Could not find the Mercury HTML and server files beside this installer."
  echo "Keep install_mercury.sh in the same folder as:"
  echo "  Mercury_Writer_*.html"
  echo "  mercury_server.py"
  exit 1
fi

say "Installing Mercury files"
mkdir -p "$INSTALL_DIR"
cp "$HTML_FILE" "$INSTALL_DIR/"
cp "$SERVER_FILE" "$INSTALL_DIR/mercury_server.py"
for extra in README.txt README.md LICENSE; do
  [[ -f "$SCRIPT_DIR/$extra" ]] && cp "$SCRIPT_DIR/$extra" "$INSTALL_DIR/$extra"
done

if ! command -v brew >/dev/null 2>&1; then
  say "Homebrew is not installed."
  if ask_yes_no "Install Homebrew now?" "Y"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -x /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
      eval "$(/usr/local/bin/brew shellenv)"
    fi
  else
    echo "Homebrew is required for the automatic dependency setup."
    exit 1
  fi
fi

say "Checking Python 3"
if ! command -v python3 >/dev/null 2>&1; then
  brew install python
else
  echo "Python found: $(python3 --version 2>&1)"
fi

say "Checking Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  brew install ollama
else
  echo "Ollama found: $(ollama --version 2>&1 | head -n 1)"
fi

say "Starting Ollama"
brew services start ollama >/dev/null 2>&1 || true

for _ in {1..15}; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

say "Choose a local AI model"
echo "  1) Qwen3 4B  — lighter; good default for 8 GB machines"
echo "  2) Qwen3 8B  — stronger; recommended starting point for 16 GB+"
echo "  3) Both"
read -r -p "Model choice [1]: " MODEL_CHOICE || true
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "$MODEL_CHOICE" in
  2) ollama pull qwen3:8b ;;
  3)
    ollama pull qwen3:4b
    ollama pull qwen3:8b
    ;;
  *) ollama pull qwen3:4b ;;
esac

say "Optional Web Search"
if ask_yes_no "Do you want to configure an Ollama API key for Mercury Web Search now?" "N"; then
  read -r -s -p "Paste your Ollama API key: " OLLAMA_KEY
  echo
  if [[ -n "$OLLAMA_KEY" ]]; then
    ZSHRC="$HOME/.zshrc"
    touch "$ZSHRC"
    TMPFILE="$(mktemp)"
    grep -v '^export OLLAMA_API_KEY=' "$ZSHRC" > "$TMPFILE" || true
    cat "$TMPFILE" > "$ZSHRC"
    rm -f "$TMPFILE"
    printf '\nexport OLLAMA_API_KEY=%q\n' "$OLLAMA_KEY" >> "$ZSHRC"
    export OLLAMA_API_KEY="$OLLAMA_KEY"
    echo "Ollama API key added to ~/.zshrc."
  fi
fi

LAUNCHER="$INSTALL_DIR/Launch Mercury.command"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -e
cd "$INSTALL_DIR"
source "\$HOME/.zshrc" >/dev/null 2>&1 || true
python3 mercury_server.py
EOF
chmod +x "$LAUNCHER"

say "Installation complete"
echo "Mercury Writer is installed at:"
echo "  $INSTALL_DIR"
echo
echo "To launch it later, double-click:"
echo "  Launch Mercury.command"
echo
echo "Or use Terminal:"
echo "  cd \"$INSTALL_DIR\""
echo "  python3 mercury_server.py"
echo
echo "Then open:"
echo "  http://127.0.0.1:8765"
echo
echo "Keep the Terminal/server window open while using Mercury."
echo "Press Control-C there to stop Mercury."

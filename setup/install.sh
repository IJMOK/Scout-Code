#!/usr/bin/env bash
# Set up a Raspberry Pi 5 for Scout Code. Run while the Pi HAS internet.
#
# On the main Pi (runs the website and an AI):
#     sudo ./setup/install.sh --role basecamp
# On the second Pi (just an AI helper), using the key basecamp prints:
#     sudo ./setup/install.sh --role worker --key <KEY>
#
# Safe to run again: it updates what's there.
set -euo pipefail

ROLE=""
KEY=""
WORKER_HOST="scout-worker.local"
LLAMA_REF="${LLAMA_REF:-b11374}"   # tested llama.cpp release; override to try a newer one
SCOUT_DIR=/opt/scout
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --worker-host) WORKER_HOST="$2"; shift 2 ;;
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done
if [[ "$ROLE" != "basecamp" && "$ROLE" != "worker" ]]; then
  echo "Usage: sudo $0 --role basecamp|worker [--key KEY]"; exit 1
fi
if [[ $EUID -ne 0 ]]; then echo "Please run with sudo."; exit 1; fi
RUN_USER="${SUDO_USER:-pi}"

step() { echo; echo "==> $*"; }

step "Installing system packages"
apt-get update
apt-get install -y git cmake build-essential python3-venv python3-pip avahi-daemon curl

step "Setting hostname"
if [[ "$ROLE" == "basecamp" ]]; then NEW_HOST=scout; else NEW_HOST=scout-worker; fi
if [[ "$(hostname)" != "$NEW_HOST" ]]; then
  hostnamectl set-hostname "$NEW_HOST"
  sed -i "s/127.0.1.1.*/127.0.1.1\t$NEW_HOST/" /etc/hosts
  systemctl restart avahi-daemon
fi
echo "This Pi is now $NEW_HOST.local"

mkdir -p "$SCOUT_DIR"/{models,data}
chown -R "$RUN_USER":"$RUN_USER" "$SCOUT_DIR"

step "Building llama.cpp ($LLAMA_REF). This takes about 10 minutes on a Pi 5."
if [[ ! -d "$SCOUT_DIR/llama.cpp/.git" ]]; then
  sudo -u "$RUN_USER" git clone https://github.com/ggml-org/llama.cpp "$SCOUT_DIR/llama.cpp"
fi
sudo -u "$RUN_USER" git -C "$SCOUT_DIR/llama.cpp" fetch --tags --depth 1 origin "refs/tags/$LLAMA_REF:refs/tags/$LLAMA_REF"
sudo -u "$RUN_USER" git -C "$SCOUT_DIR/llama.cpp" checkout -q "$LLAMA_REF"
sudo -u "$RUN_USER" cmake -S "$SCOUT_DIR/llama.cpp" -B "$SCOUT_DIR/llama.cpp/build" \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF
sudo -u "$RUN_USER" cmake --build "$SCOUT_DIR/llama.cpp/build" --config Release -j4 --target llama-server llama-bench

step "Downloading the AI model"
sudo -u "$RUN_USER" MODELS_DIR="$SCOUT_DIR/models" "$APP_DIR/setup/download-models.sh"

step "Python environment"
sudo -u "$RUN_USER" python3 -m venv "$SCOUT_DIR/venv"
sudo -u "$RUN_USER" "$SCOUT_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$SCOUT_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

step "AI access key"
# Stops anyone on the Wi-Fi chatting to the AI directly, around the safety filter.
if [[ -z "$KEY" ]]; then
  if [[ -s "$SCOUT_DIR/llm-key" ]]; then KEY="$(cat "$SCOUT_DIR/llm-key")"
  elif [[ "$ROLE" == "worker" ]]; then echo "Worker needs --key (printed at the end of the basecamp install)."; exit 1
  else KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"; fi
fi
echo "$KEY" > "$SCOUT_DIR/llm-key"
chmod 600 "$SCOUT_DIR/llm-key"
chown "$RUN_USER":"$RUN_USER" "$SCOUT_DIR/llm-key"

step "Installing services"
render() {
  sed -e "s#@USER@#$RUN_USER#g" -e "s#@SCOUT_DIR@#$SCOUT_DIR#g" -e "s#@APP_DIR@#$APP_DIR#g" "$1" > "/etc/systemd/system/$(basename "$1")"
}
render "$APP_DIR/setup/systemd/scout-llm.service"
render "$APP_DIR/setup/systemd/scout-stats.service"
SERVICES=(scout-llm scout-stats)

if [[ "$ROLE" == "basecamp" ]]; then
  render "$APP_DIR/setup/systemd/scout-portal.service"
  SERVICES+=(scout-portal)
  CONFIG="$SCOUT_DIR/data/config.json"
  if [[ ! -s "$CONFIG" ]]; then
    cat > "$CONFIG" <<EOF
{
  "event_name": "Scout Code Game Jam",
  "workers": [
    {"name": "basecamp", "llm": "http://127.0.0.1:8080", "stats": "http://127.0.0.1:8099", "api_key_file": "$SCOUT_DIR/llm-key"},
    {"name": "worker", "llm": "http://$WORKER_HOST:8080", "stats": "http://$WORKER_HOST:8099", "api_key_file": "$SCOUT_DIR/llm-key"}
  ]
}
EOF
    chown "$RUN_USER":"$RUN_USER" "$CONFIG"
  fi
fi

systemctl daemon-reload
systemctl enable --now "${SERVICES[@]}"
systemctl restart "${SERVICES[@]}"

echo
echo "================================================================"
echo " ✅ $NEW_HOST is set up as the $ROLE."
if [[ "$ROLE" == "basecamp" ]]; then
  sleep 3
  echo
  echo " Website:        http://scout.local"
  echo " Leader page:    http://scout.local/leader"
  echo " Leader PIN:     $(cat "$SCOUT_DIR/data/leader-pin.txt" 2>/dev/null || echo 'see: journalctl -u scout-portal')"
  echo
  echo " Now set up the second Pi with:"
  echo "   sudo ./setup/install.sh --role worker --key $KEY"
fi
echo
echo " Check speed with:  $SCOUT_DIR/venv/bin/python $APP_DIR/setup/benchmark.py"
echo "================================================================"

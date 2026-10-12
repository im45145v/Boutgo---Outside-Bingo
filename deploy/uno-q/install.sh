#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SERVICE_NAME="outside-bingo"
SERVICE_TEMPLATE="$SCRIPT_DIR/outside-bingo.service"

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  echo "Warning: expected an ARM64 UNO Q, but detected $(uname -m)." >&2
fi

RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

echo "Installing Outside Bingo from $APP_DIR for user $RUN_USER..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Add API keys there to enable live services."
fi

escaped_app_dir="$(printf '%s' "$APP_DIR" | sed 's/[&|]/\\&/g')"
sed \
  -e "s|__USER__|$RUN_USER|g" \
  -e "s|__GROUP__|$RUN_GROUP|g" \
  -e "s|__APP_DIR__|$escaped_app_dir|g" \
  "$SERVICE_TEMPLATE" | sudo tee "/etc/systemd/system/$SERVICE_NAME.service" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME.service"

echo "Waiting for the local health check..."
for _ in {1..20}; do
  if curl --fail --silent --show-error http://127.0.0.1:5000/health; then
    echo
    board_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "Outside Bingo is running."
    echo "Open: http://${board_ip:-<uno-q-ip>}:5000"
    exit 0
  fi
  sleep 1
done

echo "The service did not become healthy. Recent logs:" >&2
sudo journalctl -u "$SERVICE_NAME.service" -n 50 --no-pager >&2
exit 1


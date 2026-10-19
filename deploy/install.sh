#!/usr/bin/env bash
# Install / upgrade massive-access on an Ubuntu 24.04 server. Idempotent.
#
#   git clone https://github.com/zen-tradings/zen-massive-data-access
#   cd zen-massive-data-access && sudo ./deploy/install.sh
#
# Upgrade: git pull && sudo ./deploy/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/massive-access
ETC=/etc/massive-access
USER_NAME=massive
UNIT=massive-access-closes

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 1; }

echo "==> packages"
if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3-venv
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version' \
    || { echo "python >= 3.11 required" >&2; exit 1; }

echo "==> service user '$USER_NAME'"
id -u "$USER_NAME" >/dev/null 2>&1 \
    || useradd --system --no-create-home --home-dir /nonexistent \
               --shell /usr/sbin/nologin "$USER_NAME"

echo "==> venv $PREFIX/venv (pinned deps from deploy/requirements.lock)"
install -d -m 0755 "$PREFIX"
[[ -x $PREFIX/venv/bin/python ]] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q --require-hashes -r "$REPO/deploy/requirements.lock"
"$PREFIX/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO"

echo "==> config $ETC"
install -d -m 0750 -o root -g "$USER_NAME" "$ETC"
if [[ ! -f $ETC/closes.env ]]; then
    install -m 0640 -o root -g "$USER_NAME" "$REPO/deploy/closes.env.example" "$ETC/closes.env"
    echo "    created $ETC/closes.env (edit SYMBOLS / LOOKBACK_DAYS / MIN_SESSIONS)"
fi
if [[ ! -s $ETC/key ]]; then
    if [[ -t 0 ]]; then
        read -rsp "    Massive API key (input hidden): " key; echo
        [[ -n $key ]] || { echo "empty key" >&2; exit 1; }
        (umask 077; printf '%s\n' "$key" > "$ETC/key")
        unset key
    else
        echo "    no $ETC/key yet: create it, then rerun this script" >&2
        exit 1
    fi
fi
chown root:"$USER_NAME" "$ETC/key"
chmod 0640 "$ETC/key"

echo "==> systemd units"
install -m 0644 "$REPO/deploy/$UNIT.service" "$REPO/deploy/$UNIT.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now "$UNIT.timer"

echo "==> smoke test (as $USER_NAME, no write)"
sudo -u "$USER_NAME" env MASSIVE_CONFIG_FILE="$ETC/key" \
    "$PREFIX/venv/bin/massive-access" key
sudo -u "$USER_NAME" env MASSIVE_CONFIG_FILE="$ETC/key" \
    "$PREFIX/venv/bin/massive-access" closes SPY --lookback-days 10

cat <<EOF

Done. Next scheduled run:
  systemctl list-timers $UNIT.timer
Run now / inspect:
  sudo systemctl start $UNIT.service
  journalctl -u $UNIT.service -n 50
  ls -l /var/lib/massive-access
EOF

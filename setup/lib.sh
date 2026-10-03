# Shared helpers for install.sh and update-services.sh. Source, don't run.

# Write a systemd unit from setup/systemd/, filling in this Pi's paths and user.
render_unit() {
  sed -e "s#@USER@#$RUN_USER#g" -e "s#@SCOUT_DIR@#$SCOUT_DIR#g" -e "s#@APP_DIR@#$APP_DIR#g" \
    "$1" > "/etc/systemd/system/$(basename "$1")"
}

# Let the Scout Code user power the Pi off (and nothing else) without a password,
# so the leader dashboard's "Shut down both Pis" button works.
install_shutdown_permission() {
  local rule="/etc/sudoers.d/scout-shutdown"
  local tmp
  tmp="$(mktemp)"
  echo "$RUN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff" > "$tmp"
  # Never install a broken sudoers file: check it first.
  if visudo -cf "$tmp" >/dev/null; then
    install -m 0440 -o root -g root "$tmp" "$rule"
  else
    echo "⚠️  Could not set up the shutdown permission; the dashboard button won't work on this Pi." >&2
  fi
  rm -f "$tmp"
}

# If a model comparison was cut short (e.g. the Pi crashed), put the original AI model back.
restore_model_after_crash() {
  local marker="$SCOUT_DIR/models/.compare-restore"
  if [[ -f "$marker" ]]; then
    local target
    target="$(cat "$marker")"
    if [[ -f "$target" ]]; then
      ln -sfn "$target" "$SCOUT_DIR/models/current.gguf"
      echo "⚠️  A model comparison didn't finish last time: the AI is back on $(basename "$target")."
    fi
    rm -f "$marker"
  fi
}

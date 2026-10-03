# Shared helpers for install.sh and update-services.sh. Source, don't run.

# Write a systemd unit from setup/systemd/, filling in this Pi's paths and user.
render_unit() {
  sed -e "s#@USER@#$RUN_USER#g" -e "s#@SCOUT_DIR@#$SCOUT_DIR#g" -e "s#@APP_DIR@#$APP_DIR#g" \
    "$1" > "/etc/systemd/system/$(basename "$1")"
}

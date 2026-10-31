#!/usr/bin/env bash
# Run on Oracle over SSH. Snapshots survive a failed rollback for manual recovery.
set -euo pipefail
release_sha="${1:?Expected deployment commit}"
deploy_root="${DROPFIRE_DEPLOY_ROOT:-/home/ubuntu/dropfire}"
web_root="${DROPFIRE_WEB_ROOT:-/var/www/dropfire}"
health_url="${DROPFIRE_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
cd "$deploy_root"

# Refuse to overwrite server-side edits, and verify a healthy rollback baseline.
test -z "$(git status --porcelain --untracked-files=no)"
git fetch origin main
git merge-base --is-ancestor "$release_sha" origin/main
previous_sha="$(git rev-parse HEAD)"
curl --fail --silent --show-error --max-time 5 "$health_url" > /dev/null

backup_dir="$(mktemp -d "${deploy_root%/*}/dropfire-backup.XXXXXX")"
rollback_ready=false
service_touched=false
health_check() {
  local attempt
  for attempt in {1..10}; do
    if curl --fail --silent --show-error --max-time 5 "$health_url"; then
      return 0
    fi
    sleep 2
  done
  return 1
}
rollback() {
  echo "Restoring commit $previous_sha and saved runtime files."
  git -C "$deploy_root" checkout --detach "$previous_sha" &&
    mv "$deploy_root/server/.venv" "$backup_dir/failed-venv" &&
    mv "$backup_dir/venv" "$deploy_root/server/.venv" &&
    sudo cp -a "$backup_dir/web/." "$web_root/" || return 1
  if "$service_touched"; then
    sudo systemctl restart dropfire &&
      sudo systemctl reload caddy || return 1
  fi
  health_check
}
finish() {
  local result="$1"
  trap - EXIT
  if (( result != 0 )) && "$rollback_ready"; then
    echo "::error::Deployment failed; rolling back to $previous_sha."
    if rollback; then
      echo "Rollback succeeded. Deployment remains failed."
    else
      echo "::error::ROLLBACK FAILED. Recovery snapshot: $backup_dir"
      sudo systemctl status dropfire --no-pager || true
      exit "$result"
    fi
  fi
  sudo rm -rf -- "$backup_dir"
  exit "$result"
}
trap 'finish $?' EXIT

# Save the actual installed dependencies and published frontend, not a rebuild.
cp -a server/.venv "$backup_dir/venv"
mkdir "$backup_dir/web"
sudo cp -a "$web_root/." "$backup_dir/web/"
rollback_ready=true

git checkout --detach "$release_sha"
test "$(git rev-parse HEAD)" = "$release_sha"
server/.venv/bin/pip install --requirement server/requirements.txt
cd client
npm ci
npm run build
sudo cp -a dist/. "$web_root/"
sudo chown -R caddy:caddy "$web_root"
service_touched=true
sudo systemctl restart dropfire
sudo systemctl reload caddy
health_check
echo "Deployment succeeded: $release_sha"

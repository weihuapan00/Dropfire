"""Exercise the real deployment script with isolated server commands and files."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("scenario", ["success", "build", "health", "restart", "rollback_failure", "dirty"])
def test_deploy_restores_previous_release_on_failure(tmp_path, scenario):
    root = tmp_path / "repo"
    web = tmp_path / "web"
    commands = tmp_path / "commands"
    for directory in (root / "client/dist", root / "server/.venv/bin", web, commands):
        directory.mkdir(parents=True)
    state = tmp_path / "sha"
    state.write_text("old")
    (web / "index.html").write_text("old frontend")
    (root / "client/dist/index.html").write_text("new frontend")
    marker = root / "server/.venv/installed"
    marker.write_text("old dependencies")

    def executable(path, body):
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    executable(commands / "git", """
if [[ "${1:-}" == "-C" ]]; then shift 2; fi
case "$1" in
  status) if [[ "$TEST_SCENARIO" == "dirty" ]]; then echo " M server/app/main.py"; fi ;;
  fetch|merge-base) exit 0 ;;
  rev-parse) cat "$TEST_STATE" ;;
  checkout) printf '%s' "$3" > "$TEST_STATE" ;;
  *) exit 1 ;;
esac
""")
    executable(root / "server/.venv/bin/pip",
               'echo "new dependencies" > "$DROPFIRE_DEPLOY_ROOT/server/.venv/installed"\n')
    executable(commands / "npm", """
if [[ "$*" == "run build" && "$TEST_SCENARIO" == "build" ]]; then exit 1; fi
""")
    executable(commands / "curl", """
if [[ "$TEST_SCENARIO" == "health" && "$(cat "$TEST_STATE")" == "new" ]]; then exit 1; fi
if [[ "$TEST_SCENARIO" == "rollback_failure" && -f "$TEST_STATE.started" ]]; then exit 1; fi
echo '{"status":"ok"}' 
""")
    executable(commands / "sleep", "exit 0\n")
    executable(commands / "sudo", """
case "$1" in
  systemctl)
    touch "$TEST_STATE.started"
    if [[ "$TEST_SCENARIO" == "restart" && "${2:-}" == "restart" && "$(cat "$TEST_STATE")" == "new" ]]; then exit 1; fi
    exit 0 ;;
  chown) exit 0 ;;
  *) exec "$@" ;;
esac
""")
    env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}",
               DROPFIRE_DEPLOY_ROOT=str(root), DROPFIRE_WEB_ROOT=str(web),
               TEST_STATE=str(state), TEST_SCENARIO=scenario)
    script = Path(__file__).resolve().parents[2] / "scripts/deploy.sh"
    result = subprocess.run(["bash", str(script), "new"], env=env,
                            capture_output=True, text=True)
    if scenario == "success":
        assert result.returncode == 0, result.stdout + result.stderr
        assert state.read_text() == "new"
        assert (web / "index.html").read_text() == "new frontend"
    elif scenario == "dirty":
        assert result.returncode != 0
        assert state.read_text() == "old"
        assert marker.read_text() == "old dependencies"
    elif scenario == "rollback_failure":
        assert result.returncode != 0
        assert "ROLLBACK FAILED" in result.stdout
        assert list(tmp_path.glob("dropfire-backup.*"))
        return
    else:
        assert result.returncode != 0
        assert "Rollback succeeded" in result.stdout, result.stdout + result.stderr
        assert state.read_text() == "old"
        assert marker.read_text() == "old dependencies"
        assert (web / "index.html").read_text() == "old frontend"
    assert not list(tmp_path.glob("dropfire-backup.*"))

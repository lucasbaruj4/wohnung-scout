#!/usr/bin/env python3
"""Install the local collector service, with optional Windows logon startup."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-startup", action="store_true",
                        help="Also keep WSL running through a hidden Windows logon task")
    args = parser.parse_args()
    distro = os.environ.get("WSL_DISTRO_NAME")
    if args.windows_startup and not distro:
        parser.error("Windows startup setup must run inside WSL.")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        parser.error("Run ./scripts/start.sh once to install dependencies, then retry.")
    subprocess.run(["systemctl", "--user", "show-environment"], check=True, stdout=subprocess.DEVNULL)
    unit = Path.home() / ".config/systemd/user/wohnung-scout.service"
    was_active = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", unit.name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    content = f"""[Unit]
Description=Wohnung Scout local apartment collector
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory={quote(ROOT)[1:-1]}
ExecStart={quote(python)} {quote(ROOT / 'app.py')}
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=10
NoNewPrivileges=true
UMask=0077

[Install]
WantedBy=default.target
"""
    changed = not unit.exists() or unit.read_text() != content
    if changed:
        unit.parent.mkdir(parents=True, exist_ok=True)
        temporary = unit.with_suffix(".service.tmp")
        temporary.write_text(content)
        temporary.replace(unit)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", unit.name], check=True)
    if changed and was_active:
        subprocess.run(["systemctl", "--user", "restart", unit.name], check=True)
    subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit.name], check=True)
    print("Collector service is enabled. Repeating this installer keeps an unchanged service running.")
    if args.windows_startup:
        script = subprocess.check_output(
            ["wslpath", "-w", str(ROOT / "scripts/install-windows-startup.ps1")], text=True
        ).strip()
        subprocess.run([
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", script, "-Distro", distro,
        ], check=True)


if __name__ == "__main__":
    main()

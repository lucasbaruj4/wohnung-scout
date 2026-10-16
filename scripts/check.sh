#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python="${PYTHON:-.venv/bin/python}"
command -v "$python" >/dev/null 2>&1 || python=python3
"$python" -m unittest discover -s tests -v
bash -n scripts/*.sh
./scripts/check-secrets.sh

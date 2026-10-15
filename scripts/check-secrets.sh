#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

private_files=$(git ls-files -- '.env' '.env.*' '*.sqlite' '*.sqlite3' '*.db' '*.pem' '*.key' 'data/*')
if [[ -n "$private_files" ]]; then
  printf 'Remove credential and runtime files from Git before publishing:\n%s\n' "$private_files" >&2
  exit 1
fi

version=8.30.1
case "$(uname -s):$(uname -m)" in
  Linux:x86_64) platform=linux_x64 ;;
  Linux:aarch64|Linux:arm64) platform=linux_arm64 ;;
  Darwin:x86_64) platform=darwin_x64 ;;
  Darwin:arm64) platform=darwin_arm64 ;;
  *) printf 'Unsupported platform. Run this check on Linux, macOS, or WSL.\n' >&2; exit 1 ;;
esac
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
archive="gitleaks_${version}_${platform}.tar.gz"
base="https://github.com/gitleaks/gitleaks/releases/download/v${version}"
curl --fail --silent --show-error --location --max-time 60 "$base/$archive" -o "$scratch/$archive"
curl --fail --silent --show-error --location --max-time 60 "$base/gitleaks_${version}_checksums.txt" -o "$scratch/checksums.txt"
(
  cd "$scratch"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --ignore-missing --check checksums.txt
  else
    shasum -a 256 --ignore-missing --check checksums.txt
  fi
)
tar -xzf "$scratch/$archive" -C "$scratch" gitleaks
"$scratch/gitleaks" git . --redact --no-banner --log-opts=--all

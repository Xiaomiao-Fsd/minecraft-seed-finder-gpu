#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-v$(cat "$ROOT/VERSION")}" 
VERSION="${VERSION#v}"
NAME="minecraft-seed-finder-gpu-v${VERSION}"
DIST="$ROOT/dist"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$DIST"
mkdir -p "$TMP/$NAME"

copy_file() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$TMP/$NAME/$dst")"
  cp "$ROOT/$src" "$TMP/$NAME/$dst"
}

copy_file README.md README.md
copy_file VERSION VERSION
copy_file config.example.json config.example.json
copy_file seed_finder.py seed_finder.py
copy_file seed_cluster_runner.py seed_cluster_runner.py
copy_file run_seed_cluster.sh run_seed_cluster.sh
copy_file slime_prefilter.c slime_prefilter.c
copy_file slime_prefilter_cuda.cu slime_prefilter_cuda.cu
copy_file ocean_monument_filter.c ocean_monument_filter.c
copy_file all_biomes_filter.c all_biomes_filter.c
copy_file fortress_crossroads_filter.c fortress_crossroads_filter.c
copy_file .gitignore .gitignore
copy_file scripts/package_release.sh scripts/package_release.sh

chmod +x "$TMP/$NAME/run_seed_cluster.sh" "$TMP/$NAME/seed_cluster_runner.py" "$TMP/$NAME/scripts/package_release.sh"

tar -C "$TMP" -czf "$DIST/$NAME.tar.gz" "$NAME"

if command -v zip >/dev/null 2>&1; then
  (cd "$TMP" && zip -qr "$DIST/$NAME.zip" "$NAME")
else
  python3 - "$TMP" "$DIST/$NAME.zip" "$NAME" <<'PY'
import sys, zipfile
from pathlib import Path
base = Path(sys.argv[1])
out = Path(sys.argv[2])
name = sys.argv[3]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in (base / name).rglob('*'):
        z.write(path, path.relative_to(base))
PY
fi

sha256sum "$DIST/$NAME.tar.gz" "$DIST/$NAME.zip" > "$DIST/SHA256SUMS.txt"

echo "Created:"
echo "  $DIST/$NAME.tar.gz"
echo "  $DIST/$NAME.zip"
echo "  $DIST/SHA256SUMS.txt"

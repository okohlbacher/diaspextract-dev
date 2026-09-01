#!/bin/bash
# Deploy src/DIAPseudoSpectra.cpp to the cluster OpenMS tree, rebuild, record provenance.
# The ONLY sanctioned deploy path: kills the silent repo<->cluster drift the 2026-09-01 review flagged.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE=${1:-ibminode05}
SRC=src/DIAPseudoSpectra.cpp
SHA=$(shasum -a 256 "$SRC" | cut -d' ' -f1)
GITREV=$(git rev-parse --short HEAD)
git diff --quiet -- "$SRC" || GITREV="${GITREV}+dirty"
scp "$SRC" "$NODE":/scratch/kohlbach/OpenMS/src/topp/DIAPseudoSpectra.cpp
ssh "$NODE" "cd /scratch/kohlbach/OpenMS/build && make DIAPseudoSpectra -j32 > /scratch/kohlbach/build_sync.log 2>&1 && \
  printf 'src_sha256=%s\ngit=%s\nbuilt=%s\nbinary_sha256=%s\n' '$SHA' '$GITREV' \"\$(date -Is)\" \"\$(sha256sum bin/DIAPseudoSpectra | cut -d' ' -f1)\" \
  > bin/DIAPseudoSpectra.provenance && cat bin/DIAPseudoSpectra.provenance"

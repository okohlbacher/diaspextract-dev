# Evidence chain (archived 2026-09-01)

Every quantitative claim in docs/ was produced on ibminode05 from state that lived on purgeable
/scratch. This directory + the durable /ceph archive close that gap (project review 2026-09-01,
plan step 00).

## What is where

| evidence | location | notes |
|---|---|---|
| Analysis scripts, bench runners, result summaries (*.out), engine configs, cluster harness | `evidence/cluster-2026-09-01/` (95 files, byte-for-byte snapshot of /scratch/kohlbach/{prof,harness,bench} small files) | canonicalisation into bench// harness/ proper is a v0.2.0 task; this snapshot is the faithful record |
| Search outputs (results.sage.tsv, MSFragger tsv), run logs — all 89 run dirs | `/ceph/ibmi/abi/oliver/spextract-evidence/` (rsync, mzML/.d excluded) | ~17-20 GB; ARCHIVE_STATUS file marks completion |
| Raw diaPASEF .d (S23, S30, S33, S36) | `/ceph/ibmi/abi/data/2026_AGXT_PH1_liver_diaPASEF/raw_d/` | pre-existing durable archive |
| Raw S08 .d | same ceph dir | was MISSING on ceph (only a .d.txt stub); copied from /scratch 2026-09-01 |
| Extracted mzMLs (9 GB each) | NOT archived | regenerable bit-identically: raw .d + pinned source (SHA below) + logged flags -> identical mzML (determinism verified cross-node) |
| Input identities (FASTAs, engines, binary, source) | `evidence/SHA256SUMS-2026-09-01.txt` | |

## Provenance rule (from 2026-09-01 on)
Deploy to the cluster ONLY via `scripts/sync_cluster.sh`: it scps the source, rebuilds, and writes
`bin/DIAPseudoSpectra.provenance` (source sha256, git rev, binary sha256, timestamp) next to the
binary. Verified 2026-09-01: repo src == cluster src (859ea1e2...), i.e. all numbers through
d4686f0 are traceable. Benchmark runners should copy the provenance file into each run dir
(wired into the harness in plan step 03).

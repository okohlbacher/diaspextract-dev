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

## Post-review closure (adversarial review kimi + codex, 2026-09-01)

Both reviewers' verdict on the original step 00: git half solid, durable half unverified, several
load-bearing artifacts outside the rsync roots. Closed as follows:

**Additional archives (all on /ceph/ibmi/abi/oliver/spextract-evidence/):**
| item | why |
|---|---|
| `dt_s30/` incl. patched.mzML (5.5 GB), results.sage.tsv (the canonical 11,517), diatracer.{time,out} (the 7:47 runtime evidence) | diaTracer output is NOT regenerable by us; was outside every rsync root [kimi F1] |
| `dt_run/`, `tools/` (MSFragger-4.4.1.jar, diaTracer-2.2.1.jar, sage binary) | jars lived on ANOTHER project's purgeable scratch [kimi F4] |
| `mzml-diatracer-patched/` (all 6 samples, the exact patched search inputs) + `msfragger-on-diatracer/` (pepXML/pin behind the 13,014) | the 13,014 MSFragger evidence was outside all roots [codex #6]; patched variants are not derivable with certainty from the originals [codex #5] |
| `pop_s30.tsv` (1.5M-row linkage population cache) | top-level /scratch, outside all roots [codex #10] |
| `OPENMS-STATE.txt` (OpenMS 3.6.0-pre-exported-20260717 tarball — no git; EPD source sha; patch markers PRESENT) | the build environment was unpinned [codex #16, kimi F11] |
| FASTAs | inside the bench/ rsync (only *.mzML and *.d excluded); hashes in SHA256SUMS |

**Recovered into git:** `prof/msf_gate/score_msf_td.py` (the scorer behind every MSFragger number)
plus all prof subdirectory scripts (det4 oracles = the emission-falsification analysis, envq, det1,
dt_time) — the original `prof/*.py` glob missed subdirectories [kimi F2].

**Honest limits of the mzML-regenerability argument [codex Q2]:** it holds prospectively
(post-567168e determinism + committed source + recorded flags). It does NOT hold for: pre-567168e
runs (order-dependent wobble, e.g. the frozen 10,072); runs from uncommitted source (perf0723 arm B,
runtime iters 3/4, R1); and the historical q2k2/imw mzMLs whose producing binary predates the
provenance scheme (their TSVs and .out summaries ARE archived, which is what steps 01-02 need).
The one recorded md5 comparison (r1 vs imw005, r1_timing.out) shows a MISMATCH at equal spectrum
count — unexplained; plausibly the imw005 mzML predates the canonical-sort fix; R1 was reverted and
no decision rests on it, but the discrepancy is recorded rather than hidden [kimi F6].

**Known-unrecoverable references:** `sage_closed_s30.json` (cited by linkage-density-2026-07-24.md,
exists nowhere — the linkage acceptance sets can be re-derived only approximately from sage_closed.json);
the PXD027359 real-DDA matched files were never registered (ROADMAP already flags this) [codex #9-10].

**SENSITIVITY GATE for step 03 [codex #25]:** git history now contains PH1-patient-derived
acquisition identifiers (sample sheet names) and per-sample protein identifications (*.out files).
The repo is private. BEFORE any public exposure (v0.2.0, upstream PR, preprint), an explicit
publication-safety decision must be made: either consent covers these identifiers/IDs, or history is
rewritten. This is an owner decision, recorded here so it cannot be skipped.

**Provenance commitments:** deploys now refuse staged+unstaged dirt, lock, restore source on build
failure, and record OpenMS+EPD state (scripts/sync_cluster.sh v2); every deploy appends to
evidence/DEPLOY-LOG.md. Run-dir provenance propagation happens BEFORE step 02 (not step 03)
[kimi F10, codex #18] — no new extraction runs until the runner copies the provenance file.

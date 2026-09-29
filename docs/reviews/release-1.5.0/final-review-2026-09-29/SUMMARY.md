# 1.5.0 final review (2026-09-29): HEAD 109ae2e (release-1.5.0 = rc5 candidate + same-bin merge v2 + docs)

Reviewers: codex 0.155.1, kimi 2.0.2, vibe 2.25.5 (all one minor version behind; smoke-tested), plus an internal audit
workflow (3 dimensions x auditor + verifier: README vs code, CHANGELOG vs v1.4.1..HEAD, public-export scrub).

## Fixed in the follow-up commit
- `-gate:adaptive auto` below the threshold applied shrinkage/colocation/short-trace to EVERY precursor although docs,
  log and the design commit 433931e promise the plain gate (codex, audit x2). Now auto:off switches the three modes off;
  default output unchanged (auto is not the default).
- Scrub: `K562 250 ng 0.30` in the gate:auto_faint_fraction help (compiled string); `docs/reviews/...` in a toTof comment.
- dnoise: correctionRefusal accepted corr -> 0 (AccumulationTime -> inf): recoverPoint visits 1/corr + 3 candidates,
  unbounded; now 0.01 .. 1e6 (<= 10 s), unit check added.
- trace:im_slice_merge had no upper bound (llround overflow on absurd values; kimi): setMaxFloat_ 1.0.
- Docs: README 24 stamps (was "seventeen"), evidence formula, faint corr power, delta_im scope, logoverlap needs
  shrinkage off, colocation/short_traces/min_fragments rows; CHANGELOG: Sage-only entrapment, same-bin entrapment
  numbers (mean 1.21 -> 1.18, per run -0.34..+0.17), OpenMS #10291 "develop, not yet released", GATE_TARGETS is a file,
  stamps + [adaptive] line, tiling fix, logoverlap refusal, DET/OpenMS fix, "up to 10 s"; algorithm.svg updated;
  BASELINE.md dangling private refs; export_public_v3.sh gained a K562 scan.

## Declined, with reason
- Bin-0 guard escape (codex): tofOf returns 0 only off the calibrated axis (kimi), and "0 = OpenMS detector" is a
  design-wide convention of Trace::tof; documented at frag_bin.
- Ledger under-counts capacity after a merge shrink (codex): the ledger is size-based everywhere ("touched bytes"
  convention) and diagnostics-only (kimi); self-consistent.
- Literal byte identity with merges off (codex): the header gains spx:same_bin_merge; CHANGELOG now says "same semantic
  digest; the header gains the stamp".
- vibe reported no findings (low signal).

## Gate D on rc6 (binary 9a41f3dd, commit 109ae2e)
R1 8c1b047f, R2 e43672a0, R2b 9e2b075f (merge off with the gate modes): PASS; R2c 6498e613 (only the merge off = rc5
defaults): PASS; R3 new defaults 50b38ed9 (405,931 spectra, 24 stamps); R3a/b/c invariance: see the gate log.

# Adversarial review triage, 2026-09-03 (codex + kimi + vibe)

Prompt: `docs/reviews/release-2026-09-03/` (five questions: correctness, code-vs-doc consistency,
package completeness, internal commentary, test coverage). All three reviewers returned substantive
reviews (codex 145 lines, kimi 115, vibe 787) -- no SILENT reviewer, so the yield gate passed.

Both codex and kimi independently cleared the thing most likely to be wrong: **no data race in the
OpenMP window loop or the parallel MS1 pick.** Picker instances are `firstprivate`, per-window and
per-precursor output slots are disjoint, shared appends are guarded. That is two independent clears
on the code that was rewritten for parallelism, and it is the most valuable single result here.

## Fixed in this pass

| # | finding | reviewers | fix |
|---|---|---|---|
| 1 | MS1 traces were never filtered for non-finite coordinates, though fragment traces were. A NaN makes the sort comparator non-transitive (UB) and corrupts every later binary search. | codex, kimi | filter + log before the canonical sort |
| 2 | `FragGrid::off` CSR offsets were `uint32_t`; 8.5 M fragments x ~510 support points is within 2x of wrapping, and overflow silently corrupts every correlation. | codex, kimi | widened to `uint64_t` |
| 3 | Negative counts wrapped through `Size` (`min_fragments -1` -> ~1.8e19, nothing emitted) and negative tolerances gated everything out. Both failed as an empty but successful run. | codex, kimi | 17 `setMinInt_`/`setMinFloat_`/`setMaxFloat_` bounds; `0 = auto` preserved for both band counts |
| 4 | mzPeak: an unknown `frame_id` silently substituted the reference T1, so masses calibrated at the wrong temperature were stamped exact -- and the provenance record vouched for them. | codex | throws; also rejects non-positive input m/z instead of `llround(NaN)` |
| 5 | mzPeak: a short `get_spectra_batch` result was clamped with `min()`, leaving empty tail frames and a successful run. | codex | throws on any size mismatch |
| 6 | mzPeak: m/z and intensity arrays truncated to the shorter; a short IM array became "no IM". | codex | throws on mismatch |
| 7 | **Shipped defaults could not reproduce any published number**: every figure used `ms2_noise_threshold_int 10` and `ms2_split_valleys 7.0` on the command line while the registered defaults were 100 and 0. | codex, kimi | defaults moved to the benchmarked values; the "Current defaults" block in dataset D-BASELINE now lists all ten and says it was verified against the code |
| 8 | `SPEXTRACT_MZ_ESTIMATOR` set every reported precursor and fragment m/z from an undocumented env var, invisible in `--help`. | kimi | registered as `trace:mz_estimator` (apex/mean/median, default apex) with valid strings |
| 9 | `trace:split_valleys_fwhm` help claimed it overrides `ms1_split_valleys`; the code modifies `ms2_split` only. | codex | help corrected |
| 10 | `charge:ambiguity_margin` is unreachable in the default `count` scoring mode. | codex, kimi | help states the mode dependency |
| 11 | CHANGELOG advertised `SPEXTRACT_ISO_COLLAPSE` and the backfill env vars, which the ponytail pass had just removed. | codex, kimi | changelog rewritten to match the code, with Fixed/Removed sections |
| 12 | Doxygen header sent readers to `PLAN.md` / `REVIEW.md`, neither of which ships. | codex, kimi | points at `docs/dataset D-BASELINE.md` and `docs/reviews/` |
| 13 | `MzPeakStreamLoad.h` header said the exact calibration is enabled with `=1`; it is default-on and `=0` disables. | codex | comment corrected |
| 14 | `bands_for`, a per-window band heuristic, was defined, never called, and a comment said it was kept for reference. | codex | removed |
| 15 | `ponytail:` as a code tag has no meaning outside this project. | codex | reworded to `deliberate:` |
| 16 | README called both 15:21 and 12:49 "the current runtime", and its two determinism claims read as contradictory. | codex | runtime updated to 12:49/102 GB; the fixed-binary and cross-build claims separated explicitly |
| 17 | No test suite at all; verification was whole-file cluster runs only. | codex, kimi, vibe | `test/test_spextract.py`: six checks on a synthetic input -- isotope ownership, min_charge in both directions, two parameter-rejection checks, and 1-vs-4-thread byte identity |

## Rejected, with evidence

**"Precursors on a shared window boundary are emitted twice" (codex, HIGH).** Not a bug. Measured
on the dataset D output: all 23 adjacent isolation-window pairs overlap by exactly 1.000 Da, the standard
diaPASEF overlap. A precursor in an overlap band is genuinely isolated by both windows and yields two
independent measurements, so inclusive bounds on both edges are correct. The signature is visible and
benign: 27,440 of 927,813 spectra share an exact (m/z, RT, IM, charge) tuple, always with
multiplicity exactly 2, never 3. Recorded here so it is not re-flagged.

## Accepted, not yet fixed

These are real and are release work, not code defects:

- **Externally reproducible benchmark (codex BLOCKER).** The three files are patient-derived and
  cannot be published. A public PXD replication was already the open C10 item; v0.3.0 should ship
  with one public dataset reproduced end to end, or state plainly that the numbers are not
  independently checkable.
- **Build instructions and dependency identity (codex HIGH).** No OpenMS or mzPeak commit SHA,
  compiler version, or working standalone recipe. The README also implies a serial build works while
  the source calls OpenMP functions directly.
- **Resource requirements (codex HIGH).** 100-165 GB peak RSS is not stated anywhere a user would
  look, and the admission logic deliberately admits one oversized window.
- **Input/output contract (codex MEDIUM).** Required mzML content, per-peak mobility arrays,
  isolation-window offsets, the `spx_guessed` / `spx_n_isotopes` metadata and charge-0 behaviour are
  undocumented.
- **`consolidate` was falsified with a dead IM gate (kimi S2).** The code comment admits
  `getDriftTime()` returned -1 throughout, so the mobility gate never fired. That falsification is
  not evidence about the lever as designed and should be re-run or downgraded to "untested".
- **Full help-string compression (codex/kimi, question 4).** Only the three worst were done. The
  remaining `FALSIFIED` help texts still carry per-sample counts and dated arm narratives; the
  agreed target form is "Experimental; default off. Lost X, see docs/...". Source comments carrying
  route/arm chronology should move to `docs/experiments/` with stable experiment IDs.
- **Remaining test items.** Codex's window-partition, `aggregateFrames_` consumed-peak,
  band-equivalence and mzPeak contract tests need either a test-only compilation mode or fixture
  archives; the six shipped checks do not cover them.

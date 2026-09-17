# Review: 1.3.1 accepts a negative MzCalibration C2 (branch fix/c2-negative-1.3.1)

Commit under review: **2b9ade4c42** (`1.3.1: accept a negative MzCalibration C2 inside a checked domain`), base main
edf8ad8. Fix commit: the one that adds this directory. **It changes no file under `src/`**, so an arm built from 2b9ade4
has the same build inputs as one built from the fix commit (`scripts/sync_cluster.sh` INPUTS: only the two tests it
runs on the node, `test_dnoise_ms1.cpp` and `test_tdf_load.cpp`, are unchanged as well; the shipped
`tests/calibration_golden.json` is unchanged).

| reviewer | invocation | result |
|---|---|---|
| codex-cli 0.154.0 | `scripts/run_reviewer.sh codex` (`codex exec -s read-only -c model_reasoning_effort=high -o`), own worktree at 2b9ade4, left clean | rc 0, 269 s, 17.2 KB |
| kimi 0.42.0 | `scripts/run_reviewer.sh kimi` (`kimi -p --output-format text`), own worktree, left clean | rc 0, 1620 s, 14.1 KB |
| vibe 2.25.3 (mistral-medium-3.5) | `scripts/run_reviewer.sh vibe` (`vibe -p --output text --auto-approve --workdir`), own worktree, left clean | rc 0, 268 s, 19.8 KB |

All three ran (codex answered its smoke test at 03:03, before its announced 17:41 return). The brief (`brief.md`,
`scripts/build_brief.py`) is self-contained: the diff, the evidence (SDK generator output, margins, the 23 calibration
rows, the mutation matrix, ctest), the golden JSON summary, the SDK generator and the code around every caller, with
raw acquisition names reduced to run numbers. kimi 0.43.1 and vibe 2.25.4 were available and were not installed.

## Own lens (before the reviewers returned)

- **Root.** For C2 < 0 and C0 < t < C0 + b²/(4|C2|) both roots are positive, u± = (b ± √disc)/(2|C2|). The shipped
  `2(t − C0)/(b + √disc)` is u−, the rising-branch root (slope dt/du = √disc > 0), always ≤ b/(2|C2|); u+ lies at
  m ≈ 1.5e12 on PXD029836. Continuous through C2 = 0; −0.0 takes the zero path. All three reviewers derive the same.
- **Domain check.** t_zero, t_half = C0 + 3b²/(16|C2|), u_half = b/(4|C2|) are right; the corner (largest TOF, largest
  C1 factor, `fabs(dC1)`) is right; `frameFactor`'s `(dC1·ΔT)/1e6` is bounded by `cf_hi`'s `|dC1|·1000/1e6` in floating
  point. `proof/fuzz.cpp`: 200,000 random rows (87,022 accepted) × 64 samples each over TOF ≤ 1e8, m/z ≤ 1e5,
  |ΔT| ≤ 1000 K, with random C4: **0 violations** of disc ≥ b²/4 or slope ≥ b/2, round trip ≤ 2.3e-11 relative.
  Largest accepted |C2|: 0.0595301 (1418's constants), 0.0945 (dataset D's 0.125 ns timebase) (`proof/edges.out`).
- **Bit identity for C2 ≥ 0.** Only comments change in `tofToMz`/`mzToTof`/`frameFactor`; the timebase check moved
  ahead of the C2 check (same refusals for C2 ≥ 0); `frameReason` returns at `!(C2 < 0)`; the two constants equal the
  literals they replace; no data member is added. Holds by construction; the digest gate has not run.
- **Golden independence.** The committed 210 cases equal `pxd029836_golden.json` in the evidence directory, which equals
  the JSON the SDK script printed; every `mz` there is `tims_index_to_mz` output. The first 60 cases are unchanged.
- **Every caller of the inverse** (`mzToTof` is non-monotonic past m_vertex = b²/(4C2²) − C4, at least ~4e5 for any
  accepted row with a real C4, 1.49e12 on PXD029836): the store's quanta (≤ 42,950), `acq_hi` (≤ 1e5),
  `mzOf(last) + 1e-5` (last < n_bins ≤ 1e8, so on the rising branch), apex m/z of real peaks, and dnoise's loader m/z
  (always the rising-branch image) stay below it. Only an absurd `trace:mass_error_ppm` can push `best`'s window past it.
- **CHANGELOG.** "since 2026-09-01" was the date of the C2 ≤ 0 refusal; the "flips the root branch" reason dates from
  2026-09-05 (76cb1e3). "5e-8 bins" was measured as 3e-8.

## Findings and dispositions

| # | who | sev | finding | verdict | disposition |
|---|---|---|---|---|---|
| 1 | codex, kimi, vibe | MEDIUM (process) | CHANGELOG says "the four pins reproduce" before any digest gate ran | CONFIRMED | **OPEN, blocks a tag**: the gate slice (`gate_D_131.sh`: e43672a0/8c1b047f; `gate_T_131.sh`: 3aafd0b5/bff54a1f) must pass before v1.3.1 is tagged; the sentence stays because the release text requires it, and must change if a pin differs |
| 2 | codex (MEDIUM), kimi (MEDIUM), vibe (HIGH, "no real-world risk") | MEDIUM, theoretical | The OpenMS loader patch has no per-frame T1 check. With `-dnoise:ms1 false` a `.d` run whose tool reader refused a frame falls back to the openms detector, and the loader converts the frame at its recorded T1 (kimi: dC1 999 ppm/K, T1 = T1_ref − 2000 K gives m/z ×3, finite) | CONFIRMED by reading `diaspextract.cpp:3230-3245, 3975-3985` and the patch. The same conversion happens for every zero/positive-C2 file at such a T1 (no C2 ≥ 0 frame check ever existed); no real frame is outside ±1000 K (spreads ≤ 0.034 K) | **OPEN, user decision.** Not fixed here: it needs either a regenerated loader patch plus a re-patched cluster OpenMS tree, or a tool-side refusal instead of the fallback in `diaspextract.cpp`, which only the node's e2e suite can test. CHANGELOG now states the gap explicitly |
| 3 | codex (MEDIUM), kimi (LOW), vibe (LOW) | LOW, theoretical | The 1e8 TOF bound is enforced only on `DigitizerNumSamples`; the loader converts raw blob indices, mzPeak reconstructs a TOF, and neither checks it | CONFIRMED. The forward root is always the rising-branch root or NaN, never a finite wrong mass. On all four PXD029836 vectors the discriminant at index 2³² − 1 at the ±1000 K corner is still ≥ 0.336 b² (`proof/edges.out`), so no stored index can reach NaN there; a near-edge row gives NaN past ~1.33e8 (MS1: run refused by `requireFiniteMs1Mz`; mzPeak: throws; MS2 integer path: `bad_mz`) | OPEN (optional defence in depth); CHANGELOG no longer says "everything the tool can ask" |
| 4 | codex | LOW, theoretical | Finite rows at floating-point extremes pass the check but give disc < 0 (C0 = 2^72 rounding; timebase 1e308 with C2 −1e-310) | CONFIRMED (`proof/edges.out`): both convert to NaN, not to a wrong mass | OPEN (hardening) |
| 5 | codex, kimi (pre-existing) | LOW, pre-existing | Only NaN is screened: ±inf in C0, delay, C4, T1_ref is accepted for any C2 sign (C4 = −inf → m/z +inf; own: C2 = +inf with C4 < 0 → every peak at m/z −C4) | CONFIRMED by reading; not introduced here | OPEN (hardening: `std::isfinite` screen, byte-identical for every real file) |
| 6 | codex | LOW, pre-existing | A frame whose C1 factor is exactly 0 gives b = inf, and with C4 < 0 every peak becomes m/z −C4 (PXD1418 row, C4 −500, T1 = T1_ref + 50000 → 500) | CONFIRMED (`proof/edges.out`): identical with C2 > 0; the tool's reader refuses it for C2 < 0 only | OPEN (hardening: refuse a non-finite or non-positive frame factor on every path) |
| 7 | codex | LOW, theoretical | `mzToTof` past the vertex: descending-branch masses map to real TOFs (m/z 144 and 3,952,144 on one synthetic row); `inverse_convert` casts ~7.5e9 to uint32 at m/z 1e12; `best` with `trace:mass_error_ppm` 1e16 gets TOF 0 | CONFIRMED as behaviour; no tool path feeds such masses (own lens); `inverse_convert` has no caller | OPEN (optional: saturate `tofOf` past the vertex for C2 < 0) |
| 8 | codex | LOW, pre-existing | `mzToTof` clamps m + C4 < 0 to 0 | CONFIRMED; no negative-C2 file with C4 ≠ 0 is known | OPEN |
| 9 | codex | LOW | `test_calibration_cpp.cpp:220`: `std::fmax` drops a NaN operand, so a NaN inverse above m/z 1e5 would not fail the domain sweep | CONFIRMED: a header mutation returning NaN for m/z > 1e5 passes the old test (`proof/test_guards.out`) | **FIXED**: each point must be within 1e-6 bins; the mutation now fails |
| 10 | kimi | LOW | The temperature ablation is only checked globally; run 1347's is 0.078 ppm, below the 0.1 floor, so a regenerated JSON with no T1 spread on the new files would pass | CONFIRMED: a flat-T1 1408 passes both old tests | **FIXED**: per-file floor 0.05 ppm in both tests (smallest real 0.074, run 1408); the flat file now fails both |
| 11 | codex, kimi | LOW | The golden JSON has no `C4`; the C++ scanner never reads one | CONFIRMED (Python reads `C4`) | **FIXED**: the C++ test refuses a golden file carrying a `C4` key until its scanner reads it; mutation fails as intended |
| 12 | codex | LOW | `test_calibration.py` puts "taking the other root" in the 38-80 ppm class | CONFIRMED: the other root lands near m/z 1e12 | **FIXED** (docstring) |
| 13 | codex, own | LOW | CHANGELOG: "57 times theirs" holds for run 1418 only (49-102 over the four vectors); "1e-6 inside" is relative; "5e-8 bins" was 3e-8; "since 2026-09-01" dates the C2 ≤ 0 refusal, not the stated reason; "beyond the peak" is ambiguous; the mzPeak path refuses rather than falls back | CONFIRMED | **FIXED** in CHANGELOG |
| 14 | codex, kimi | LOW | `src/TdfMzCalibration.h` comments overstate: "everything the tool can ask of the model" (29-31), "NaN, which the tool drops and counts (bad_mz)" (35-37; an MS1 NaN refuses the run), `DigitizerNumSamples` as an enforced bound (63-65), line 24's −11..−40 ppm sign; `TdfLoad.h:57` prints "[2, 1e8]" instead of the constant | CONFIRMED | OPEN: comments only, deferred to the next `src/` change so the gate slice's build inputs stay those of 2b9ade4 |
| 15 | codex, kimi | LOW (deploy) | A new tool with an old libOpenMS keeps the old refusal (fail-safe); the positive-C2 digest gates cannot see it | CONFIRMED | OPEN for the deploy slice: the new provenance's `libopenms_sha256` must differ from 1.3.0's, and one PXD029836 file must load through the rc arm (the planned `dwv_pxd029836` rerun does) |
| 16 | kimi | LOW | The SDK generator pins the tdf sha256 of 1418/1420/1422 only; 1431/1408/1347 have a 16-hex prefix in `sdk_golden.out` | CONFIRMED | OPEN (evidence outside the repo) |
| 17 | vibe | LOW | No vendor case combines C4 ≠ 0 with C2 < 0 | CONFIRMED; no such file is known | OPEN (optional, would need a synthetic tdf through the SDK) |
| 18 | vibe | LOW | "6.4e9" and "16,000×" should be 6.6e9 and 19,000× | REFUTED: 6.4e9 is run 1431 at the ±1000 K corner (6.47e9 = 16,270 × N), which is what the text describes | none |
| 19 | vibe | — | "every accepted file has its half-slope TOF near 5.7e9" | REFUTED: the check guarantees only 1e8 (the edge row halves exactly there); 5.7e9 is PXD029836's | none |
| 20 | vibe | — | "an old libOpenMS refuses only with `-dnoise:ms1 false`" | REFUTED: the loader converts every peak in every mode, so an old libOpenMS refuses in every mode | none (see 15) |
| 21 | vibe | LOW | `%.6g` in refusal messages | cosmetic | none |

Answers with no finding (all three): the root choice, the domain algebra and corner, the bit-identity argument for
C2 ≥ 0 (no layout or aggregate change, C++20, constants equal), the independence of the vendor cases, no other code path
that assumes C2 ≥ 0, `tdf_table_modeltype1` provenance unchanged.

## Proof around the review

- `proof/test_guards.out`: old tests (2b9ade4) vs new, on the unchanged golden file, a file with a `C4` key, a file with
  no T1 spread on run 1408, and a header mutation returning NaN from `mzToTof` above m/z 1e5. Old: all pass. New: the
  golden file passes; the three defects fail (C++); Python fails the flat file and reads the `C4` key.
- Local ctest after the fix: 3/3 on AppleClang 21 and on GCC 16 (`-Wall -Wextra`, 0 warnings);
  `python3 tests/test_calibration.py` OK (270 cases, per-file temperature 0.074-0.669 ppm);
  `scripts/check_option_tokens.py` OK.
- `proof/fuzz.cpp` / `proof/edges.cpp` (compiled against the header at 2b9ade4): the domain fuzz, the per-vector edges,
  the codex witnesses (items 4 and 6) and the uint32 margin (item 3).

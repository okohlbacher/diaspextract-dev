SpeXtractor 2.0 is the renamed tool, three weeks of measured work on speed, memory and charge assignment, and the first release with a like-for-like comparison against the reference implementation on public data.

## Why 2.0

Three things break compatibility with 1.x, and each is deliberate:

- **The executable is `spextractor`.** The old name was taken. Every script that called `spextract` has to change, and ini files written by 1.x carry the old section name and must be regenerated (`-write_ini`); the GitHub URLs redirect.
- **A third OpenMS patch is mandatory.** `MassTrace` in OpenMS declares copy operations that suppress its moves, so every `std::move` of a trace deep-copied its points. The patch adds the moves, and a `static_assert` stops the build without it. `scripts/apply_openms_patches.sh` applies all three.
- **Output is not digest-comparable with 1.x.** An MS1 arena-compaction defect that overwrote ~1% of precursor profiles is fixed, the `C4` calibration term of 2019-firmware timsTOF Pro files is modelled, and an isolation m/z acquired in two ion-mobility slices is now two windows. All three change spectra.

## Where it stands

On a 2-hour public diaPASEF acquisition (PXD047793, run 009), both tools on the same node at 100 threads:

| | reference implementation | DIAspeXtractor 2.0.0 | ratio |
|---|---|---|---|
| wall | 20:57 (mean of 2) | **12:42** | **0.61×** |
| peak RSS | 341 GB (mean of 2) | **188 GB** | **0.55×** |
| Sage peptides, per-charge 1% FDR | 21,743 | **27,831** | **1.28** |
| MSFragger peptides, per-charge 1% FDR | 28,294 | 28,181 | **1.00** (0.996) |

Run 001 gives 1.25 / 0.98. Whole-run entrapment FDR on the 2-hour files is at the nominal 1% (0.93–1.03% pooled, 0.98–0.99% per charge; a 30-minute in-house file reads 1.33%). That 30-minute gradient runs in 3:17 at 58 GB. The wall figure is one run against the reference's two-run mean. Before this cycle the same 2-hour file ran 1.46× *slower* than the reference.

## Singly charged precursors are emitted, with a mobility veto

`charge:min_charge` defaults to 1 again. On 2-hour tryptic acquisitions the z=1 hypotheses are 14–20% of Sage peptides and most of the MSFragger deficit, and they are physically singly charged: their ion mobility sits +0.29 Vs/cm² above the 2+ trend line, exactly where the reference implementation's own 1+ identifications sit. Charge halving is real too (11–26% of z=1 calls, depending on the file, are a 2+ envelope whose M+1 was missing), and TIMS resolves it: the 2+ and 3+ mobility lines are fitted per run and a z=1 on the 2+ line is re-called, one on the 3+ line dropped (`charge:im_charge_veto`).

**Read this before you search.** Under a pooled 1% cut the z=1 stratum carries ~3% entrapment FDR on the 2-hour files (~9% on a 30-minute one) while the whole-run figure reads about 1%; a per-charge FDR walk puts it at 0.9% and keeps the gain. Control FDR per charge downstream, and report it by charge. `-charge:min_charge 2 -charge:im_charge_veto false` restores the 1.x charge policy.

## Speed and memory

- The scoring stage of a large isolation window was silently single-threaded — libgomp runs a `taskloop` inline once its task count exceeds 64× the thread count. A fixed worker pool fixes it; two windows that decided a 2-hour run went from 418 s and 581 s to the 12–28 s of their neighbours.
- Precursor inference is parallel and exact (ordered speculation): 23× on the greedy claim loop, byte-identical output.
- Two hot loops compute their index instead of binary-searching it; MS1 band distribution and seed preparation are parallel; the trace record is 48 bytes, was 72.
- `perf:malloc_trim` (on) returns the allocator's retained pages at the phase boundaries; the memory pass it completes measured −30% peak memory for +8.5% wall on a 2-hour file. Off is one flag when time is the constraint.
- `perf:ms1_trace_bands` 12 → 48: MS1 tracing 2× faster once its distribution stopped being serial.

## Also

- `-threads` defaults to every core; the output format follows the `-out` extension (`.mzpeak` by default in a build with mzPeak, `-out_type` forces it; write `.mzML` for a search) — both since v1.1.0. OpenMP is required.
- Runs end to end on the public HeLa benchmark (PXD017703): three loader defects the in-house cohort never exposed are fixed.
- Thirteen end-to-end checks; the suite now runs the shipped detector rather than the fallback.
- The tool reports its own version (`--help`, the ini `version` parameter, the mzML software entry used to carry the OpenMS version).

## Unchanged limits

DIAspeXtractor cannot be built against a released OpenMS package; the commit is pinned in `patches/openms.lock` and `.github/workflows/build.yml` is the reference recipe. It needs a large machine: ~57 GB on a 30-minute acquisition, ~170–190 GB on a 2-hour one. The in-house benchmark cohort is patient-derived and cannot be published; the public-data numbers above are reproducible from the PXD accessions.

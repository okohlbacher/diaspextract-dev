## 1. Is the integer detector defensible as the default?

No. The stated adoption rule was bent—and the claimed default was not actually implemented.

The most immediate defect is factual: commit `e3c6eb4` says “Make `trace:detector=integer` the default,” but HEAD still registers `"openms"` and describes it as the default at [DIAPseudoSpectra.cpp:1485](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1485). Consequently, `integer_detector` becomes true only when the user explicitly requests it at [DIAPseudoSpectra.cpp:3115](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3115). The README and CHANGELOG claims are false; the CHANGELOG even contradicts itself, saying both “defaults to integer” and “experimental, default openms” at [CHANGELOG.md:27](/Users/kohlbach/Claude/speXtractor/CHANGELOG.md:27) and [CHANGELOG.md:61](/Users/kohlbach/Claude/speXtractor/CHANGELOG.md:61).

Even if that coding error were fixed, the evidence does not satisfy the stated rule:

- dataset D has both engines and entrapment (`4bd81c2`), and `bbb2121` establishes that the span build produces the same dataset D spectrum-list digest as the pre-span build.
- dataset A (`4a22ad7`) has only Sage, memory and runtime, predates `3a1d91e`, and has not been rerun after the span change. MSFragger and entrapment are explicitly still missing in [FAILURE-ANALYSIS.md:117](/Users/kohlbach/Claude/speXtractor/docs/reviews/integer-tracing-2026-09-03/FAILURE-ANALYSIS.md:117).
- Therefore: both-engine/entrapment evidence exists on one file; second-file evidence exists for only Sage and memory on the old representation. The full rule was not met.

The honest evidence statement is:

> On dataset D, the integer detector reduces wall time 6:54→6:21 (8.0%), peak RSS 150→86 GB (42.7%), and window-loop CPU 19,440→14,249 CPU-s (26.7%). Sage decreases 1.3%, MSFragger increases 2.1%, and entrapment shows no detectable worsening. On pre-span dataset A, Sage increases 0.3%, RSS falls 39%, and wall time is effectively unchanged. Generalization across engines and files remains unverified.

“Agree to about 1%” is misleading because it describes the net count, not membership. The sets intersect at 11,494 peptides: OpenMS-only is 1,148/12,642 = 9.1%, integer-only is 981/12,475 = 7.9%, and the symmetric difference is 2,129/13,623 = **15.6% of the union**. That is substantial deterministic churn.

Likewise, entrapment is not demonstrated to be “lower”: 1.27% versus 1.38% is a −0.11 percentage-point point estimate with heavily overlapping confidence intervals. The defensible conclusion is “no evidence of worsening.”

The fallback in `e3c6eb4` is insufficient for a default. The warning and `spx:detector` metadata at [DIAPseudoSpectra.cpp:3130](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3130) and [DIAPseudoSpectra.cpp:3862](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3862) are useful, but the same nominal default command can select different algorithms depending on input container and sidecars. That mode should be called `auto`, not `integer`; alternatively keep `openms` as the default and require an explicit request for integer.

Worse, having a calibration is not sufficient. Unknown frame IDs become zero at [DIAPseudoSpectra.cpp:637](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:637), while `factor(0)` silently returns a reference factor at [DIAPseudoSpectra.cpp:542](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:542). An mzML plus sidecar can therefore avoid the fallback warning yet use reference-temperature calibration for frames whose native IDs cannot be mapped. That must fail closed before integer can be considered a safe default.

## 2. What is unverified or overstated?

### Actually verified by runs

- The scoring-array change in `1a7158e` was measured at 7:17 and produced the same **Sage peptide set**, replicated three times. That is what [dataset D-BASELINE.md:764](/Users/kohlbach/Claude/speXtractor/docs/dataset D-BASELINE.md:764) and [CHANGELOG.md:49](/Users/kohlbach/Claude/speXtractor/CHANGELOG.md:49) support. They do **not** document a spectrum digest comparison. Calling it “digest-identical” overstates the record.
- The span representation from `3a1d91e`, after the child-bin bug was fixed in `6ea4e3f`, has a reported dataset D spectrum-list digest match for both detectors in `bbb2121`, [TRACE-STRUCT-REDESIGN.md:230](/Users/kohlbach/Claude/speXtractor/docs/TRACE-STRUCT-REDESIGN.md:230). This is the strongest identity evidence from today.
- That is a semantic `<spectrumList>` digest, not byte identity of the complete mzML: the project’s digest deliberately excludes parameters, timestamps, and the trailing byte-offset index, as explained at [README.md:83](/Users/kohlbach/Claude/speXtractor/README.md:83).
- dataset D integer search results and entrapment were measured in `4bd81c2`; pre-span dataset A Sage/RSS/runtime were measured in `4a22ad7`.

### Asserted or incompletely verified

- `7d6e56f`—dropping `frame_of`, dropping `member`, and exact-reserving seeds—is explicitly “output-neutral by construction; digest-gated,” but no completed digest run exists. It is committed, not verified.
- The global RT-axis conversion in `0e518a4` was argued arithmetic-equivalent. I found no isolated before/after spectrum digest in the supplied record. Later successful runs exercise it, but they do not isolate its effect.
- The flight-time-axis work in `436f3c6` is not representation-only. Picked m/z is first quantized at [DIAPseudoSpectra.cpp:669](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:669), then inverted and rounded to a TOF bin at [DIAPseudoSpectra.cpp:780](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:780). For centroided peaks, that bin is reconstructed, not necessarily the original raw measurement. Calling the path “lossless” is overstated.
- The claim that the remaining detector difference is “scheduling-order sensitivity” is unsupported and likely wrong. Each band has a private visited bitset at [DIAPseudoSpectra.cpp:898](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:898), writes a disjoint result, and is merged in band order at [DIAPseudoSpectra.cpp:3301](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3301). Scheduling order should not alter that output. The remaining churn is an algorithm/banding/rebinning difference until demonstrated otherwise.

### The corrected ledger is still not correct

The add-without-subtract error was partly fixed in `6ea4e3f`, but the advertised 27.9 GB simultaneous peak is not trustworthy:

- `g_tr` is created only **after** detection and valley splitting at [DIAPseudoSpectra.cpp:3337](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3337). It therefore misses the parent intensity and bin arenas, band-private stores, input trace records, child arenas, and parent/child coexistence during splitting. The reported 6.9 GB “traces peak” is actually a post-split resident measurement.
- The EPD input guard is installed only after all input `MassTrace`s have been allocated, and the output guard only after `splitValleys()` has returned, at [DIAPseudoSpectra.cpp:1073](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1073) and [DIAPseudoSpectra.cpp:1095](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1095). Concurrent overlaps during construction are invisible.
- `g_wmap` remains charged to the end of the window task even though `detectTraces_` clears the map at [DIAPseudoSpectra.cpp:1700](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1700) or [DIAPseudoSpectra.cpp:1725](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1725). Thus the OpenMS total is overcharged in one category while large OpenMS internals remain untracked.
- MS1 compaction subtracts `old_capacity - keep.size()` rather than `old_capacity - keep.capacity()` at [DIAPseudoSpectra.cpp:3000](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3000). It underbooks any retained spare capacity.
- Emitted spectra are added only in the share-all branch at [DIAPseudoSpectra.cpp:3473](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3473); apportionment and `rp_max` are unaccounted.
- `memTotalPeak` sums independently changing atomics without a coherent snapshot at [DIAPseudoSpectra.cpp:729](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:729). It can combine category values that never coexisted or miss a real overlap.
- The ledger still calls the replacement structure `FragGrid` at [DIAPseudoSpectra.cpp:718](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:718).

The RSS reduction to 86–88 GB is real process evidence. The 27.9 GB attribution is not.

## 3. Correctness of the span implementation

The main dataset D path appears semantically sound, and `bbb2121` provides real evidence for that. I did not find the suspected dangling-store-pointer bug in the exercised paths:

- Band stores are absorbed before `st` is assigned at [DIAPseudoSpectra.cpp:3303](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3303).
- Chunk stores are absorbed and offsets rebased at [DIAPseudoSpectra.cpp:1122](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1122), after which the caller resets every `st` to the stable window store at [DIAPseudoSpectra.cpp:3325](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3325).
- MS1 compaction moves arena contents but not the `TraceStore` object, so existing `st == &ms1_store` pointers remain valid.
- Arena reallocations do not invalidate offsets because traces store indices, not element pointers.

There are nevertheless real defects and missing guards:

- **`off` can silently wrap.** `makeSpan()` casts `store.inten.size()` to `uint32_t` before checking the resulting arena size at [DIAPseudoSpectra.cpp:327](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:327). `TraceStore::absorb()` checks merged stores, but cannot repair a band-local offset that already wrapped. MS1 compaction repeats the unchecked cast at [DIAPseudoSpectra.cpp:3005](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3005). The design required a pre-write `<2^32` assertion; it was not implemented.
- **The zero sentinel is conditionally valid, not intrinsically valid.** Current option bounds require nonnegative thresholds at [DIAPseudoSpectra.cpp:1583](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1583), and the integer detector admits points only with intensity `> noise` at [DIAPseudoSpectra.cpp:896](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:896). That supports the invariant. But `makeSpan()` accepts arbitrary zero/negative values, interprets repeated zero slots as absent, and has no assertion at [DIAPseudoSpectra.cpp:333](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:333). Harden it with `q.second > 0` and frame-range assertions.
- **`uint16_t len/npts/apex` are safe under the current construction.** `L < 65,536` is checked, `npts` cannot exceed the unique occupied slots in `len`, and `apex < len`. This part is defensible. The missing protection is the arena offset, not the per-trace length.
- **OpenMS’s empty `store.b` is handled correctly in the current consumers.** OpenMS traces retain `tof=0`, and `exportMz_()` falls back to cached m/z at [DIAPseudoSpectra.cpp:2378](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2378). `buildFragStats`, `scoreCandidates_`, `xicCorr`, `packReal`, and the FWHM paths require only the frame table and intensity arena.
- **`packReal`, `xicCorr`, `buildFragStats`, and the default scoring loop honor presence correctly.** They skip zero slots at [DIAPseudoSpectra.cpp:313](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:313), [DIAPseudoSpectra.cpp:1816](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1816), [DIAPseudoSpectra.cpp:1399](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1399), and [DIAPseudoSpectra.cpp:2232](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2232).
- **One FWHM routine contradicts its contract.** The main median-FWHM calculation initializes crossings to `-1` and excludes truncated peaks correctly. The diagnostic `fwhm_of`, however, initializes `lo` and `hi` to the trace endpoints and always returns `hi-lo`, even if one or both half-height crossings were never found at [DIAPseudoSpectra.cpp:2924](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2924) and [DIAPseudoSpectra.cpp:2935](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2935). Its comment promises `-1`. This bug predates the span representation but survives it.
- **The MS1 arena compaction is logically correct but accounting-incorrect and overflow-unsafe**, as described above.
- **Integer calibration provenance remains unsafe.** The comment says frame ID zero “must” be treated as unknown, but the caller does not do so; it silently uses a reference factor. That is a correctness blocker independent of the span.

The existing synthetic suite explicitly exercises only the OpenMS detector at [test_spextractor.py:19](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:19). Thus dataset D digest equality is the only meaningful coverage of the integer span/split path.

## 4. Occupancy

The figures are broadly consistent; they do not establish a scheduling defect.

Using whole-run wall time:

- CPU ratio: `14,249 / 19,440 = 0.7330` → 26.7% less work.
- Wall ratio: `381 / 414 = 0.9203` → 8.0% less wall time.
- Expected occupancy ratio: `0.7330 / 0.9203 = 0.7965`.
- Expected integer occupancy: `81.0 × 0.7965 = 64.5x`.
- Observed: `68.5x`, which is 4.0 cores or **6.2% above**, not below, that whole-run expectation.

More importantly, occupancy is scoped to the window loop rather than the whole run. Its implied window-loop walls are:

- Integer: `14,249 / 68.5 = 208.0 s`.
- OpenMS: `19,440 / 81.0 = 240.0 s`.

Thus the window loop itself is 13.3% faster, and:

`(14,249 / 19,440) / (208 / 240) = 0.8457 = 68.5 / 81.0`

The arithmetic closes exactly when like scopes are compared. Lower occupancy is principally the consequence of finishing less CPU work, not proof that workers are unnecessarily idle.

Still worth measuring once:

- A 1 Hz R/S/D thread-state trace.
- Ready-task count or time with no runnable task.
- Admission-wait time at [DIAPseudoSpectra.cpp:3187](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3187).
- Per-stage scoped wall/CPU rather than mixing whole-run wall with window-loop CPU.

Do not redesign the scheduler based on the raw 68.5x versus 81.0x comparison.

## 5. What next, and what should stop?

Ranked by value:

1. **Correct the false default claim immediately.** Either leave OpenMS as the documented default or actually switch only after validation. Rename fallback behavior to explicit `auto`. Reject missing/unknown frame IDs instead of applying the reference factor. Fix README/CHANGELOG contradictions introduced by `e3c6eb4`.

2. **Complete the validation matrix before any default change.** First digest-gate `7d6e56f` against `bbb2121`. Then rerun post-span dataset A with Sage, MSFragger and entrapment. Given 15.6% union churn, also report set differences—not just net counts.

3. **Repair the ledger before quoting another component-level GB saving.** Track arenas while they are allocated, include `bins` and child stores, release `g_wmap` when the map is cleared, use capacities consistently, cover every assembly branch, and obtain a coherent peak snapshot. Until then, use 86 GB RSS as truth and treat 27.9 GB as an incomplete lower-dimensional accounting result.

4. **Finish release reproducibility before further optimization.** The earlier review’s blockers remain: no public dataset, no dependency SHAs/compiler identity, no end-to-end worked example, an incomplete input/output contract, and no prominent resource requirements. These are recorded at [TRIAGE.md:43](/Users/kohlbach/Claude/speXtractor/docs/reviews/release-2026-09-03/TRIAGE.md:43). A tool needing 86–150 GB but not saying so is not release-ready.

5. **Add integer-path tests.** Provide a tiny injectable calibration fixture and test span holes, split-child apex bins, unknown frame IDs, band equivalence, zero rejection, offset limits, and OpenMS/integer mode selection. The current suite silently falling back to OpenMS would not test the proposed default.

6. **Measure occupancy once, cheaply.** Attach the thread-state/admission sampler to the required dataset A reruns. Do not spend a separate benchmark campaign on it.

7. **Only then try per-trace valley splitting.** It may remove the 7.6+1.0 GB MassTrace coexistence, but “8–11 GB” is presently derived from an incomplete ledger. Isolate it, add a split-stage timer, and require an dataset D spectrum-list digest match.

Lower value:

- **Trace scalar removal:** deriving `intensity` can save 8 B/trace; deriving `b` complicates the OpenMS empty-store fallback. Do this only after a corrected ledger gives an actual concurrent trace count.
- **Further prep/slab work:** validate `7d6e56f` first. Do not stack more compaction on an unverified commit.

Stop:

- **Stop calling integer the default or saying the detectors “agree to 1%.”**
- **Stop treating the 27.9 GB ledger total as correct.**
- **Stop pursuing “slab lifetime” as an open item:** slab and prep are already physically released before splitting at [DIAPseudoSpectra.cpp:3313](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3313). Remove the stale plan item.
- **Stop allocator experiments** unless concurrency is fixed and the experiment measures process RSS under the same admission schedule. The existing plan already records glibc/tcmalloc evidence and the admission-gate confound.
- **Stop performance-first work until the public replication and packaging recipe exist.** Another 5–10 GB or 20 seconds has less project value than making one published number independently reproducible.
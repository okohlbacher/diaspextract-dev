I would hold the tag for the **bin-0 guard escape** and **`adaptive auto` behavior** below. The held-memory ledger invariant and literal file-byte compatibility also need resolution.

Reviewed `109ae2e` against `v1.4.1`. No files modified, builds run, or commits made. This was source review with arithmetic checks, not an end-to-end reproduction.

1. **`toTof()` regrouping: no corruption or thread/tile ordering defect found.**

   At [src/diaspextract.cpp:982](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:982>), each original frame range is read before its offset is rewritten. The write cursor never overtakes unread peaks, and all members of a same-bin run are read before its groups are written. Other frames and bins are preserved.

   `(imq, idx)` gives deterministic grouping and summation order. Arbitrarily permuting input peaks can affect ties, but the loader preserves within-frame order across thread counts and tile groupings. No invariant-1 violation found here.

   The span boundary is **inclusive**: both comparisons use `<=`. This is in quantized units: default `0.015` becomes 702 quanta, with a 1404-quanta span cap, approximately `0.0299931` 1/K0.

2. **Assembly ties, overlap, cap key, and unchanged unique-bin spectra: fine.**

   At [src/diaspextract.cpp:3395](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:3395>), equal emitted intensities retain the lowest canonical fragment index. Summation follows that canonical order. Touching RT spans count as overlapping; every member is compared directly with the strongest member.

   The cap key is the **maximum existing key among summed members**, so merging does not inflate it. With no duplicate group, `nm == 0` and neither fragments nor scores are rewritten. Disabling the guard bypasses its mutations.

   Assembly deliberately applies the RT-overlap rule without reapplying the tracing IM link/span limits. That matches the option’s documented purpose of catching slices beyond the tracing span.

3. **Merge coverage: one concrete escape.**

   **Fix-before-tag — [src/diaspextract.cpp:3384](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:3384>) and `:3386`: legitimate integer TOF bin 0 is mistaken for “OpenMS/no bin.”**

   Concrete case: two bin-0 mobility slices at `0.991` and `1.009`, around precursor IM `1.0`. Their separation exceeds the default merge link, but both pass the precursor IM gate. Give them overlapping three-frame profiles `[100,300,200]` and `[200,300,100]`, with `-trace:ms2_split_valleys 0`, plus another accepted fragment.

   The repository’s real calibration fixture maps bin 0 to approximately m/z `99.990048`. Tiny frame-temperature differences yield distinct cached centroids—approximately `99.990047842` and `99.990048286`—while both still invert to bin 0. The guard compares their exact m/z values instead of their bin and retains both.

   **Real or theoretical?** Valid acquisition-edge input; corpus incidence is unmeasured. This violates the stated TOF-bin invariant.

   Other coverage looks sound: band/valley children and boundary carries reach assembly, and carries enter before canonical sorting. OpenMS exact-m/z grouping matches its documentation; MS1 traces supply precursors rather than emitted fragments. The later twin fold uses ppm fusion without bin provenance, so it cannot establish an unconditional bin guarantee, but I found no additional demonstrated release defect there.

4. **Ledger: signed arithmetic and concurrency are correct; held-memory accounting is not.**

   **Fix-before-tag under invariant 4 — [src/diaspextract.cpp:1028](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:1028>): shrinking vector sizes does not release their capacity.**

   Example: merging 1,000 peaks down to 500 subtracts 5,000 bytes because `PeakSlab::bytes()` counts sizes. The three vectors still hold their original allocations, including the previously touched discarded tail, until their later release.

   **Real or theoretical?** Happens whenever merging removes peaks while the ledger is enabled. It understates held slab memory; it does not corrupt spectra.

   Both operands are converted to signed `long long` before subtraction, and `ledAdd_` uses atomic `fetch_add`. I found no lost-update race among these callers. The delta correctly measures **logical payload reduction**, not memory returned.

5. **Documentation/defaults: registrations match, but several claims need correction.**

   The scoped README defaults—including **500**, **0.015**, **true**, `faint`, `fisher`, `ranges`, `concentric`, and `evidence`—match registration. The seven-switch recipe disables every new spectrum-changing default. Its finite-data arithmetic supports semantic-spectrum compatibility.

   **Fix-before-tag against literal invariant 2 — [src/diaspextract.cpp:4687](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:4687>): disabling all modes still adds new provenance fields.** In particular, `spx:same_bin_merge` is written even with both merges off. File bytes therefore differ from the pre-merge build and 1.4.1. **Real:** every affected mzML output. The semantic-digest qualification at CHANGELOG:22 is appropriate; “output exactly” at CHANGELOG:32 should carry the same qualification.

   **Fix-before-tag — [CHANGELOG.md:34](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/CHANGELOG.md:34>): the diagnostic recipe and “fate” promise are incorrect.** `DIASPEXTRACT_GATE_TARGETS` expects a **filename** containing whitespace-separated `id mz rt im z`, not `<m/z,rt;...>`. Following the documented syntax yields no target rows. Even with a correct file, the fate calculation ignores the new gate modes: an accepted faint one-point fragment can be labelled `np`, and a colocation-rejected fragment `kept`. **Real:** ordinary diagnostic use with release defaults.

   **Fix-before-tag — [CHANGELOG.md:19](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/CHANGELOG.md:19>): “entrapment FDR on both engines” exceeds the recorded evidence.** The recorded peptide gains cover both engines, but the harness entrapment search and report are Sage-only. **Real:** a published validation claim. The rounded peptide-gain figures themselves check out.

   **Minor — README behavior descriptions omit consequential conditions.** At [README.md:49](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/README.md:49>), faint precursors actually use correlation power **1**, despite the blanket “squared” description. At `:236`, `logoverlap` requires `-gate:shrinkage off`. At `:247`, colocation also checks the reciprocal apex condition; at `:249`, concentric requires span containment. Both allow one-frame slack, and the centre tolerance has a one-frame floor. **Real:** these affect configuration and interpretation.

   **Minor — [CHANGELOG.md:3](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/CHANGELOG.md:3>) omits two user-visible fixes:** the adaptive-window tiling correction and preventing diagnostic TOF conversion on the OpenMS path. **Real scenarios:** faint precursors near tile cuts, and OpenMS runs with `DIASPEXTRACT_DET`.

   The dnoise description matches its changed recovery logic. I could not independently verify the current upstream status of OpenMS PR #10291.

6. **Other release issue: `adaptive auto` enables global relaxation when it reports OFF.**

   **Fix-before-tag — [src/diaspextract.cpp:4273](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/src/diaspextract.cpp:4273>) and `:3221`:** below the run-level faint threshold, `adaptive_` becomes false. Consequently, `all_p = !adaptive_ || faint` becomes true for **every precursor**, enabling default Fisher shrinkage, colocation, and concentric handling despite `auto:off`.

   Concrete case: a dense run below the default 45% threshold, with a five-frame precursor and three distinct-bin one-point fragments at its apex. The promised plain gate rejects those fragments for insufficient shared points; the actual OFF-auto path can accept them through Fisher shrinkage and emit a spectrum.

   **Real or theoretical?** Real-data relevant whenever users select `-gate:adaptive auto` on dense runs. Explicit `adaptive off` intentionally means global application; automatic OFF needs a distinct state.

   The **`tile_drt` fix itself looks correct**: the widest active RT window consistently controls ownership, RT buckets, and transitive carry. I found no further thread/tile determinism defect in the reviewed changes.

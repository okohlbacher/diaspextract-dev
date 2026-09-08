• I'll verify the release documents against the actual files before writing findings.

• Now let me verify the remaining numbers against BASELINE and the REFERENCE-COMPARISON doc.

• The disk files differ from the provided excerpts in places (e.g. CHANGELOG line 78). Let me read the disk CHANGELOG v2.0.0 section directly.

• The disk README is more careful than the excerpt in several places. A few final verifications:

• I reviewed the on-disk files (which differ from the excerpts in the brief in several places — the disk versions already fixed some issues like the "9 GB" disk figure and the "72×/90×" occupancy). Findings below are against the disk state of CHANGELOG.md, README.md, CONTRIBUTING.md, docs/BASELINE.md, docs/REFERENCE-COMPARISON-2026-09-08.md, src/spextractor.cpp, test/test_spextractor.py, and the CI workflows.

  ## Findings

  1. **CHANGELOG.md:36-38** — *"re-calling those to 3+ identified nothing on either file ... while adding 178k / 93k spectra"*. The 178k / 93k figures are veto **call** counts (178,226 on run 009, 93,008 on dataset D), not spectra. The recorded spectrum-list deltas are 4,035,234 → 3,918,321 = **116,913** on 009 (BASELINE T3→T4) and 927,712 → 854,817 = **72,895** on dataset D (BASELINE v37→v38). The same doc's own "2.9% / 7.9% off the v37 spectrum list" is computed from the correct deltas, so the sentence contradicts itself two lines apart. docs/REFERENCE-COMPARISON-2026-09-08.md:202 repeats the same mislabeling. **HIGH**

  2. **CHANGELOG.md:36** — *"z=3 peptides 5,313 -> 5,322 on run 009"*. This number appears in **no** BASELINE.md entry. docs/REFERENCE-COMPARISON-2026-09-08.md:204-205 admits it "exists only in the source comment beside the veto's 3+ branch in src/spextractor.cpp ... and in no BASELINE.md entry". A release headline number whose own companion doc declares it unrecorded. **MEDIUM**

  3. **CHANGELOG.md:56** — *"Chunking over spectra takes it to 0.55 s and the phase to **36.3 s at 8.0x**."* Neither "36.3" nor "8.0x" appears anywhere in BASELINE.md. The recorded numbers (75.9 s phase, 39.0 s serial distribute → 0.55 s; BASELINE:1489-1500) arithmetically give ~37.5 s, and no phase parallelism of 8.0x is on record (the recorded post-fix figure is 106.2 s at 11.2x on TNBC, BASELINE:1509). Unsupported number. **MEDIUM**

  4. **CHANGELOG.md:96** — *"measured, that floor is 138 GB at the loop start of a 2-hour acquisition."* "138 GB" appears nowhere in BASELINE.md; the record says the trim "returns **~99 GB** at the MS1 boundary" (BASELINE:1399). The src help text (src/spextractor.cpp:1777) repeats the unsupported 138 GB. The 265→186 GB peak claim is supported (264.9→186.2, BASELINE:1395-1396). **MEDIUM**

  5. **CHANGELOG.md:125-126** — *"the tool compiles on a stock OpenMS tree"*. Directly contradicts the same section (lines 6-7: "a tree without [the third patch] does not build the tool"; lines 107-108: the `static_assert`), CONTRIBUTING.md:9 ("refuses to compile against a MassTrace without move operations"), and the verified `static_assert(std::is_nothrow_move_constructible_v<OpenMS::MassTrace>...)` at src/spextractor.cpp:54. The intended meaning is evidently "compiles without the mzPeak library", but as written it says a stock (unpatched) OpenMS tree works, which is false. **MEDIUM**

  6. **CHANGELOG.md:19** — *"Whole-run entrapment FDR is at the nominal 1% (0.93-1.03%)"*. At this release's defaults dataset D measures **1.33%** (BASELINE v38 table, and disclosed in the same file's own Measured section, line 218). The headline range silently covers only the two 2-hour runs. **MEDIUM**

  7. **CHANGELOG.md:220-221 vs CONTRIBUTING.md:26** — *"Every interval overlaps the nominal 1%"* and the standing gate "entrapment FDR inside the previous interval". No confidence interval is recorded for any v38 entrapment arm (the v38 tables give point estimates only: 1.24→1.38→1.33% on D). 1.33% exceeds the documented six-dataset band of 1.13-1.31% quoted in the same entry, so compliance with the project's own gate for the shipped default is asserted, not shown. **MEDIUM**

  8. **CONTRIBUTING.md:46-47 vs README.md:85-87** — CONTRIBUTING: "a run with -in, -out and -threads must reproduce the benchmarked configuration. **There is a test for this**." README: the suite "passes a few extraction options of its own, so it is **not a test of the whole default set**". The test file confirms the README: only the detector default (c9) and charge floor (c2/c3) are pinned. The two release documents contradict each other about what is guaranteed. **MEDIUM**

  9. **src/spextractor.cpp:1797-1798 (shipped --help)** — *"which is closer to the truth is UNMEASURED."* Stale: it was measured 2026-09-05 (BASELINE:994-1005: one-shot reader +223 Sage peptides / +2.0% at unchanged entrapment), and both the CHANGELOG Measured entry and README.md:107 document the result. The release ships help text that denies a measurement its own release notes cite. **MEDIUM**

  10. **README.md:155** — *"an admission gate sizes concurrency from free RAM **at startup**."* Stale: the v2.0.0 fix moved admission to a dynamic per-window decision ("Admission now happens on the master before a window task is spawned", CHANGELOG:163; src help for perf:mem_fraction: "re-decided at every window admission", src/spextractor.cpp:1809). **MEDIUM**

  11. **CHANGELOG.md:206** — *"First public-data extraction: 136,818 spectra in 57 s."* BASELINE records two wall times for this same acquisition: 57 s (line 1052, first extraction) and **0:42** (line 1101, campaign table). The release cites one without noting the other; the record is internally inconsistent by 36%. **MEDIUM**

  12. **CHANGELOG.md:282 (v0.3.0 section)** — *"which is where the README's stated 80-125 GB requirement comes from"*. Stale cross-reference: the current README states ~57 GB (30-min) / ~170-190 GB (2-hour); no "80-125 GB" figure exists anywhere in the shipped README. **MEDIUM**

  13. **CHANGELOG.md:40** — *"2.8-2.9% on the 2-hour files"* for the z=1 stratum. Measured: 2.91% (001) and 2.94% (009) — the same document's Measured section (line 219) correctly says "2.9%". src/spextractor.cpp:1828 also says "~2.8%". **LOW**

  14. **CHANGELOG.md:32 and src/spextractor.cpp:1827,1843** — *"~13% of z=1 calls"*. Measured: 287,900/2,548,391 = **11.3%** (009), 11.2% (001); README.md:103 says "11–26%". The ~13% is unsupported by the record and inconsistent with the shipped README. **LOW**

  15. **CHANGELOG.md:78-79** — *"thread occupancy went from 1.0x to 23.4x ... (112-138 s -> 7.8 s)"*. The direct serial arm is v28: **128.8 s → 7.8 s = 16.5x** (BASELINE:1616-1617); 23.4x is the *phase* CPU/wall ratio (629.7/26.9, BASELINE:1628), not the greedy loop's; and 112.8 / 138.3 s come from intermediate builds v27/v25, not the serial baseline. The parenthetical does not multiply out to the headline figure (138/7.8 = 17.7). **LOW**

  16. **CHANGELOG.md:65-66** — *"the residue was the greedy claim loop (156.3 s), not the sorts (8.5 s), which the next entry removes."* Misattribution: the next entry removes binary searches *inside* the greedy walk (130.0/128.8 s), not the 8.5 s of sorts; the greedy loop itself is parallelised by the entry after that. **LOW**

  17. **docs/REFERENCE-COMPARISON-2026-09-08.md:90** — *"spectra 2,343,822 | 4,035,058 (+72%)"* vs BASELINE T3 = **4,035,234**. The two release documents disagree on the v37 spectrum count by 176. **LOW**

  18. **CHANGELOG.md:249-250 (v1.1.0)** — *"On 224 cores against the benchmark's -threads 100: 5:10 vs 5:22 for byte-identical output."* The "5:22" matches BASELINE:831, a line explicitly marked "(SINGLE PAIR -- see the retraction below)". No unretracted support for the pair is on record. **LOW**

  19. **CHANGELOG.md:15-18, 231-232 / README.md:144** — the 0.61x wall ratio compares SpeXtractor's **single** v38 run (12:42.21) against the reference's two-rep mean, while v35's own two reps spread 8% (11:24.97 / 10:36.92). The headline ratio carries single-run noise; the table presents it to two significant figures without saying so. **LOW**

  20. **README.md:32-33** — *"Memory figures throughout are peak RSS as /usr/bin/time reports them (kB ÷ 10⁶)"* vs BASELINE:1429-1430: "Every figure in this file is **GiB**". The 57 / 188 / 187.9 GB figures are lifted from the GiB record, so the README's stated unit convention mislabels them (~7% ambiguity, exactly the "unit trap" the record warns about). **LOW**

  21. **README.md:141** — *"window-loop occupancy 78×"* for the 30-minute gradient. The 89× (009) is on record (89.2x, BASELINE:1917); no dataset D occupancy at v35-v38 is recorded in the v37/v38 tables (the nearest figures are 69.9x from 2026-09-03 and 94.2x from the rejected trace_bands=48 arm). Unsupported number. **LOW**

  22. **Release engineering — CI.** tests.yml (per-push, 4 platforms) builds only `-DSPEXTRACTOR_TESTS_ONLY=ON` targets — it never compiles src/spextractor.cpp. build.yml, whose own comment says it is "the only job that proves the tool compiles", runs **weekly and on-demand only**. So per-push green proves nothing about the tool building, and nothing in the release process forces a full build on the release commit — particularly acute for v2.0.0, whose headline mechanism (the MassTrace static_assert) is a compile-time gate. (The cluster "publish refuses a binary that failed its suite" covers their deploy path, not the public tag.) **HIGH**

  23. **Release engineering — version truth in two places.** CMakeLists.txt:2 (`VERSION 2.0.0`) feeds `-DSPEXTRACTOR_VERSION`, but src/spextractor.cpp:62-63 hardcodes a fallback `#define SPEXTRACTOR_VERSION "2.0.0"`. On the next release the fallback will silently pin a stale version in any non-CMake or mis-configured build. CITATION.cff (2.0.0, 2026-09-08) is consistent. **LOW**

  ## Specific questions

  **Q1 — is v2.0.0 the right bump?** Yes. The executable rename alone (every caller's command line breaks) mandates a major under semver; the mandatory third OpenMS patch breaks the build for every existing build tree; and the default changes (min_charge 2→1, veto on, bands 48, malloc_trim) change output for identical command lines. Any one of these suffices. The CHANGELOG's own reasoning is sound, with one nit: "output is not digest-comparable with 1.x" would not by itself justify a major (any bug fix can change digests) — but it is moot next to the rename. The only process criticism is that v1.0.0/v1.1.0 were cut from the v0.3.0 tree four days earlier, so 1.x users get no deprecation window; that is poor release hygiene, not a semver violation.

  **Q2 — the `version_ = SPEXTRACTOR_VERSION` assignment.** Implemented correctly in the ways that matter: both `version_` and `verboseVersion_` are set (src/spextractor.cpp:1660-1661), and `--help` prints `verboseVersion_`, so all three surfaces named in the CHANGELOG (--help, ini `version`, mzML software entry) will carry 2.0.0. `official=false` is set in the TOPPBase constructor, addressing the ToolHandler registration issue the comment describes. Residual risks, all minor: (a) ini round trips — inis written by 1.x carry the OpenMS version string, so TOPPBase will emit a version-mismatch warning on load; harmless and arguably desirable for a breaking release; (b) downstream parsers that matched the software entry's OpenMS version will no longer match — that is the intended break, disclosed under "Why 2.0"; (c) "2.0.0" parses cleanly as x.y.z anywhere OpenMS parses versions, so no format risk; (d) the dual source of truth in finding 23 is the only real defect.

  **Q3 — inconsistent numbers.** Yes, eight of them: (i) "178k / 93k spectra" vs the recorded 117k / 73k spectrum deltas (finding 1); (ii) "36.3 s at 8.0x" — nowhere in the record (finding 3); (iii) "138 GB floor" vs the recorded ~99 GB (finding 4); (iv) "2.8-2.9%" vs the measured 2.91/2.94 and the same file's own "2.9%" (finding 13); (v) "~13% of z=1 calls" vs 11.3% measured and the README's own "11-26%" (finding 14); (vi) "23.4x" beside "112-138 s -> 7.8 s" — the direct arm gives 16.5x (finding 15); (vii) "136,818 spectra in 57 s" vs BASELINE's own 0:42 for the same acquisition (finding 11); (viii) REFERENCE-COMPARISON's 4,035,058 vs BASELINE's 4,035,234 (finding 17). Plus the stale "80-125 GB" cross-reference (finding 12) and the unsupported 78× occupancy (finding 21).


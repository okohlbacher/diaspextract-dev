# README rewrite for 1.3.2: three-CLI review, what was taken and what was not

Reviewed: dev `1fcdd72` (README.md, the three diagrams, the CHANGELOG v1.3.2 entry, CITATION.cff, CMakeLists.txt).
codex-cli 0.154.0 and kimi 0.42.0 reviewed that commit; vibe 2.25.3 reviewed `72f6d31` (the fix commit) after its
first run hit its turn ceiling — see "Vibe" below. Before the CLIs, three verification agents (facts, diagrams,
audience lenses) checked the same files against the source, the tests and docs/.

## Taken (all fixed in 72f6d31 unless noted)

| # | from | finding | fix |
|---|---|---|---|
| 1 | codex 1, kimi 1 | the output-neutrality legend covered every option table, but holds only for the memory and concurrency one | legend scoped; the detection/charge/gate/assembly/denoising options are described as shaping the spectra by definition |
| 2 | codex 3 | "memory is one tile's" overstates it: the MS1 traces and precursors of the whole run stay resident | tiling now bounds the *fragment working set*; the streaming diagram's title and the `-tile:cells_per_tile` row follow |
| 3 | codex 2 | the chord fallback and the Bruker SDK path abort at the defaults: the MS1 denoiser needs the exact model | both now documented as requiring `-dnoise:ms1 false` |
| 4 | codex 6 | `spx:mz_calibration` has two more values | `mzpeak_two_point_transform` and `unset` added with their input paths |
| 5 | codex 4 | `-trace:mz_estimator` does not set the reported m/z of integer-detector fragment traces (they carry their apex bin, calibrated at export: src/diaspextract.cpp:1176, 1257-1263, 3008, 3121-3127) | row rewritten to separate precursor traces, integer fragments and the `openms` detector |
| 6 | codex 5 | `-trace:band_edges slab` does not give "the same peptides" (docs/BASELINE.md:2838-2842: different digests, five peptides, 1.5 % of spectra) | "the spectra differ slightly, the identifications hardly" |
| 7 | codex 7, kimi 2 | CHANGELOG "all 59 registered options": the tool registers 63; 59 is what the token checker's regex sees; `diag:selftest_arena` is in neither | count dropped, "every user-facing option" |
| 8 | codex 11, kimi 3 | CHANGELOG claimed a `--helphelp` defaults gate that does not exist in CI | now says the names are gated in CI and the defaults were cross-checked by hand for this release |
| 9 | codex 13 | "The cluster reference arm stays v1.3.1" is internal bookkeeping | removed from the public CHANGELOG |
| 10 | codex 8 | the mzML writer patch gives a byte-identical *spectrum list*, not output | wording fixed |
| 11 | codex 9 | the halo filter excludes the candidate's own TOF bin (src/DnoiseMs1.h:677) | added |
| 12 | codex 10 | `min_fragments` is checked before the `max_fragments` cap | both rows say so, with the advice to keep the cap at or above the minimum |
| 13 | codex 12 | the `-threads` rule: an ini value above 1 *is* honoured, only `threads = 1` counts as unset | row rewritten |
| 14 | kimi 4 | the EPD lock "serialised the tool": the record says it burned ~28 % of CPU in blocked threads and did not shorten the wall | "burned about a quarter of the CPU in blocked threads" |
| 15 | kimi 5, 6, 7 | three measured ranges slightly outside what docs/BASELINE.md supports (MSFragger +4.4 % on one file; im_weight_sigma 7.1 %; native_ms1_neighbors measured on older defaults) | ranges widened / qualified |
| 16 | kimi 8 | the resident path prints `LOAD(full)` | added to the pipeline diagram's footnote |
| 17 | vibe 1 | "multiplied by the square of its correlation" reads as hardcoded | now names `-assembly:corr_power` and its default |
| 18 | vibe 5 | "one window is always admitted" without the reason | "whatever the memory says, so a single oversized window cannot deadlock the run" |

Earlier, from the verification agents: the LOAD box claimed MS2 frames are read at load (they are read per tile inside
the window loop), the assembly order (rank by correlation-weighted intensity, then cap, then emit with corr^k), the
gate is over the full RT grid with ≥ 3 shared points, "same window and cell" narrowed to the isolation window,
`calibration_golden` covers 270 cases from nine acquisitions, the prune drops centroids *at or below* the threshold,
build.yml applies the patches before configuring OpenMS, and the compiler floors (GCC 13+/Clang 16+) had no source.

## Not taken

- **codex 12 / vibe 2, 7** on describing TOPPBase's registered default of 1 in the Run section: the option row now
  carries the full rule; repeating the mechanism where a user reads "pass `-threads <n>` on a shared machine" would
  cost more than it explains.
- **vibe 3, 4**: `-perf:stream_load false` already says "on a machine with the memory for it" and its row gives the
  1.75× figure; `-assembly:im_weight_sigma` is already in the sensitivity list, and `-assembly:corr_power` ships at
  its measured best value, so there is nothing for a user to change.
- **vibe 6**: the mzPeak transform value was already added (item 4 above); vibe reviewed the commit that has it.
- **vibe 2, 8, 9, 10 and its two "blockers"**: withdrawn by vibe itself after reading the source.

## Vibe: incomplete first run, recorded as such

The first vibe run (40-turn limit, the flag matrix's documented value) ended with
`<vibe_stop_event>Turn limit of 40 reached</vibe_stop_event>` and an empty review, and it wrote three files inside
its throwaway worktree (discarded with it; the real tree was untouched). `--trust` also produced nothing; the run
that worked used `--auto-approve --max-turns 200`, on the fix commit rather than on `1fcdd72`. So vibe did not see
`1fcdd72`, and its review is of the already-corrected text. Codex likewise reported a rejected flag in its wrapper
log (the dispatcher's flag-rejection heuristic matched the brief's own quoted text: "Unknown option(s) '[-a:b]'"),
but its review completed and is recorded here in full.

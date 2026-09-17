• I'll work through this systematically. Let me first set up tracking, then delegate ground-truth checks in the docs and tests while I read the remaining source and diagrams myself.

• While those run, I'll examine the rest of the source myself.

• The `spx:` stamps are at lines 4152–4171 and the `-threads` scan at 3145–3155. Let me read the surrounding logic plus main().

• Now the SVGs, the OpenMS lock file, and the patch internals.

• Let me check for the "defaults cross-check against --helphelp" that the changelog claims, and run the option-token script.

• Both ground-truth passes are in. Here is the complete review.

  # Review: DIAspeXtract 1.3.2 documentation release

  ## Findings, ranked

  **1. should-fix — README.md:148–149: "options marked **changes output** move the spectrum list, the others only cost or save time and memory."**
  The sentence is global, but it is only true of the `perf:`/`tile:` table (README.md:168 states it correctly there). Unmarked options that plainly move the spectrum list include `-gate:delta_rt`, `-gate:min_correlation`, `-assembly:min_fragments`, `-charge:min_charge`, `-trace:mass_error_ppm` and most of the `trace:`/`dnoise:` tables — they change the gate, the emission floor or the traces by design (src/diaspextract.cpp:2127–2146, 2235–2241). Under your own stated convention ("an option marked otherwise must really be output-neutral"), every one of these is mis-marked by omission. Fix: scope the sentence to the resource knobs, e.g. "in the memory/concurrency table, options marked **changes output** move the spectrum list; the others only cost time or memory" — line 168 already carries the correct version.

  **2. should-fix — CHANGELOG.md:18: "The option reference lists all 59 registered options with their defaults."**
  Wrong on two counts. `registerOptionsAndFlags_()` registers **63** options (src/diaspextract.cpp:2103–2283; this release's own v1.2.0 entry says "the shipped tool registers 63 options", CHANGELOG.md:501). 59 is only the count of colon-prefixed names that `scripts/check_option_tokens.py`'s source regex can see (scripts/check_option_tokens.py:61; it prints "against 59 registered options"), i.e. 63 minus `in`, `out`, `out_type`, `max_charge`. And the README does not list even those 59: `diag:selftest_arena` (src/diaspextract.cpp:2166) appears nowhere in README.md, so it covers 62 of 63. Fix: "lists all 63 registered options" and add a one-line `diag:selftest_arena` row, or drop "all" and say "every user-facing option".

  **3. should-fix — CHANGELOG.md:21: "`scripts/check_option_tokens.py` and a defaults cross-check against `--helphelp` gate the text."**
  The first half is real (tests.yml runs the script on every push, build.yml against the binary's `-write_ini`). The second half describes a gate that does not exist: no workflow or script compares README defaults against `--helphelp` output; the only mention of the idea is as future work in docs/BACKLOG.md:901 ("Generate the README section from `--helphelp`…"). A release note claiming a verification gate that was never run is worse than no sentence. Fix: delete the second conjunct, or land the cross-check before tagging.

  **4. nit — README.md:109: the EPD patch row says "called from a parallel window loop, that one lock serialised the tool."**
  The record contradicts the implication that removal shortened the run: docs/benchmarks/runtime-2026-07-25.md:44–46 — removing the contention "freed 28% of CPU but did not shorten wall" (wall was +4.5%). Fix: "that one lock burned ~28 % of CPU in blocked threads".

  **5. nit — README.md:229: `corr_power` "2 gives +8–10 % Sage and +5–8 % MSFragger peptides over 0."**
  The only dataset-D MSFragger measurement is +4.4 % (docs/BASELINE.md:629–630); the +5–8 % band holds on datasets A/B only. The README inherits this verbatim from the help text (src/diaspextract.cpp:2136), so fix both or neither.

  **6. nit — README.md:230: `im_weight_sigma` "0.005 gave +1–7 % Sage peptides."**
  Dataset A is +7.1 % (docs/BASELINE.md:142–143) — marginally above the stated band; likewise inherited from src/diaspextract.cpp:2135.

  **7. nit — README.md:198: `native_ms1_neighbors` "about 2.7× the spectra for about 8 % more Sage peptides."**
  The measurement behind this is from 2026-07-27, pre-calibration-fix, Sage-only, and flagged confounded in docs/BACKLOG-ANALYSIS-2026-09-02.md. The help text (src/diaspextract.cpp:2193) carries the "(2026-07-27, older defaults)" caveat; the README dropped it. Fix: keep the date qualifier.

  **8. nit — assets/pipeline.svg:46: "LOAD is printed as LOAD(stream) and LOAD(tile)."**
  The resident path prints `LOAD(full)` (src/diaspextract.cpp:3468). The footnote is incomplete, not wrong; add it or drop the parenthetical.

  **9. nit — README.md:164 / src/diaspextract.cpp:3149: the `-threads` argv scan matches the exact string `-threads`.**
  `--threads 1` (double dash, accepted by TOPPBase) escapes the scan and is silently overridden to all cores. The README documents only `-threads <n>`, so this is consistent as written — worth one clause ("pass it single-dash") or a code tweak, your call.

  ## What I checked that is clean

  - **The gate** (attack 2): exactly |ΔRT| ≤ `gate:delta_rt` (3 s) ∧ |ΔIM| ≤ `gate:delta_im` (0.01) ∧ Pearson ≥ `gate:min_correlation` (0.3) over the full frozen frame grid with ≥ `gate:min_correlation_points` (3) shared points (src/diaspextract.cpp:2945–3001). README.md:36–38 and algorithm.svg:28–29 state it correctly.
  - **corr_power ordering**: the emitted intensity carries corr² for every accepted fragment, but the `max_fragments` ranking key is corr × (IM-weighted) intensity *without* corr_power (src/diaspextract.cpp:3002–3025), so corr_power cannot change the cut — matching README.md:39–41 and the assembly table's claim that only `im_weight_sigma` moves the cut.
  - **Boundary fragments** are carried between tiles (transitively, within 2·delta_rt; src/diaspextract.cpp:4052–4057, 4129–4132) and **one window is always admitted** (src/diaspextract.cpp:4292–4293). README.md:63–65 correct.
  - **Sixteen `spx:` userParams**: README.md:253–257 is exactly the stamped set (src/diaspextract.cpp:4152–4171), including `spx:pearson_G` = "frames" and the three `spx:mz_calibration` values from patches/openms-brukertims-mz-calibration.patch:45.
  - **`-threads`**: main() scans argv and uses every core when absent (src/diaspextract.cpp:3145–3156); README.md:134/164 and the v1.3.2 changelog entry are accurate, including "ini `threads = 1` counts as unset".
  - **Every default in the README tables** matches its registration (gate 3 s/0.01/0.3/3; assembly 3/500/2/0/true/2; trace 15/100/10/3/0/3,1/7,7/120; dnoise 3,5,2,2,0,0 / true,0.15,80,2 / true,5,0.05; perf 0.75/0/true/true/48/12/true; tile 600/1; charge 1/5/count/true/2.5/0.05/0,off).
  - **SVGs**: every number (48 bands, 120 s, 12 bands, 600 s, 3 s, 0.01, 0.3, 3 points, ±0.05, top 500, ≥ 3, corr², 75 %, cells_per_tile 1/0) and the stage order match the code; phase names exist as printed (except finding 8).
  - **CHANGELOG v1.3.2 otherwise**: "three diagrams" ✓; "binary differs from 1.3.1 only in its version string" — verified, `git diff v1.3.1..HEAD` touches only the version define in src/ plus docs/metadata; "-threads" correction ✓.
  - **CITATION.cff** (1.3.2, 2026-09-17) and **CMakeLists.txt** (project VERSION 1.3.2, with the drift guard) are consistent with CHANGELOG and the source fallback.
  - **Hygiene**: README contains no PXD numbers, run labels, specimen identifiers, home paths, or the comparison tool's name (docs/ name it; README does not). No dated-chronology or internal-review leftovers remain in the README.
  - Numeric claims I traced to docs all hold: 85 % detector agreement / 40 % memory (CHANGELOG.md:954–963), 0.2 % near-cut loss (0.17 %, docs/BASELINE.md:2670), stream_load 1.75×/1.7×/+2.0 % (docs/BASELINE.md:994–1016), 20 s → 6 s writer patch (docs/BASELINE.md:2069–2072), 6–11 % chord identifications (docs/BASELINE.md:403–409), `DIASPEXTRACT_LOAD_BATCH` default 256 (patch :440–443), e2e 25/26 checks, calibration golden 270 cases.
  - "Which option for what" (README.md:151–155) covers memory, time, sensitivity and FDR — attack 5's mapping exists and is accurate.

  ## Verdict

  No blockers; nothing here touches the software, and the README's algorithm description, option defaults and diagrams are unusually well pinned to the source. But I would **not tag as-is**: fix the three should-fix items first — two are false statements in the release notes themselves (the "59"/"all" option count, and a verification gate that doesn't exist), and one is a README sentence that mislabels the majority of the scientific options as output-neutral. All three are one-line edits.


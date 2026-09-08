Based on my analysis of CHANGELOG.md, README.md, docs/BASELINE.md, docs/REFERENCE-COMPARISON-2026-09-08.md, src/spextractor.cpp, and test/test_spextractor.py, here is the numbered list of findings:

---

### Findings

1. **(README.md, line in `-charge:min_charge` option description)** "Their stratum carries ~3% entrapment FDR under a pooled 1% cut" — WRONG. The measured z=1 stratum FDR under pooled 1% cut is 8.8–9.2% on the 30-minute dataset (dataset D) and 2.91% on 2-hour files (TNBC 001/009). The README’s ~3% is not accurate for any dataset under the shipped defaults. Evidence: BASELINE.md lines 1876 (8.8%), 1899 (2.91%), 1902 (2.9%); REFERENCE-COMPARISON lines 161–162 (2.9%). Severity: **HIGH**

2. **(CHANGELOG.md, “Changed” section, precursor inference)** “the greedy claim loop went from 1.0x to **23.4x** on a 2-hour file, 112–138 s -> 7.8 s” — WRONG. 112/7.8 = 14.36x, 138/7.8 = 17.69x; the maximum possible speedup from the quoted times is ~17.7x, not 23.4x. Evidence: direct calculation from the stated durations. Severity: **HIGH**

3. **(CHANGELOG.md, “Added” vs “Measured” sections, `perf:malloc_trim`)** “30% less peak memory for about 8% more wall time” (Added) vs “costs **+8.5% of wall time**” (Measured) — INTERNALLY CONTRADICTORY. Evidence: source comment (spextractor.cpp:1780) and BASELINE.md consistently cite +8.5%; “about 8%” understates the measured cost. Severity: **MEDIUM**

4. **(CHANGELOG.md, “Where it stands” vs “Added” sections, peak memory)** “12:42 / 188 GB” (Where it stands) vs “takes the peak from **265 GB to 186 GB**” (Added) — INTERNALLY CONTRADICTORY. BASELINE.md (line 1915) records v38 peak at 187.9 GB; the Added section’s 186 GB and the summary’s 188 GB cannot both be the overall peak for the same run. Severity: **MEDIUM**

5. **(CHANGELOG.md, “Changed” section, trace record size)** “2.1 billion records, **143.6 GiB at 72 bytes** if simultaneous” — WRONG. 2.1×10⁹ × 72 B = 151.2 GB = 140.9 GiB (151.2×10⁹ / 1024³). Evidence: arithmetic. Severity: **MEDIUM**

6. **(README.md, `-perf:stream_load` option description)** “Measured on dataset D 2026-09-04, true = 655,776 spectra… false = 656,371” — STALE. With the shipped v2.0.0 defaults (min_charge=1 + veto), dataset D emits 854,817 spectra (BASELINE.md line 1869). The README quotes pre-v37 data. Severity: **MEDIUM**

7. **(CHANGELOG.md, “Changed” section, `charge:min_charge`)** “it discarded **14–20% of Sage peptides**” — AMBIGUOUS/UNSUPPORTED. The old default (min_charge=2) resulted in **14–20% fewer Sage peptides** on 2-hour files (v35→v38: +14–20%), not “discarded 14–20% of all Sage peptides.” Evidence: REFERENCE-COMPARISON lines 97–98 (+14.2% on 009, +20.1% on 001). Severity: **LOW**

8. **(README.md, Performance table and Requirements)** Memory range “**~170–190 GB**” — OVERLY CONSERVATIVE. BASELINE.md records 177.4–180.0 GB (v37) and 187.9 GB (v38) on 2-hour; actual spread is ~177–188 GB. Severity: **LOW**

9. **(README.md, Determinism section)** “byte-identical **at any thread count**” — OVER-CLAIM. The test suite (test_spextractor.py) only verifies 1 vs 4 threads (check c6); “any” is unproven. Severity: **LOW**

10. **(CHANGELOG.md, “Where it stands” section, reference wall time)** “20:57 / 341 GB” — ROUNDED vs BASELINE.md’s “20:56.9 / 340.6 GB.” The rounded figures are acceptable, but the CHANGELOG should either use the precise means or state they are rounded. Severity: **LOW**

---

---

### Answers to Specific Questions

**Q1. Is v2.0.0 the right semver bump?**
**YES.** Three breaking changes justify MAJOR: (1) executable rename `spextract`→`spextractor` breaks all calling scripts; (2) the third OpenMS patch (`MassTrace` move ops) is enforced by a `static_assert` (src/spextractor.cpp:54), so an unpatched tree **fails to compile**; (3) outputs are not digest-comparable with 1.x. Previous public releases were v1.0.0 and v1.1.0 (2026-09-04). Per semver, any backward-incompatible change demands MAJOR.

**Q2. Risk from `TOPPBase::version_ = SPEXTRACTOR_VERSION`?**
**LOW correctness risk; NONE for compatibility with search engines.** The assignment (src/spextractor.cpp:1660) makes `--help`, the ini `version` parameter, and the mzML `<software>` entry report “2.0.0” instead of the OpenMS version. This **fixes an attribution error** (the tool is not OpenMS). Downstream:
- OpenMS version checks on unofficial tools: none known; SpeXtractor is standalone.
- ini-file round trips: harmless (SpeXtractor owns the ini).
- mzML software entry: improved provenance.
The CHANGELOG explicitly documents this change.

**Q3. Inconsistent numbers in CHANGELOG v2.0.0 or README?**
**YES — see findings 1–6 above.**
- **HIGH severity:** README’s ~3% z=1 FDR (Finding 1); CHANGELOG’s 23.4x precursor loop speedup (Finding 2).
- **MEDIUM severity:** malloc_trim wall-time (8% vs 8.5%, Finding 3); peak memory (186 vs 188 GB, Finding 4); trace memory (143.6 vs 140.9 GiB, Finding 5); stale stream_load numbers (Finding 6).
All ratios in the CHANGELOG’s head-to-head table (lines under “Measured”) are **consistent** with BASELINE.md and REFERENCE-COMPARISON-2026-09-08.md.
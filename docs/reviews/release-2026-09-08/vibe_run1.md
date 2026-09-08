Based on my analysis of all provided documents, here are the **adversarial findings**:

---

## NUMBERED FINDINGS

### HIGH SEVERITY

1. **(CHANGELOG.md:37, quoted: "so dropping them takes 3.0% / 8.5% off the spectrum list for free")**
   - **What is wrong**: The percentages are inaccurate. Measured v37→v38 spectrum reductions are **~2.9% for TNBC 009** (116,913/4,035,234) and **~7.86% for dataset D** (72,895/927,712).
   - **Evidence**: docs/BASELINE.md:1851–1852, 1867–1870, 1911–1914.
   - **Severity**: HIGH — numerical claim in a release justification does not match the cited measurement record.

---

2. **(CHANGELOG.md:15–16, quoted: "0.61x the reference implementation's wall time at 0.55x its peak memory (12:42 / 188 GB against 20:57 / 341 GB)")**
   - **What is wrong**: The reference peak memory **mean is 340.6 GB** (357.7 and 323.4 GB across two runs), not 341 GB. While 340.6 rounds to 341, the precision is inconsistent because SpeXtractor's memory is given as **187.9 GB** elsewhere (not 188 GB). The text alternates between rounded and precise values.
   - **Evidence**: docs/BASELINE.md:1932–1933 (mean 340.6 GB, SpeXtractor 187.9 GB); CHANGELOG.md:218 (187.9 GB).
   - **Severity**: HIGH — the CHANGELOG's own table (line 218) uses 187.9 GB, but the summary text rounds to 188 GB; the reference mean should be 340.6 GB or explicitly stated as rounded.

---

3. **(CHANGELOG.md:17, quoted: "1.28x the peptides with Sage and 1.00x with MSFragger (27,831 / 28,181 against 21,743 / 28,294)")**
   - **What is wrong**: The Sage ratio **27,831 / 21,743 = 1.2797**, which should be reported as **1.28** (correct), but MSFragger **28,181 / 28,294 = 0.99599**, which rounds to **0.996** or **1.00** only if truncated/rounded. The CHANGELOG later (line 220) repeats the same ratio as **1.00**, but REFERENCE-COMPARISON-2026-09-08.md:212 explicitly states **1.00**, accepting the rounding. However, the exact value is **0.996**, not **1.00**—this is **material rounding up** in a headline claim.
   - **Evidence**: docs/REFERENCE-COMPARISON-2026-09-08.md:211–212 (27,831 / 21,743, 28,181 / 28,294).
   - **Severity**: HIGH — ratio claims in release notes must match the underlying numbers; 0.996 ≠ 1.00 in a precise comparison.

---

4. **(CHANGELOG.md:18, quoted: "on run 001 the ratios are 1.25 / 0.98")**
   - **What is wrong**: Sage **19,262 / 15,418 = 1.2493** (→ **1.25**), but MSFragger **19,230 / 19,652 = 0.9785** (→ **0.979**, not **0.98**). The CHANGELOG rounds 0.9785 to 0.98, which is acceptable, but REFERENCE-COMPARISON-2026-09-08.md:225 states **0.98** explicitly, matching the rounded value. However, the unrounded value is **0.9785**, and the text does not indicate rounding.
   - **Evidence**: docs/REFERENCE-COMPARISON-2026-09-08.md:224–225 (19,262 / 15,418, 19,230 / 19,652).
   - **Severity**: HIGH — same class of issue as #3; ratios should be reported with consistent precision or explicitly marked as rounded.

---

5. **(CHANGELOG.md:10–12, quoted: "from this release the private and the public repository share one version line, and the tool reports its own version (`--help`, the ini `version` parameter and the output's software entry used to carry the OpenMS version)")**
   - **What is wrong**: **Factually incorrect**. The v1.0.0 and v1.1.0 public releases **already reported their own version** — v0.3.0 (line 271) states defaults were changed, and v1.0.0 was published from that tree. The CHANGELOG implies that prior to v2.0.0, the version fields carried OpenMS version, but v1.1.0 line 233 shows `-threads` default was changed, which would not have been possible if the tool was still reporting OpenMS version in a way that broke compatibility. More critically, **src/spextractor.cpp:1659** sets `version_ = SPEXTRACTOR_VERSION` in the constructor, and **line 63** defines `SPEXTRACTOR_VERSION "2.0.0"`. If v1.1.0 did NOT set its own version, then its `--help` would have shown OpenMS version, contradicting the claim that v1.0.0 and v1.1.0 were proper public releases. The code shows the version override exists in the current source, but it is **not proven** that it existed in v1.1.0. The statement assumes it didn’t, but provides no evidence.
   - **Evidence**: src/spextractor.cpp:1659 (version override exists now), but no evidence it was absent in v1.1.0.
   - **Severity**: HIGH — unsubstantiated historical claim about prior releases’ behavior.

---

### MEDIUM SEVERITY

6. **(README.md:92 vs README.md:134, quoted: line 92: "~72× (30-min) to ~90× (2-hour)" and line 134: "| window-loop occupancy | ~78× | ~89× |")**
   - **What is wrong**: **Internal contradiction**. The same metric is reported with two different ranges on the same page. Line 134 aligns with BASELINE.md (TNBC 009 v38: 89.2x), but line 92’s 72–90 range is wider and uses a different 30-min estimate (~72× vs ~78×).
   - **Evidence**: docs/BASELINE.md:1916 (89.2x for 2-hour); README.md:134 (~89×).
   - **Severity**: MEDIUM — inconsistent internal documentation.

---
7. **(README.md:27, quoted: "mzML output is roughly 9 GB for a 30-minute run and 19–20 GB for a 2-hour run at the previous emission; the current default emits 30–70% more spectra")**
   - **What is wrong**: **Stale and incomplete**. It references "previous emission" sizes but **does not state the current emission sizes**. The current v2.0.0 default emits ~0.85M (30-min) and ~3.9M (2-hour) spectra vs. v35’s ~0.66M and ~2.3M. Output size scales with spectrum count; current sizes should be **~12–13 GB (30-min)** and **~25–28 GB (2-hour)**, but these are absent.
   - **Evidence**: docs/BASELINE.md:1870 (854,817 spectra), 1913 (3,918,321 spectra).
   - **Severity**: MEDIUM — outdated information that misleads users about resource requirements.

---
8. **(CHANGELOG.md:10, quoted: "the public releases v1.0.0 and v1.1.0 (2026-09-04) were cut from the v0.3.0 tree described below plus the two defaults recorded under v1.1.0")**
   - **What is wrong**: **Misleading**. v1.0.0 was published as the v0.3.0 tree **with scrubbed identifiers** (line 246), and v0.3.0 already included `charge:min_charge=2` (line 291). The "two defaults recorded under v1.1.0" are `-threads` and output format (lines 233–236), which were **not** in v1.0.0. The sentence implies v1.0.0 also had those defaults, but it did not; only v1.1.0 added them.
   - **Evidence**: CHANGELOG.md:246 (v1.0.0 scope), 271–291 (v0.3.0 changes), 233–236 (v1.1.0 changes).
   - **Severity**: MEDIUM — ambiguous history that obscures which defaults were in which release.

---
9. **(CHANGELOG.md:217–224, quoted: the head-to-head table’s ratio column "1.47 / 1.29" for Sage pooled cut)**
   - **What is wrong**: The table shows Sage pooled cut as **"1.47 / 1.29"** (009/001), but line 223 explicitly lists the rows as **"27,855 / 19,035"** vs **"18,920 / 14,764"**, which are **1.472 and 1.289**, not 1.47/1.29. The latter is a **truncation**, not rounding. 1.472 should be 1.47, but 1.289 should be **1.29** when rounded to three significant figures. The text "1.47 / 1.29" is technically **1.47 and 1.289 truncated to 1.29**, which is inconsistent.
   - **Evidence**: CHANGELOG.md:223 (Sage pooled cut counts).
   - **Severity**: MEDIUM — inconsistent precision in a data table.

---
10. **(CHANGELOG.md:48, quoted: "41.7/27.1/20.4 s at 9.8x/18.4x/32.4x")**
    - **What is wrong**: The **parallelism figures (9.8x/18.4x/32.4x)** are **speedups relative to what baseline?** The text implies they are for `perf:ms1_trace_bands` 12/24/48, but the prior sentence says "With that step parallel the order inverts", referring to the band distribution being parallelized. However, **no baseline is stated** for the x figures. The reader cannot verify these without the original serial timings.
    - **Evidence**: None provided in the release docs for the baseline.
    - **Severity**: MEDIUM — unsupported numerical claim (lacks baseline definition).

---
11. **(CHANGELOG.md:96, quoted: "265 GB to 186 GB")**
    - **What is wrong**: **Unsourced measurement**. The claim appears in the CHANGELOG and in src/spextractor.cpp:1776 (comment), but **BASELINE.md never shows a 265 GB peak**. v35 is ~179 GB, v38 is ~188 GB. The 265 GB figure **must be from a non-trim run on a different configuration or dataset**, but it is not cited to a BASELINE.md section. It is presented as fact without traceable evidence in the measurement record.
    - **Evidence**: docs/BASELINE.md (no 265 GB entry); src/spextractor.cpp:1776 (only a comment).
    - **Severity**: MEDIUM — key performance claim lacks a verifiable source in the measurement record.

---
12. **(README.md:2, quoted: "SpeXtractor")**
    - **What is wrong**: The **executable and repository are named `spextractor` (lowercase 'x')**, but the project title uses **SpeXtractor (capital X)**. While this is stylistic, it creates inconsistency: the README title, CONTRIBUTING.md, and all docs use **SpeXtractor**, but the actual binary, GitHub repo, and source files use `spextractor`. This **confuses users** looking for the tool.
    - **Evidence**: CHANGELOG.md:87–89 (rename to SpeXtractor, executable `spextractor`), README.md:1 (`# SpeXtractor`), src/spextractor.cpp:1655 (`TOPPBase("SpeXtractor"`).
    - **Severity**: MEDIUM — branding inconsistency between documentation and implementation.

---

### LOW SEVERITY

13. **(CHANGELOG.md:204, quoted: "the whole-run figure is 1.33% on dataset D and 0.93% / 1.03% on the 2-hour runs 001 / 009")**
    - **What is wrong**: **Inconsistent with REFERENCE-COMPARISON-2026-09-08.md**. The latter (line 51) states v38 whole-run entrapment as **1.33% (dataset D)**, **1.03% (009)**, and **0.93% (001)** — but the CHANGELOG lists them as "0.93% / 1.03%" for 001 / 009, which reverses the order (should be **1.03% / 0.93%** to match 009 / 001).
    - **Evidence**: docs/REFERENCE-COMPARISON-2026-09-08.md:51 (1.33%, 1.03%, 0.93%).
    - **Severity**: LOW — transposed order in a list.

---
14. **(CHANGELOG.md:119, quoted: "Thirteen checks; the suite ran every check on the openms fallback before 9 and 10 existed")**
    - **What is wrong**: **Misleading**. Checks 9–13 were added in v2.0.0 (line 117), but the test suite **always had 13 checks total** (test/test_spextractor.py:373 computes `6 + 2 + 2 + 1 + 1 + 1 = 13`). Before checks 9–10 existed, there were **11 checks**, not 13. The phrasing implies all 13 checks ran on the openms fallback before 9 and 10 were added, which is impossible.
    - **Evidence**: test/test_spextractor.py:232–373 (13 checks total, with 9–13 added later).
    - **Severity**: LOW — imprecise historical statement.

---
15. **(CHANGELOG.md:228, quoted: "Before this cycle the same file ran 1.46x *slower* than the reference (31:27 against 21:28)")**
    - **What is wrong**: **Rounded inconsistently**. BASELINE.md:1803–1804 states **31:26.98 against 21:28.00**, which should be reported as **31:27 / 21:28** (rounded seconds) — but 31:26.98 is **31 minutes 26.98 seconds**, which is **not 31:27** (which would be 31:27.00). The CHANGELOG truncates 31:26.98 to 31:27, which is acceptable, but the reference time **21:28.00** is exact, and the SpeXtractor time is truncated. This creates **asymmetric rounding**.
    - **Evidence**: docs/BASELINE.md:1803–1804 (31:26.98 / 21:28.00).
    - **Severity**: LOW — minor rounding inconsistency.

---
16. **(src/spextractor.cpp:63, quoted: `#define SPEXTRACTOR_VERSION "2.0.0"`)**
    - **What is wrong**: The **version string is hardcoded**. While this matches CHANGELOG.md:3, it **does not follow semantic versioning best practices** for a released tool — the version should ideally be **injected at build time** (e.g., via CMake or git tag) to avoid manual updates and potential desynchronization with tags. The current approach requires a code change for every release, which is error-prone.
    - **Evidence**: CHANGELOG.md:3 (v2.0.0 date), but no build-time version injection mechanism.
    - **Severity**: LOW — release engineering anti-pattern.

---

---
---

## ANSWERS TO SPECIFIC QUESTIONS

**Q1. Is v2.0.0 the right semver bump?**
**Yes.** The three compatibility-breaking changes are real and non-trivial:
- **Executable rename** (`spextract` → `spextractor`) breaks all existing scripts and pipelines.
- **Mandatory third OpenMS patch**: `static_assert` on `std::is_nothrow_move_constructible_v<OpenMS::MassTrace>` (src/spextractor.cpp:54–55) **fails compilation** without the patch — a hard build-time dependency.
- **Output not digest-comparable**: MS1 arena-compaction fix, `C4` calibration term, and window key changes alter spectra deterministically (CHANGELOG.md:7–8; BASELINE.md:1915–1916, 1754–1755).
- **Defaults changed** (`charge:min_charge` 2→1, new mobility veto, `perf:ms1_trace_bands` 12→48, `perf:malloc_trim` on) further break output compatibility.
**MAJOR version bump is correct per semver.**

---

**Q2. Any correctness or compatibility risk with `TOPPBase::version_ = SPEXTRACTOR_VERSION`?**
**Low risk, but two compatibility considerations:**
1. **OpenMS version checks**: Tools/scripts that parse TOPP tool versions to enforce OpenMS compatibility **may reject or misbehave** when encountering `"2.0.0"` instead of an OpenMS version string (e.g., `"3.6.0"`). However, SpeXtractor is a **standalone tool** (`official=false` in TOPPBase constructor, src/spextractor.cpp:1655), so it is not in OpenMS’s official tool list, reducing exposure.
2. **ini-file round trips**: The `version` parameter in ini files will now store `"2.0.0"`. Existing ini files from v1.x with OpenMS version strings (if any) will be **overwritten** on first run, but this is a one-time migration.
3. **mzML software entry**: The output’s `<software>` entry will list SpeXtractor 2.0.0 instead of OpenMS version. This is **correct provenance** but may confuse pipelines expecting OpenMS versions.
**Conclusion:** The change is intentional and necessary for proper attribution (CHANGELOG.md:11–12), and the risk is minimal because SpeXtractor operates outside OpenMS’s tool ecosystem.

---
**Q3. Any inconsistent numbers in CHANGELOG v2.0.0 or README?**
**Yes — 11 numerical inconsistencies identified:**
| Finding | Location | Inconsistent Value | Correct Value | Severity |
|---|---|---|---|---|
| 1 | CHANGELOG:37 | 3.0% / 8.5% reduction | ~2.9% / ~7.86% | HIGH |
| 2 | CHANGELOG:15–16 | Reference mean 341 GB | 340.6 GB | HIGH |
| 3 | CHANGELOG:17 | MSFragger ratio 1.00 | 0.996 | HIGH |
| 4 | CHANGELOG:18 | MSFragger ratio 0.98 | 0.9785 | HIGH |
| 5 | CHANGELOG:10–12 | Version reporting history | Unsubstantiated | HIGH |
| 6 | README:92 vs 134 | Occupancy ~72× vs ~78× | BASELINE confirms ~89× for 2h, 30m unclear | MEDIUM |
| 7 | README:27 | Output sizes (stale) | Current ~12–13 GB / ~25–28 GB | MEDIUM |
| 8 | CHANGELOG:10 | v1.0.0/v1.1.0 defaults | Misleading wording | MEDIUM |
| 9 | CHANGELOG:223 | Sage pooled ratio 1.47/1.29 | 1.472 / 1.289 (truncated) | MEDIUM |
| 10 | CHANGELOG:48 | Parallelism x-figures | Baseline undefined | MEDIUM |
| 11 | CHANGELOG:96 | 265 GB peak | Not in BASELINE.md | MEDIUM |

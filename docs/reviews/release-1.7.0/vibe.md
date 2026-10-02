Based on my systematic review of the diff `31bbab1..cea89fe`, here is the adversarial findings report:

---

## **BLOCKER**

### 1. Public-text leak: in-house dataset names in CHANGELOG.md
- **Severity**: blocker
- **File**: `CHANGELOG.md` (public, not in `.export-private`)
- **Lines**: 95, 1181, 1234, 1254, 1256, 1311–1314, 1318, 1326, 1365–1370, 1380, 1386–1389, 1401, 1417, 1432, 1471, 1496, 1498, 1516, 1549, plus 353, 444, 495, 537, 619, 622, 680, 682, 694, 701, 719, 791, 804, 983, 996, 1002, 1014, 1055, 1057, 1074, 1079, 1126, 1591–1592
- **Concrete failing input**: Any reader of CHANGELOG.md
- **Issue**: Repeated references to "dataset A", "dataset B", "dataset C", "dataset D", "dataset F", "cohort samples are datasets A-F", "in-house cohort", and "dataset-D baseline file" violate Invariant 5.
- **Real-world impact**: Public text names in-house data, breaching the project's data policy.

---

## **SHOULD-FIX**

### 2. CHANGELOG.md references a private file
- **Severity**: should-fix
- **File**: `CHANGELOG.md:95`
- **Issue**: Mentions `docs/BASELINE.md` (which is in `.export-private`) as containing historical in-house measurements. While the file itself is private, referencing it in public text leaks that it exists and its purpose.

---

## **NOTES**

### Question 1: R1–R12 removals at defaults or under kept options

| Removal | Default in 1.6.1 | Now hard-coded | Behavioral change at defaults? | Why |
|---------|------------------|-----------------|-------------------------------|-----|
| R1 `gate:coelution=logoverlap` | `pearson` | always `pearson` | **No** | The `log_overlap_` flag was always false; Pearson path unchanged |
| R2 `gate:variance_support` | off | always full-grid | **No** | `var_support_` always false; Pearson variance always over full grid |
| R3 `charge:scoring=envelope` | `count` | always `count` | **No** | `envelope_scoring` always false; count walk unchanged |
| R4 `charge:mono_averagine_guard` / `mono_averagine_select` | off | gone | **No** | `mono_guard_=0`, `mono_select_=false`; guard logic never triggered; the `!v.guard_stop && mono == leftmost_mz` condition in `monoPositionPass_` was always true at defaults |
| R4 `charge:mono_profile_check=true` (v1) | `v2` | only `false`/`v2` | **No** | v1 path removed; v2 is now the only non-false mode and was already the default |
| R5 `charge:mono_profile_check true` params | v2 default | gone | **No** | v1-specific params (`min_corr`, `max_dim`) only used when v1 was selected |
| R6 `charge:iso_partner=closest` | `first` | always `first` | **No** | `iso_closest_` always false; first-in-m/z path unchanged |
| R7 `assembly:cap_rank` | `corr_inten` (0) | always `evidence` (renamed 0) | **No** | `cap_rank_` always 0; ranking by score×intensity unchanged |
| R8 `assembly:fragment_fuse_mode=linkage` | `anchored` | always `anchored` | **No** | `fuse_linkage_` always false; anchored fusion unchanged |
| R9 `assembly:require_isotope_support`, `assembly:default_charge` | `true`, 2 | always drop, no default | **No** | At defaults, guessed precursors were always dropped; `monoPositionPass_` always saw `pc.charge==0` before and after (charge assignment moved but still happens after the v2 pass) |
| R10 `trace:split_scan_time=trace` | `frame` | always `frame` | **No** | `trace:split_scan_time` always `frame`; cycle time from run's frames unchanged |
| R11 `trace:mz_estimator=mean/median` | `apex` | always `apex` | **No** | `mzEstimator()` always `"apex"`; apex m/z unchanged |
| R12 `trace:band_edges=slab` | `acquisition` | always `acquisition` | **No** | At defaults, acquisition path was always used; error messages updated to match |
| R12 `DIASPEXTRACT_TILE_RESIDENT` | not set | gone | **No** | Only affected non-default `trace:band_edges=slab`; now that option is removed, the env var is unreachable |

**R4 deep dive**: The `!v.guard_stop && mono == leftmost_mz` guard in `monoPositionPass_` was removed. At defaults (`mono_guard_=0.0`, `mono_select_=false`), `v.guard_stop` is always false and the monoisotope equals the leftmost partner, so the condition was always true. Removal is a no-op at defaults.

**R9 deep dive**: Guessed precursors (`charge==0`) are still marked and dropped. `monoPositionPass_` is called **before** the `guessed` flag is set in both old and new code, and in both cases it sees `pc.charge==0` and skips them via `if (v.z <= 0 || pc.charge <= 0 || ...)`; the only change is that the obsolete `pc.charge = default_charge` assignment was removed, but it happened **after** `monoPositionPass_` anyway.

---

### Question 2: C3 refactors in d7dac2e

| Refactor | Change | Semantic impact |
|----------|--------|------------------|
| `toTrace`/`toTraceAt` merge | Unified with `makeSpan`, optional offset | **No** | Same Trace and arena bytes |
| `procKb_` consolidation | One `/proc` reader for RSS, VmSize, VmHWM | **No** | Only called on Linux; same values returned |
| `coRank_` reuse | Extracted from `parallelSortTotal_` | **No** | Same merge logic, just factored |
| Option mirrors initialized to registered defaults | Initial values match registered defaults | **No** | All mirrors are overwritten from options in `main_` before any use |
| M-11: `!streamed` blocks merged with `firstprivate(spicker)` | OpenMP scheduling cleanup | **No** | Same execution order |
| M-15: `lower_bound` | Replaced manual binary search | **No** | Same positions returned |
| M-17: post-load tdf retry loop removed | Preflight check suffices | **No** | At defaults, preflight check always ran; retry was unreachable |
| `taskErr_` consolidation | Replaced named criticals | **No** | Same exception propagation |

All C3 refactors preserve semantics; the commit message confirms "Spectra and spx: stamps are unchanged at every kept option."

---

### Question 3: Error and fallback paths

| Path | Old behavior | New behavior | Impact |
|------|--------------|--------------|--------|
| `trace:band_edges=slab` + streaming .d | Refused with suggestion | Unknown option error | **OK** – only reachable via removed option |
| `DIASPEXTRACT_TILE_RESIDENT=1` + streaming .d | Forced resident source | Ignored | **OK** – only reachable via removed env var |
| `trace:detector=integer` + missing GlobalMetadata | Refused with `trace:band_edges=slab` suggestion | Refused with `-trace:detector openms` suggestion | **OK** – error message updated to match new reality |
| `absorbAll_` serial branch | Threw via `TraceStore::absorb` | Removed (was unreachable) | **OK** – dead code; commit message confirms unreachable |
| M-17 post-load tdf retry | Second chance after failed preflight | Removed | **OK** – at defaults, preflight always ran and succeeded or fell back to openms |

**No new refusals or unintended runs found.** All removed fallback paths were only reachable through removed options or env vars.

---

### Question 4: Docs vs code

| Doc | Issue | Status |
|-----|-------|--------|
| `README.md` | Algorithm flow, requirements, options | **Fine** | Matches current code; references only public PXD accessions |
| `docs/options.md` | Complete option list with defaults | **Fine** | Accurate and complete for all kept options |
| `CHANGELOG.md v1.7.0` | Release notes | **BLOCKER** | In-house data references (see above) |
| `CONTRIBUTING.md` | Building, testing, reporting | **Fine** | No in-house data; accurate |

**Mermaid chart**: Stage order and numbers match the described pipeline (Read → Clean → Trace → Precursor → Check → Tile → Window → Frag → Gate → Spec → Fold → Out).

**Migrating section**: Accurately describes behavior for removed options (unknown-option error for CLI, unknown-parameter error for INI).

---

### Question 5: Public-text leaks

- **CHANGELOG.md**: **BLOCKER** – Multiple in-house dataset/cohort references (see Finding 1).
- **Other public files** (`README.md`, `docs/options.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`): **Clean** – No in-house data, diaTracer, K562, PXD041421, or cohort labels found.

---

### Question 6: CI, tests, and scripts

| File | Issue | Status |
|------|-------|--------|
| `.github/workflows/build.yml` | Updated option-token check description | **Fine** | Matches updated script behavior |
| `.github/workflows/tests.yml` | Updated option-token check description | **Fine** | Matches updated script behavior |
| `scripts/check_option_tokens.py` | Now checks README, CONTRIBUTING, docs/options.md; verifies all registered options are documented | **Fine** | Improvement; no regressions |
| `test/test_diaspextract.py` | Removed `-assembly:require_isotope_support true`, updated comments to remove "dataset D" | **Fine** | Accurate and functional |
| Removed bench scripts | Referenced in CHANGELOG | **Fine** | CHANGELOG correctly notes their removal |

**No broken references or silently skipped checks found.**

---

## **Final Answer**

### Ranked by severity

#### BLOCKER
1. **CHANGELOG.md contains in-house dataset references** – `CHANGELOG.md:95,1181,1234,1254,1256,1311-1314,1318,1326,1365-1370,1380,1386-1389,1401,1417,1432,1471,1496,1498,1516,1549,1591-1592` (and scattered earlier lines). Violates Invariant 5. **Must fix before release.**

#### SHOULD-FIX
2. **CHANGELOG.md:95 references private docs/BASELINE.md** – Should avoid naming private files in public text.
3. **CHANGELOG.md:1591-1592 reference single-cohort verification** – Should reword to avoid implying in-house-only validation.

#### NOTES (all fine)
- R1–R12 removals: **No behavioral change at defaults or under kept options.**
- C3 refactors: **No semantic change; spectra and spx: stamps confirmed unchanged.**
- Error/fallback paths: **No new refusals or unintended runs.**
- Docs (except CHANGELOG): **Accurate and consistent with code.**
- CI/tests: **Functional; no broken references.**

---
**Conclusion**: The only release-blocking issue is the in-house data leaks in CHANGELOG.md. All code changes preserve behavior at the defaults, and all other documentation is accurate. Fix CHANGELOG.md to remove "dataset A-F" and "cohort" references, then the release is sound.

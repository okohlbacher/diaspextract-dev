Reviewed `dde035e` against `1641a00`. The previous out-of-bounds seed-list write is closed. Six issues remain; none demonstrates a failure on the measured D run.

1. **Medium — The digitizer ceiling is not an absolute bound after m/z quantization.** [spextractor.cpp:4292](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4292), [conversion:990](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:990).

   A synthetic calibration accepted by `isSupported()` disproves the guarantee: `ModelType=1`, `C1=160000`, `DigitizerTimebase=0.0001`, `DigitizerDelay=25000`, with the other coefficients zero. Set `n_bins=1008`, lower m/z `100`, and upper m/z `100.00080560162249`.

   The raw last bin follows:
   ```text
   1007 → 100.00080560162249 m/z → quantized 100.00081
        → inverse TOF 1012.4979497 → bin 1012
   ```
   The unquantized upper conversion remains `1007`, so acquisition mode now throws at the superset check. `tofOf()` clamps only the lower end.

   **Fix:** derive a conservative metadata-only ceiling through the actual quantized endpoint conversion, or validate a sufficient calibration-resolution condition. This is a code-supported synthetic case, not an observed instrument failure.

2. **Medium — Finite upper m/z can still overflow conversion and silently collapse the band partition.** [spextractor.cpp:4291](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4291), [band construction:4583](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4583).

   The `n_bins ≤ 1e8` guard does not constrain `thi_mz`. With the D fixture calibration at reference temperature, `MzAcqRangeUpper=37272052327.068054` converts to exactly `UINT32_MAX`. This passes the metadata parser. Acquisition `thi` becomes `UINT32_MAX`, and both `thi−tlo+1` and `thi+1` wrap to zero. Every boundary becomes zero; containment passes, all seeds enter the last segment, and the detector treats that segment as unbanded.

   Larger finite values such as `1e100` also reach `llround` outside its representable domain—even during slab-mode diagnostic calculation.

   **Fix:** validate converted TOF before rounding/narrowing, require a representable exclusive upper endpoint, and calculate spans/endpoints in a wider type.

3. **Medium — The sample-count range check occurs after an unsafe cast.** [TdfLoad.h:56](/Users/kohlbach/Claude/speXtractor/src/TdfLoad.h:56).

   `DigitizerNumSamples="1e100"` passes the finite-number check, then `(long)v` invokes undefined behavior before the upper guard runs. `"634073.9"` silently becomes `634073`; `"100000000.9"` passes the stated ceiling through truncation.

   **Fix:** require `2 ≤ v ≤ 100000000` and `trunc(v) == v` before converting to `long`.

4. **Medium — mzPeak still refuses after loading and MS1 processing.** [spextractor.cpp:3335](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3335), [MzPeakStreamLoad.h:142](/Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:142).

   mzPeak bypasses preflight. When its calibration is usable but bounds are missing or malformed, metadata construction merely saves `bounds_why`. Decoding, picking, and MS1 processing proceed before the [acquisition guard](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4268) throws.

   **Fix:** validate acquisition requirements immediately after recovering mzPeak calibration metadata, before decoding. Keep this refusal outside the recoverable streaming-load fallback.

5. **Medium — Preflight can validate a different source from the selected calibration.** [spextractor.cpp:3343](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3343), [source selection:4155](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4155).

   Suppose `.d/analysis.tdf` has valid calibration but missing bounds, while the sidecar has valid bounds. Preflight succeeds on the sidecar; later initialization selects the first usable calibration—the `.d`—and acquisition mode refuses after loading.

   **Fix:** resolve the calibration source once and preflight the bounds belonging to that source.

6. **Low — Embedded NUL bypasses strict trailing-junk rejection.** [TdfLoad.h:45](/Users/kohlbach/Claude/speXtractor/src/TdfLoad.h:45).

   SQLite TEXT containing `1700\0junk` is accepted as `1700`: `strtod` stops at the embedded NUL, satisfying `*end == '\0'`.

   **Fix:** use `sqlite3_column_bytes()` and require parsing to consume the complete SQLite value.

What I checked and found sound:

- **Measured last-bin round trips:** D’s four golden frame temperatures recover bin `634072` after quantization; the tested SDK fixture extrema recover `636030`. The first review’s concrete SDK boundary case is fixed.
- **An empty upper tail:** a representable `thi_mz` above the digitizer ceiling is safe for containment. It can move interior edges and change seed ownership, so it is not necessarily output-neutral. That matches the specified partition.
- **Clamp versus detector range check:** for valid ordered boundaries, segmentation matches the detector’s half-open ranges and skips empty bands. Ordinary outliers encounter the unconditional containment check before segmentation; they cannot silently disappear through the clamp.
- **One-cell slab assertion:** it is tautological with ordinary slab-derived extremes. It becomes useful under acquisition bounds or a TileProbe override. Worker exceptions are captured and rethrown.
- **Parser basics:** `"634073"` converts exactly. NULL, ordinary junk, infinity, NaN, missing fields, and unordered bounds are refused. Duplicate rows cannot disguise a missing field because its zero default fails validation; the inspected vendor schema also makes `Key` a primary key.
- **Locale:** `"1700.000000"` works in the C locale. A comma locale would reject it, but I found no demonstrated CLI path changing `LC_NUMERIC`; environment locale settings alone do not establish that failure.
- **Provenance and concurrency:** explicit OpenMS and both integer fallbacks stamp `spx:band_edges=none`. Acquisition refuses the window-file override. Frozen factors remain read-only, distinct precreated window entries are written independently, and metadata is copied before temporary-file removal.

Validation: source review, in-memory numeric/parser probes, and passing `tests/test_calibration.py`. No C++ build or end-to-end extraction was run.

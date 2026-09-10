Adversarial review of 1641a00 (cell grid, step 3a: `trace:band_edges=slab|acquisition`),
2026-09-10, and of its fix-up dde035e (round 2: brief2.md, codex2.md, kimi2.md).

Round 1 (brief.md):
- codex.md -- Codex / GPT-6: "the calibration extremum is correct; the nominal acquisition
  ceiling is not a guaranteed peak-bin bound" -- a supported-calibration fixture where the last
  digitizer bin maps above the nominal MzAcqRangeUpper, so a frozen window could hold a valid peak
  above `thi`; with several cells the superset assert throws, with one cell `bandOf()` returned
  `nb` and wrote out of bounds (High). Medium: TEXT parsing of GlobalMetadata (NULL, "inf",
  "1700junk") reached `atof`; the refusal for missing metadata came after the whole load and MS1
  phase; a `SPEXTRACTOR_WINDOW_FILE` row could override acquisition edges under an
  `acquisition` stamp; the TNBC arm compared against a RECORDED slab arm from another binary;
  "within run-to-run spread" needs a number (the engines reproduce exactly, so any count change
  is a real spectrum change); the chain reports completion whatever failed and deletes the mzMLs
  before a per-spectrum diff could size the perturbation. Sound: the calibration direction
  (larger b, larger tof; max over the frozen table is the right extremum), tlo = 0, the mzPeak
  read before the temp file is removed, slab-mode identity, the 3b gap (the block still scans the
  slabs; the acquisition pair needs only the frozen tables and the axis).
- kimi.md -- Kimi Code: the same High (one-cell heap corruption / multi-cell late throw), the
  same refusal-timing and parsing points, the swallowed `why` at both read sites, the stamp
  recording the option rather than what ran (openms detector), "a few bins" stated as a
  property when it is a measurement on two files, the TNBC recorded arm not being a base, and an
  acceptance rule proposal (mechanistic bound first: logged thi pairs + specdiff; then entrapment
  <= same-build base + 0.3 on both acquisitions; engines within the same-build spread; set
  overlap with an alert below ~99%).
- vibe.md -- 0 bytes (documented cause).

Fix-up dde035e: `thi = max(DigitizerNumSamples - 1, the MzAcqRangeUpper conversion)` -- the
digitizer's sample count is an absolute bound on every bin index (D: 634,073, so thi 634,072 =
the value the science chain searched; TNBC: 399,967); `loadTdfAxisBounds` parses strictly with a
reason string logged on failure; acquisition mode refuses BEFORE the load when no candidate tdf
provides the bounds; `bandOf` clamps at both ends and the per-cell superset assert runs in every
mode; the stamp records what was applied; the window-file override is refused under
acquisition; the help text states the measured difference. Gate design: the follow-up chain
(chain_step3a_fu.sh) re-runs the TNBC slab control on the fixed build, keeps the D pair for
`mzml_specdiff.py`, and re-checks the acquisition arms' `[tof]` pairs and digests.

Round 2 (brief2.md, on dde035e):
- codex2.md -- Codex: "the previous out-of-bounds seed-list write is closed"; six remaining, none
  demonstrated on D: a coarse synthetic calibration whose quantised last bin lands one bin above
  the digitizer ceiling (now the ceiling is the quantised last bin per frame); a finite upper m/z
  converting to UINT32_MAX wrapped the partition (now `tofOf` saturates and the acquisition thi
  must be representable); the `(long)` cast before the range check; mzPeak refusing after the
  load (now the cached metadata sweep is consulted before any decode); the preflight validating a
  different tdf than the one later selected (now the preflight IS the selection: the first
  candidate whose calibration loads becomes the axis and must carry the bounds); an embedded NUL
  in a TEXT value (now the parse must consume `sqlite3_column_bytes`). Sound: D's four golden
  temperatures and the SDK fixture's extrema round-trip to the last bin; the clamp vs the
  detector's range test; the one-cell slab assert is tautological in slab mode; provenance and
  concurrency.
- kimi2.md -- Kimi: "the five claimed fixes all do what the commit message says, and the
  DigitizerNumSamples - 1 bound is genuinely absolute for vendor-origin peaks" (the 1e-5 Da quantum
  is ~500x finer than a bin, centroids cannot exceed the last bin's m/z); remaining: an
  unbounded `mz_hi` magnitude (now refused above 1e5 m/z, and `tofOf` saturates), the preflight's
  any-vs-first candidate semantics (now the preflight is the selection), the window-file conflict
  and the mzPeak refusal after the load (now both before), duplicate GlobalMetadata keys (now
  refused), hex/whitespace strtod nits (accepted), and the help text naming
  `-trace:detector openms` as the escape (added).

Gate: docs/BASELINE.md "Cell grid, step 3a".

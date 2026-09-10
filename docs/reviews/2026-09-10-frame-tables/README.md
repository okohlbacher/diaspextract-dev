Adversarial review of 38907fb (cell grid, step 1 (b): frozen frame tables from the readers'
metadata + lockstep padding), 2026-09-10. Brief: brief.md (nine attack lines).

- codex.md -- Codex / GPT-6 (gpt-6-astra): "no numerical change in the normal P=0 path"; two
  must-fix: (1) the new structural throws were `InvalidValue`, which the loader's recoverable
  catch swallows -- it would fall back to a full resident load ON TOP of the partial slabs and
  MS1 map (duplicated frames, non-monotonic RTs), and the post-load invariant ran inside the same
  try after `streamed = true`; (2) the lockstep matched on RT alone, so two table rows with one RT
  (an mzPeak archive without retention times defaults them to 0) could take a delivered frame for
  the wrong row with the invariant still passing. Should-fix: a resident mzML fallback kept the
  `loader` stamp; a delivered window absent from an enabled table bypassed enforcement; an mzPeak
  cache hit after a failed sweep of another archive left the "last" calibration accessors stale;
  the `number_of_peaks` diagnostic counted MS1 spectra. Notes: the duplicate-window-key throw is
  the explicit form of a pre-existing merge (windows are keyed by isolation m/z and group), and
  step 2 must handle a window with zero frames in a tile before the rebase (`slab_rt[0]`).
- kimi.md -- Kimi Code: the same must-fix (1) independently, with the mzML mis-stamp as its second
  mode; the `frame_id` half of the invariant; notes: the digest gate excludes the header (so the
  stamp change is not a regression), `trace:native_ms2_neighbors` is a streaming no-op (help text
  overstates), `get_frame` is a lookup (`frame_descs.at`), no first-touch race; mzPeak same-key
  windows merge in table and store alike; step 2 must either gate the tile loop on a non-slab
  table or build the group union for mzML; with `load_ms1 = false` the slab reservation degrades
  (perf only; the judged plan passes the tile's frozen count).
- vibe.md -- 0 bytes: the documented bash-permission cause (memory: adversarial-review-clis).

Fixes applied in a91cfcf: `FrameTableError` (fatal, rethrown past the fallback catch; the
invariant runs outside the try); the lockstep and the invariant use (rt, frame id); a delivered
key missing from an enabled table throws; `spx:frame_table` is assigned only after a successful
streamed load and invariant; a cache hit republishes `lastMzPeakExact()`/`lastMzPeakCalibration()`;
the diagnostic counts MS2 spectra lacking `number_of_peaks`.

Carried into step 2 (not fixed here): the zero-frame slab before the rebase (Codex 7); the
mzML union-or-refuse rule for the tile loop (Kimi 8); the pass-2 `expected_frames` (Kimi 9b, in
the judged plan).

Gate: docs/BASELINE.md "Cell grid, step 1: frozen frame tables".

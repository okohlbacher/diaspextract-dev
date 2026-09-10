• I'll work through this adversarial review. First, let me gather the commit, the contract, and the relevant code.

• Now let me examine the current state of the code at the key regions the attack targets.

• Now the tile loop and its per-iteration cleanup:

• Now let me verify the patch internals — the table export ordering, the time source for the filter, the num_peaks skip, and the batch loop's schedule:

• Let me check the gate script and a few remaining details — `cstat` usage, and whether the pass-1 `LOAD(stream)` phase timing is separate from per-tile `LOAD(tile)`:

• One ordering question: the `spx:tile_source` stamp is set *after* `writer->setExperimentalSettings(out_exp)`. Let me check TileWriter's semantics and that ordering:

• I have everything I need. All the load-bearing code paths are verified: the patch hunks, the consumer's lockstep/padding, pass 1, the tile loop, the writer, and the fallback. Here is the review.

  ---

  # Adversarial review — step 3b, the .d streaming source (HEAD 933bba5)

  ## Findings

  **1. MEDIUM-HIGH — the pass-1 fallback leaves `tile_source` set; the "graceful" fallback is broken for `.d`**
  `src/spextractor.cpp:3485-3489`. The recoverable catch around pass 1 logs "falling back to loadExperiment" but never resets `tile_source`. If the fallback load then succeeds, the run continues with `streamed == false` but `tile_source == true`: `run_tables` is empty (the invariant block at :3494 is skipped), so `frozen` is empty (:3636-3638), the RT axis is built from MS1 only (:3652-3653), `indexRt` then snaps every resident MS2 frame onto an MS1-only axis (:3667), `n_win`/`fkeys`/`wbands`/`visited` are all empty, and the tile loop calls `loadDIAStreaming` again per tile (:4502) with an empty `tablefn` — ending in either an uncaught loader throw after a full resident load, or a `std::out_of_range` from `frozen.at(wl[wi].first)` (:4654) / `wbands.at(...)` (:4674) inside an OMP task. None of these is the graceful resident run the fallback promises.
  Failure scenario: pass-1 `loadDIAStreaming` throws an OpenMS `BaseException` that the consumer, not the file, caused (e.g. `PeakPickerIM` rejecting a pathological MS1 spectrum in the streamed pick); `loadExperiment`'s non-streamed pick succeeds → corrupted configuration instead of a resident run.
  Fix: one line in the catch — `tile_source = false;` (the fallback *is* a resident whole-run source; everything downstream is then exactly the pre-3b path). Alternatively refuse, but resetting is free and matches the fallback's intent.

  **2. MEDIUM — the advertised `spx:tile_source` stamp never reaches the mzML header**
  `src/spextractor.cpp:4447` sets the stamp *after* `writer->setExperimentalSettings(out_exp)` at :4444. `PlainMSDataWritingConsumer::setExperimentalSettings` copies into `settings_`, and `TileWriter::writeBlock` serialises the header from that copy at first block (:1910), so the mutation at :4447 is invisible to the writer. Every mzML written under this commit — the streaming runs included — lacks the one stamp that would attribute the file to the tiled reader; mzPeak output gets it (bulk-written from `out_exp` at the end). Nothing caught it because e2e asserts on no such header key. This is precisely the silent-provenance class the stamp exists to prevent.
  Fix: move the `setMetaValue("spx:tile_source", ...)` up into the stamp block at :4400-4411, before the writer is constructed.

  **3. LOW — the parallelism log still reads `window_list`, which is empty under the streaming source**
  `src/spextractor.cpp:4186`: `" m/z bands = " + String((int)window_list.size() * n_bands) + " trace units"` prints `28 windows x 12 bands = 0 trace units` under the streaming source. The two sibling uses in the same message were converted to `n_win`; this one was missed. Cosmetic, but it is the line a scheduler diagnosis reads first.
  Fix: `n_win` here too.

  **4. LOW — the `trace:band_edges=slab` refusal fires after the two most expensive phases**
  `src/spextractor.cpp:4325-4327`. Reachable, yes — but only after pass 1 (full MS1 decode+pick) and the whole MS1 tracing phase (the process peak), because it sits in the `wbands` block. A user who pins `slab` on a 2-hour TNBC file learns of the refusal after the better part of an hour. The input type and `SPEXTRACTOR_TILE_RESIDENT` are both known before the load.
  Fix: hoist the refusal into the option-validation block at :3331-3362, next to the other `band_edges` checks (refuse in milliseconds).

  **5. LOW (latent) — absent windows are keyed differently between the two sources, so the A/B control can diverge on a sparse file**
  Under the streaming source, `frozen` comes from `run_tables` (:3636-3638) and includes a window whose frames all delivered nothing (every IM slice empty after picking — the "absent" count at :3501); under the resident control, `frozen` comes from `ms2_by_window` (:3640-3641) and excludes it. `n_bands = ceil(n_threads / n_win)` (:4155), `n_conc`, and the log then differ between the two builds' sources on the same file, and since each band has its own `visited`, a different `n_bands` is an output-moving difference — the `SPEXTRACTOR_TILE_RESIDENT=1` same-build control would not be identical for reasons having nothing to do with the reader. On the pinned files absent == 0, so the gate is unaffected; the first sparse dataset is where this bites.
  Fix: derive `frozen` from `run_tables` whenever they are non-empty (the resident streamed .d fills them too), or drop zero-delivered windows from `run_tables` under the streaming source — one definition of "the run's windows" for both modes.

  **6. LOW — the MS2 compact-store warnings are blind under the streaming source**
  `cstat` accumulates MS2 stats only during the per-tile reads (:4490), but both consumers of it run earlier: the `[compact] DROPPED … NOT lossless` warning at :3612-3619 (which under `tile_source` also prints the misleading "Split into MS1 + 0 windows … compact store 0 MB" at :3621-3624) and the `unmapped_frame` warning at :4229-4232. An MS2 peak drop or an unparseable nativeID now produces no warning at all. Relatedly, the plan's explicit "`fid == 0` in `flush_()` throws under the tiled readers" is not implemented; the effect is achieved indirectly (id 0 is never in the table, so the lockstep at :1679-1686 throws), with a less specific message.
  Fix: re-log both warnings after the tile loop (the counters are cumulative, so the totals are the whole run's).

  **7. LOW — gate-vs-plan deviation: no chained slab digests**
  The judged STEP 3b gate calls for `slabDigest_` to gain a seed so per-(window, tile) digests chain, and for "chained slab digests == the one-tile whole-window digests 24/24 and 28/28". The commit implements neither; the existing per-(window, tile) `[det]` digest (:4601-4605) cannot be compared to a whole-window digest (different frame sets). The chain you describe (final-file identity vs the flipped-default pins + e2e 18/18) is the stronger end-to-end check, but it is blind to a mid-pipeline divergence that cancels by export time, which is what the digest chain was for. The prefetch (step 5) and `[det]` chaining are legitimately later work; the digest line should either land here or be struck from the G1 wording so the gate's claim matches what was measured. Nothing else from the plan must be in this commit for the gate to be meaningful.

  ## Attack lines found sound

  - **Per-tile read exactness (attack 1).** The table is exported before the filter (patch :411-421 vs :454-460), and both the export and the filter read the same `handle->get_frame(fid).time` double that `spec.setRT(frame.time)` stamps (:516) — bitwise identical by construction, stable across re-opens (deterministic `atof` of unchanged sqlite text). Both range tests are the same half-open `[lo, hi)` on the same tile-bound doubles, so an MS2 frame landing exactly on a cell edge is still assigned to exactly one tile on both sides — the "no MS2 frame on an edge" assumption is not load-bearing. The selection preserves the group's frame order; decode is per-frame with the documented thread-local ZSTD pattern; hand-off is index-ordered within sequential batches, so `SPEXTRACTOR_LOAD_BATCH` and thread count change nothing emitted. `num_peaks == 0` frames are excluded from the table (:3452) and skipped before decode (patch :490) in both modes — no pads, consistent. Any residual mismatch is loud: lockstep throw (:1679-1686) plus the per-tile slab==table invariant (:4509-4510).
  - **Pass 1 (attack 2).** `lo = +inf, hi = -inf` selects no MS2 frame; `tables_` initialise in `flush_()` before the `n == 0` early return (:1607 vs :1609), so `finish()` populates them with zero MS2 frames; every window is absent, `run_tables` is copied, and the empty-table case refuses loudly (:3492-3493). `frozen` and the RT axis from the tables equal the resident slab-derived values given the pass-1 invariant and the measured 0 pads.
  - **`n_win`/`fkeys` (attack 3).** Apart from finding 3's log, every run-level structure (bands, carry, visited, coverage) is keyed on the frozen keys; the K > 1 resident slicing (:4524-4539) and the one-tile move (:4520) are unreachable under the streaming source (`else` arms).
  - **Per-tile consumer and memory (attack 4).** `ms1_none` is safe (`flushMS1_` no-ops; the `n_ms1 == 0` reserve fallback is unreachable because tables are always present under `tile_source`); `spicker` reuse is safe (Param deep-copied per flush, :1619); `tc.tablefn`'s by-reference capture of `tile` is alive for the whole iteration and invoked only within it; `tile_slabs`/`wl` are loop-local (:4480-4481) and the slabs are moved into the window body, so nothing accumulates across tiles; `indexRt` on an empty slab is a no-op (:949-956); the empty-slab body branch exists (:4657-4664) and `sliceFrames` is never called on this source. Per-tile handle re-open is the plan's accepted ~0.3-1 s, measured per call by `LOAD(tile)`.
  - **mzPeak (attack 5).** `tile_source` is false for mzPeak; `frozen` still comes from slabs, `run_tables` is filled but unused — no shared-code regression. `SPEXTRACTOR_TILE_RESIDENT` is undocumented, consistent with the other `SPEXTRACTOR_*` ponytails, but it should be named in BASELINE/docs as the A/B control since the gate now depends on it.
  - **Pass-2 failure handling (attack 6, partially).** The per-tile `loadDIAStreaming` at :4502 is correctly outside any catch — fatal, no half-read tile. Only the pass-1 side is broken (finding 1).
  - **Parallelism (attack 7).** `readTile` runs in the master's sequential region before the tile's `#pragma omp parallel` (:4482 vs :4543), so the loader's decode loop is never nested; it carries an explicit `schedule(dynamic, 1)` (patch :477), so the consumer's run-schedule static (:1623) cannot leak into it; `omp_set_max_active_levels(2)` (:4183) is irrelevant outside a parallel region. No hazard.

  **Verdict:** the exactness core — range selection, table export ordering, lockstep padding, per-tile invariant, frozen-keyed run structures — is sound and fails loud where it can fail at all. Finding 1 (fallback) should be fixed before this gate's results are trusted as a release basis, since it turns a designed robustness path into a corrupt-or-cryptic one; finding 2 makes the commit's own provenance stamp a lie of omission in the very files the gate produces. Findings 3-7 are small, but 5 deserves a line in the plan's open questions before the first sparse dataset arrives.


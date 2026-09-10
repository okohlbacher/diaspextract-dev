• I have the ledger and the allocation map. Now let me ground myself in the code and the measurement history before writing the review.

• The measurements and history are clear. Now I need the code grounded in detail before I can rank proposals. I'll dispatch four focused explorations in parallel.

• The four explorations converged. Before writing, let me verify the three load-bearing details my ranking hinges on.

• Two details to resolve: what the `scratch` ledger row actually charges during the MS1-only pass, and what the other `malloc_trim` sites are.

• One inconsistency to resolve: the ledger shows `scratch` at 3.4 GB during the MS1-only pass, but `flushMS1_` doesn't touch the scratch arrays. Let me check where `flush_` can run in pass 1.

• All four code explorations and the load-bearing details are verified. Two findings from my own checks before I write this up:

  - The ledger's `scratch` row (3.4–3.8 GB at the pass-1 peak) cannot be the MS2 pick scratch on the stream arms — no MS2 flows in pass 1 (`dia_ms2_rt_lo=+inf`, patch filter at line 460 of the calibration patch; `flush_` only sizes scratch). The number matches the 256-frame MS1 staging buffer `ms1_buf_` (256 × ~690k raw peaks × 20 B ≈ 3.5 GB), which is **uncharged** in the current source — a ledger attribution gap at the exact process peak.
  - The ~18–20 GB `free` that persists through every tile phase is glibc arena retention: the MS1 map's per-frame peak vectors (~11 MB each) sit under glibc's 32 MB dynamic mmap cap, so the 13.8 GB freed during MS1_TRACE never leaves the arenas. The existing `malloc_trim` at :4201 runs and the free column doesn't move — more trims will not fix this; only changing the allocation shape will.

  Now I'll write the review.

• Review written to `docs/reviews/2026-09-10-streaming-memory/kimi.md`. The summary:

  **The headline.** On both acquisitions the process peak is no longer the MS2 side. On D, both tiled stream arms peak at 31.8 GB at t ≈ 9 s in pass 1, before any MS2 is read; the tiled loop tops out at 23.5 GB. On TNBC, 1 tile vs 13 tiles gives 124.1 vs 125.0 GB — thirteen-fold tiling moved the peak by +0.9 GB. The MS2 program has hit its floor; what remains is pass 1 and the allocator.

  **Three findings the ledger supports but nobody had named:**

  1. **~10.7 GB is live-but-uncharged at the exact peak instant** (t ≈ 9.5 s: charged 13.9, RSS 30.9, glibc free only 6.3). Worse, the ledger's "scratch" row there cannot be the MS2 pick scratch — no MS2 flows in pass 1 (`flush_` never runs; the loader filters all MS2 at patch :460). The number matches the 256-frame MS1 staging buffer `ms1_buf_` (~3.5 GB), which is uncharged in the current source. The ledger is most misleading exactly where it matters most; charge `ms1_buf_`, the picker per-frame temporaries, and decode staging first.
  2. **The 18–20 GB "freed but retained" floor under every tile phase is the MS1 map's allocation shape.** Its 1,343 per-frame peak vectors (~11 MB each) sit under glibc's 32 MB mmap cap, so `s.clear(true)` at :2430 returns them to arenas, not the kernel — fragmented off the heap tops, which is why the existing `malloc_trim` at :4201 runs and the free column doesn't move. More trims will not fix this (the 64 kB mmap-threshold experiment already measured −15.5 GB for +26% wall). The fix is a **flat pooled MS1 store, 16 B/peak, with progressive `madvise` free during band distribution** — output-identical, −2.8 GB pass-1 bytes, and the retained floor actually leaves the process. tcmalloc's measured −7% peak corroborates.
  3. **The carry-independence claim survives code inspection.** A cell's detection reads only its slab slice, frozen tables, metadata band edges, and user constants — `ms2_noise` is a constant, no run-level noise estimation exists. The decisive experiment is cheap: re-detect tile k's last cell in tile k+1 and byte-diff the reconstructed carry against the handed one. It buys back the measured +27% loop-wall tiling penalty and ~30% pool idle (loop parallelism 44x vs 63x at 1 tile), at +17% detection CPU that lands in currently-idle pool capacity.

  **Ranked build order** (all D-class unless noted): ① ledger attribution fix (hours); ② density-balanced tile grouping from the frame table's `num_peaks` — the grouping loop at :4423 is ~10 lines, output invariant by digest, −30% densest-tile charged, worth ~0 today but it binds the moment pass 1 drops; ③ pooled MS1 store — the only item that lowers today's peak; ④ prefetch read(k+1) with a ~24-thread reader team, per-consumer stats (`stats_ +=` at :1749 races), and admission charged for prefetched slabs — hides 8% (D) / ~20% (TNBC); ⑤ `buildFragStats` in offset order — it sweeps the 336 MB window arena randomly per window because the :5085 sort never rebases `off`; ⑥ carry reconstruction → 2-tile overlap, gated on the byte-diff and a loop wall/CPU ratio ≥ 1.15x. S-class sequels if still bound: 10 B/peak quantised MS1 store (−6.5 GB D, −15–20 GB TNBC), 8 B/peak packed slab word `(tof:20|imq:12)` (sort-order preserved, one fewer prefetch stream in `best()`).

  **Orchestrator shape:** stage-separated threads with explicit team budgets (reader ~24, writer ~8–16, compute keeps its single region) over one global priority pool — the reader/writer are `parallel for` phases and nesting them invites the libgomp taskloop cliff. Ordered write via an in-order drain buffer of finished tile blocks; part-files or out-of-order append break native-ID numbering for no measured need. Explicitly not proposed: tiling the MS1 tracing pass (S-class, real carry-correctness surface — only if TNBC still binds after the 10 B store), and everything the reverted-attempts list already refuted.


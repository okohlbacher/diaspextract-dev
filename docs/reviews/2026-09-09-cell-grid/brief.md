Review only -- do not modify any file. Repository: /Users/kohlbach/Claude/speXtractor, HEAD is 8779a0b (clean).
Scope: the changes of commit 8779a0b (`git show 8779a0b -- src/spextractor.cpp`), plus the design they implement:
docs/reviews/2026-09-09-bounded-parents-design/judge.md (the "cell-atomic grid"; read its Recommendation and
Bound sections) and the measurements behind it in docs/BASELINE.md ("tiling plan step 1", "cause 2 vs cause 3").

Domain: SpeXtractor turns diaPASEF raw data into pseudo-MS/MS spectra; per isolation window the integer
detector (detectTracesInteger_) traces peaks over RT frames (seeds by intensity per tof band, extension both
ways with a running centroid/sd, 'visited' claims, unbounded in RT), then ElutionPeakDetection splits parents
at valleys (parent-global decisions), trimToSpan trims to 120 s, and precursors are scored against the
window's fragments within gate:delta_rt. The goal: process the run in RT tiles with output that is
BIT-IDENTICAL however the run is tiled. The measured fact: any cut changes ~41% of parents (detection) and
~half of all fragments, uniformly in RT, so a halo cannot give invariance.

The change under review (step 2 of the design): detection runs per fixed RT CELL. Cell edges are the run's
MS1 frame times every round(pitch / cycle) frames (tile:rt_sec; -1 = one cell = the previous code path,
which must be byte-identical); a window's frames are cut at those edges (frame_rt lower_bound); each cell is
traced on a slice of the window's PeakSlab (sliceFrames: frame_off rebased, rt_index, b, tof, inten, imq);
prepareTracing and the banded detectTracesInteger_ run per cell on the slice with the WINDOW's band edges
(tlo/thi from the whole slab); every cell's band stores are absorbed into the window store afterwards in
(cell, band) order with t.off rebased by absorb() and t.frame0 / t.bframe rebased by the cell's first frame;
splitting (per parent), trimming and scoring stay per window. The header gets spx:tile_rt_sec and
spx:tile_boundaries. Tiled execution (reader per tile, delta_rt carry-over of boundary children, the frozen
frame table) is NOT in this commit; the exactness gate uses the existing RT-range probe (TileProbe: MS2
frames outside [lo, hi] dropped after picking, core precursors only, frozen tof edges and G from a window
file) with cell-aligned ranges and halo 0: a core cell traced with complete neighbour cells must be
byte-identical to the same cell in the whole run at the same pitch.

Attack, in order of what I am least sure of:
1. Exactness: is a cell's detection output (parents: membership, off/frame0/bframe/apex/rt_at, IM, m/z,
   the band store contents) a pure function of the cell's slice, given that the tof band edges and
   the noise/snr are run-level? Look for anything in prepareTracing (~line 1046), buildTofIndex, and
   detectTracesInteger_ (~1098-1260) that depends on the slab as a whole rather than the slice: seed order
   ties (intensity desc, slab index desc -- the slab index is now cell-local), the tof index geometry
   (buildTofIndex derives bucket count from P/F of the SLICE: does that change any decision, or is it
   provably exact as its comment claims?), frame_live, the running sd initialisation, msr / min_len_sec
   in frames vs seconds, and rtAxis()/rt_index use. Give a concrete counterexample if any.
2. The rebase: is every store-local frame index in a Trace rebased (frame0, bframe -- what about apex, rt_at,
   and anything makeSpan/toTrace writes)? Are the arena offsets (off) and the per-frame bins (wst.bins,
   int16 offsets from t.tof) correct after absorb() in (cell, band) order? Would the ORDER of frag_traces
   differ from the one-cell order in a way that changes output (the canonical sort at the score stage,
   ties, the top-500 cap)? Is the '[det] frag traces' digest / slab digest still meaningful?
3. The identity arm: with tile:rt_sec=-1 (no edges), is the code path literally the same statements as
   before (no slice, same release_input timing before the merge, same merge log, same reserve)? Anything
   that could change bytes or the [mem] accounting?
4. The cell edges: edges at rts[n], rts[2n], ..., remainder < n/2 joins the last cell; frames assigned by
   lower_bound on frame_rt. Off-by-one at an edge (an MS2 frame exactly at an MS1 frame time cannot occur,
   but what if rt_index/frame_rt has duplicates or the window has no frame in a cell -> empty cell:
   f > cut.back() guard)? Does the probe's inclusive keepFrame [lo, hi] agree with the cells' half-open
   [T_k, T_{k+1})?
5. What the gate cannot see: after this commit, which parts of the judge's exactness bound are still
   unimplemented (frozen frame table / G / nearest_local, the delta_rt carry-over and precursor deferral for
   tiled scoring, pass 1 per cell), and does the probe-based gate (complete neighbour cells, MS1 whole-run)
   truly prove per-cell exactness or could it pass while tiled mode would still differ? Say precisely what
   a later tiled-reader implementation must preserve.
6. Cost: memory (all cells' band stores alive at the merge -- same as today's? the slice copy?), CPU (13 x
   prepareTracing / buildTofIndex per window), and the taskloop shape (12 band tasks per cell,
   sequential cells -- occupancy at 100 threads with 28 windows).

For each finding: severity (blocker / should-fix / note), file:line, a concrete scenario, and whether it
would bite on real data. If something is fine, say so in one line. Do not restate the design.

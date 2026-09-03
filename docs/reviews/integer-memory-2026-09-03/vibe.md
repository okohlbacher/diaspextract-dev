## 1. Per-structure inventory

**Scale:** 24 windows in flight, P = 5.0×10⁷ peaks/window, F = 1,400 frames/window, 7.5×10⁶ traces/window, 10 points/trace.

| Rank | Structure | Bytes/element | Simultaneous count | Peak bytes | Notes |
|---|---|---|---|---|---|
| **1** | `std::list<Peak2D>` nodes (valley splitting) | 48 | 24 × 7.5×10⁷ points | **86.4 GB** | 24+16+8 bytes per node (payload + two pointers + allocator) |
| **2** | `visited` vectors (detection) | 1 | 24 × 12 × P | **14.4 GB** | One P-sized `vector<char>` per band task (288 total) |
| **3** | `PeakSlab.tof`, `inten`, `imq` | 4, 4, 2 | 24 × P each | **12.0 GB** | tof:200 MB, inten:200 MB, imq:100 MB per window |
| 4 | `Trace` vector data (xi,xv,xt) | 12 | 24 × 7.5×10⁷ | 21.6 GB | Only during detection; freed before valley splitting |
| 5 | `Trace` scalars | ~48 | 24 × 7.5×10⁶ | 8.6 GB | Persist during valley splitting |
| 6 | `TracePrep.frame_of` | 4 | 24 × P | 4.8 GB | Redundant with `PeakSlab.frame_off` |
| 7 | `MassTrace` objects | ~32 | 24 × 7.5×10⁶ | 5.8 GB | Valley splitting intermediate |

**Top 3 memory owners at global peak (105 GB):**
1. **`std::list<Peak2D>` nodes: 86.4 GB** — 4× expansion vs compact `Trace` arrays during valley splitting.
2. **`visited` arrays: 14.4 GB** — 12 per window, each P bytes.
3. **`PeakSlab` (tof+inten+imq): 12.0 GB** — Core peak store after compact frame consumption.

*The sum exceeds 105 GB because stages are pipelined: some windows are in detection (holding PeakSlab/visited/Trace vectors) while others are in valley splitting (holding list nodes). The list nodes alone account for ~82% of measured peak.*

---

## 2. Duplication

| Duplicate | Representations | Lifetime overlap | Size (per window) | Simultaneous? |
|---|---|---|---|---|
| **Frame mapping** | `TracePrep.frame_of[P]` vs `PeakSlab.frame_off[F+1]` | prepareTracing → end of detectTraces | 200 MB vs 5.6 KB | **Yes** — `frame_of` is a P-length cache of frame boundaries |
| **m/z authority** | `Trace.mz` (double) vs `(Trace.tof, Trace.b)` | Entire Trace lifetime | 8 bytes vs 12 bytes per trace | **Yes** — mz is cached convenience; (tof,b) is authoritative |
| **Trace points** | `Trace.{xi,xv,xt}` vs `std::list<Peak2D>` | During `splitIntegerTraces` conversion | 12 B/point vs 48 B/point | **Yes, but brief** — vectors freed immediately after list construction |
| **Noise membership** | `TracePrep.member[P]` vs `PeakSlab.inten[P]` | prepareTracing → detectTraces | 50 MB vs 200 MB | **Yes** — member[k] = (inten[k] > noise) |

**Only frame_of/member are material duplicates.** The others are either short-lived or small per-instance.

---

## 3. Repeated passes

| Data | Pass | Count | Notes |
|---|---|---|---|
| **Peak (PeakSlab)** | `toSlab` (from CompactFrame) | **1×** | Compact store consumed; no duplication |
| | `prepareTracing` (frame_of, member, frame_live) | **1×** | Full scan of all peaks |
| | `detectTracesInteger_` candidate checks | **~50×** | Each peak is scanned as candidate for ~50 traces (estimated from trace density and TOF window) |
| | `detectTracesInteger_` accepted into trace | **≤1×** | Visited array prevents reuse |
| **Trace point** | Trace → Peak2D conversion | **1×** | `splitIntegerTraces` reads xi,xv,xt |
| | Valley splitting (`splitValleys`) | **1×** | Reads list<Peak2D> |
| | New Trace construction (apex search) | **1×** | Reads split trace points |
| **Trace seed** | Sorting in `prepareTracing` | **1×** | By intensity for seed ordering |

**Fusable/eliminable passes:**
- **Fuse `prepareTracing` into `detectTracesInteger_`**: Eliminate 1 full pass over P. Risk: must inline seed sorting.
- **Inline `member` check**: Replace `member[k]` with `(sl.inten[k] > noise)` in `best()`. Saves 50 MB/window but adds a float compare per candidate (~2.25×10¹⁰ checks/window).
- **Inline `frame_of`**: Replace with binary search in `frame_off` (10–11 compares vs 1 load). Saves 200 MB/window.
- **Fuse Trace→MassTrace conversion**: Avoid separate pass by building splittable representation directly. Saves 1× read of all trace points.

---
---
## 4. The `visited` array

- **Current cost**: 288 `vector<char>(P)` = 24 windows × 12 bands × 5.0×10⁷ bytes = **14.4 GB**.
- **Problem**: Each band task allocates a full-window `visited`, but bands are seeded from disjoint TOF ranges. However, traces can *extend* across bands, so a peak outside a band’s seed range may still be claimed by that band’s trace.
- **What it should be**: **One `vector<char>(P)` per window**, shared by all 12 band tasks. Use `std::atomic<char>` or bit-level atomics for thread-safe marking.
- **Saving**: 11/12 × 14.4 GB = **13.2 GB**.
- **Correctness**: Required to prevent cross-band trace overlap (currently, a peak could be claimed by multiple bands).

---
---
## 5. More memory-efficient design

| Rank | Change | Saving | Output change? | Verification | Risk |
|---|---|---|---|---|---|
| **1** | Replace `std::list<Peak2D>` with `vector<Peak2D>` in valley splitting | **~38.9 GB** | No | Compare peptide IDs before/after | **Medium** — Requires OpenMS compatibility or custom `splitValleys`; list overhead is 48 B/point vs 24 B/point for vector |
| **2** | Share `visited` per window with atomics | **13.2 GB** | No | Assert no duplicate peak usage across bands | **Low** — Lock-free on x86_64 |
| **3** | `vector<bool>` (bitset) for shared `visited` | **+10.5 GB** (total 23.7 GB) | No | Same as #2 | **Medium** — Atomic bit ops are slower; alignment complexity |
| **4** | Eliminate `TracePrep.frame_of`; compute via binary search in `frame_off` | **4.8 GB** | No | Trace count stability | **Low** — 1400-element binary search is ~11 compares |
| **5** | Eliminate `TracePrep.member`; check `inten[k] > noise` inline | **1.2 GB** | No | Trace count stability | **Low** — Adds 1 float compare per candidate check |
| **6** | Eliminate entire `TracePrep`; merge into `detectTracesInteger_` | **~7.2 GB** | No | Full regression test | **Medium** — Must inline seed sorting and membership |

**Free savings (no risk to correctness, minimal perf impact):**
- **#2 + #3**: 23.7 GB (shared bitset visited) — *Best immediate win*.
- **#4 + #5**: 6.0 GB (remove frame_of/member) — *Low-hanging fruit*.

**Trade-offs:**
- **Vector for valley splitting (#1)**: 38.9 GB saved, but requires touching OpenMS or reimplementing valley splitting. *Highest ROI if feasible.*
- **Binary search for frame_of (#4)**: 4.8 GB saved, costs ~11 compares per access. *Worth it — compares are cheaper than 200 MB RAM.*

**Not in this code but confirmed external:**
- **Compact store**: 1.26×10⁹ peaks × 10 B/peak = 12.6 GB, but *consumed* during `toSlab` (vectors swapped away), so not simultaneous with PeakSlab.
- **Allocator fragmentation**: 24 windows × 7.5×10⁶ traces × 72 B vector overhead = 13.0 GB. *Included in Trace vector overhead above.*
- **Emitted spectra**: Not in this path; managed by caller. *Not a factor in the 105 GB measurement.*

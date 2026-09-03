## 1. Per-structure inventory

I use decimal GB, matching the table. Assumptions: LP64, `TofIdx = uint32_t`, `sizeof(std::vector)=24`, `sizeof(pair<int,float>)=8`, `sizeof(Trace)=120`. The supplied information does not define `sizeof(MassTrace)`, the seed count, maximum trace length, allocator size classes, or actual phase overlap. Those cannot honestly be given as exact constants.

Let:

- \(P=5\times10^7\) raw peaks/window.
- \(T=5\times10^6\)–\(10^7\) traces/window.
- \(Q=10T=5\times10^7\)–\(10^8\) trace points/window.
- 24 live windows.
- 12 concurrent band detectors/window: 288 band tasks.
- 48 EPD chunks/window: 1,152 chunk tasks, but they partition \(T\) and \(Q\); they do not multiply them by 48.

### PeakSlab and compact input

| Structure | Bytes/element | Count at 24-window scale | Bytes |
|---|---:|---:|---:|
| `PeakSlab::tof` | 4 | \(24P=1.2\times10^9\) | 4.8 GB |
| `PeakSlab::inten` | 4 | \(24P\) | 4.8 GB |
| `PeakSlab::imq` | 2 | \(24P\) | 2.4 GB |
| `frame_off` | 4 | ~33,624 | 0.00013 GB |
| `rt_index` | 4 | ~33,600 | 0.00013 GB |
| `b` | 8 | ~33,600 | 0.00027 GB |
| Full slabs | 10/peak | \(24P\) | **12.0 GB** |
| Original compact store | 10/peak | 1.26 billion total | **12.6 GB** |

The claim that consuming frames avoids slab/input duplication is only partly true. All three slab peak arrays are reserved at full size before any `CompactFrame` is released. Therefore allocated capacity can briefly be:

- compact input: 500 MB/window;
- reserved slab: 500 MB/window;
- total: **1.0 GB/window, 24.0 GB for 24 windows**.

Untouched reserved pages may not all enter RSS, but allocator page reuse/retention may make much of this visible. Logically, after each source frame is swapped away, that frame is no longer represented twice.

### TracePrep

| Structure | Bytes/element | Per window | 24 windows |
|---|---:|---:|---:|
| `frame_of` | 4 | 200 MB | **4.8 GB** |
| `member` | 1 | 50 MB | **1.2 GB** |
| `frame_live` | 1 | ~1.4 KB | negligible |
| `order` at initial `P/4` capacity | 4 | 50 MB | **1.2 GB** |
| `order` worst case, all peaks seeds | 4 | 200 MB | **4.8 GB** |

Consequently `PeakSlab + TracePrep` is at least **19.2 GB** at the reserved `P/4` order size, or **22.8 GB** if almost all peaks qualify as seeds.

Sorting may transiently coexist with an old vector allocation only when `order` grows beyond capacity; its capacity and peak reallocations are implementation-dependent.

### `visited`

Each band allocates one byte for every peak in the entire window:

- 50 MB/band;
- 12 bands/window: 600 MB/window;
- 24 windows: **14.4 GB**.

There are **288 separate arrays**, holding 12 independent visitation states for each window.

### Detected `Trace` objects and profiles

`Trace` is 120 bytes:

- scalar portion including padding: 48 bytes;
- three vector objects: 72 bytes.

Profiles cost 12 bytes/point:

- `xi`: 4;
- `xv`: 4;
- `xt`: 4.

At ten points/trace:

| Component | Per trace | 24-window total |
|---|---:|---:|
| `Trace` objects | 120 B | 14.4–28.8 GB |
| Profile payload | 120 B | 14.4–28.8 GB |
| Logical total | 240 B | **28.8–57.6 GB** |

That excludes:

- three heap allocations per trace;
- allocator metadata and size-class rounding;
- unused vector capacity;
- slack in the outer `vector<Trace>`.

At even 16 bytes of allocator overhead per profile allocation, the three small vectors add another:

- 48 B/trace;
- **5.76–11.52 GB** across 24 windows.

This code creates **360–720 million small profile allocations**. Fragmentation is not a footnote; it can readily account for multiple GB.

Because `out` is not reserved, its `Trace` object buffer normally has 1–2 times the used capacity. The unused capacity can add as much as another **14.4–28.8 GB**, with a brief old-buffer/new-buffer overlap during growth.

### EPD conversion

A list node is given as:

- `Peak2D`: 24 B;
- two pointers: 16 B;
- allocator overhead: 8 B;
- total: **48 B/node**.

But the accounting in the code is false: `list_bytes` accumulates the sizes of every list ever constructed, while each `pk` is destroyed at the end of its loop iteration. At most one `pk` exists per EPD chunk.

With 1,152 concurrent chunks and ten-point traces:

- live list nodes at the average trace length: \(1,152\times10\times48\);
- only **0.553 MB**.

The actual upper bound is `1,152 × maximum_trace_length × 48`, not `48Q`. The `MemGuard` reports **2.4–4.8 GB/window of phantom list memory** that is no longer live when the guard is constructed.

The real EPD storage is the `MassTrace` vector payload:

| Representation | Point bytes | 24-window total |
|---|---:|---:|
| Input `mts` Peak2D payload | 24 | **28.8–57.6 GB** |
| Returned `split` Peak2D payload | another 24 | **another 28.8–57.6 GB** |
| Post-split `Trace` profile, likely `xi+xv` only | 8 | **9.6–19.2 GB** |

`mts` and `split` are simultaneously alive after `splitValleys` returns. While `toTrace` builds the output, all three representations can coexist within each completed chunk:

- 24 + 24 + 8 = **56 bytes/point**;
- **67.2–134.4 GB** over all 24 windows, before object headers.

This alone can explain a 105 GB peak if only part of the nominal concurrency has reached that phase.

`MassTrace` headers add `H_MT × number_of_traces` for each generation. The message does not define `H_MT`. Its lower bound is 24 bytes merely for its vector. If it is 64 bytes, one generation costs:

- **7.68–15.36 GB** across 24 windows;

and two generations cost twice that. Reporting an exact number without the class definition would be fabrication.

### EPD support objects

| Structure | Count | Approximate bytes |
|---|---:|---:|
| `parts` vector headers | \(24\times48\) | 27.6 KB |
| `mts` outer arrays | total \(T\), partitioned among chunks | `H_MT × 120–240m` |
| `split` outer arrays | approximately total \(T\) | another `H_MT × 120–240m` |
| `b_of_rt` | 24 maps × ~1,400 entries | roughly 1–2 MB total |
| `got` | one per band task | `288 × 4 × max_trace_length` |
| `pts` | one per band task | `288 × 8 × max_trace_length` |

The 48 chunks increase concurrent allocators and temporary vectors, but not the aggregate point count by 48.

### FragGrid

This is the largest red flag.

For 5–10 million fragments and approximately 510 support points/fragment:

| Structure | Bytes/element | Per window | 24-window hypothetical |
|---|---:|---:|---:|
| `flat` | 8 | **20.4–40.8 GB** | **489.6–979.2 GB** |
| `off` | 8/fragment | 40–80 MB | 0.96–1.92 GB |
| `mean` | 8/fragment | 40–80 MB | 0.96–1.92 GB |
| `invnorm` | 8/fragment | 40–80 MB | 0.96–1.92 GB |
| `slot_of_frame` | 4 × 33,553 | 0.134 MB | 3.22 MB |
| `nearest_slot` | same | 0.134 MB | 3.22 MB |
| `rt` | roughly 8 × 1,400 | 0.011 MB | 0.27 MB |

The measured 105 GB proves that 24 such `flat` arrays are not simultaneously resident. Even ignoring every other allocation:

- at 5 million fragments, at most five grids fit in 105 GB;
- at 10 million, at most two;
- at the cited 8.5 million, one `flat` is 34.68 GB, so at most three fit.

“In flight” therefore does not mean “all 24 are simultaneously at the FragGrid phase,” or `flat` is constructed differently from what its comment says. The missing call site prevents resolving which.

### Ranking

There are two plausible peak phases.

At detection:

1. `Trace` objects, profile allocations, and allocator fragmentation: **28.8–57.6 GB logical**, plausibly much more with headers, capacity, and allocator overhead.
2. `PeakSlab + TracePrep`: **19.2–22.8 GB**.
3. Per-band `visited`: **14.4 GB**.

At valley splitting/grid construction:

1. `FragGrid::flat`: **20.4–40.8 GB per live grid**.
2. Simultaneous input/output `MassTrace::Peak2D` payload: up to **57.6–115.2 GB** at full 24-window concurrency.
3. `Trace` headers/profiles and their allocator overhead: **28.8–57.6+ GB**.

The code does not establish which phase produced the measured peak. Phase-tagged RSS or heap profiling is required before claiming that `visited` is the principal owner.

## 2. Duplication

### Genuinely simultaneous

- Compact input and slab capacity: all 500 MB/window of slab capacity is reserved while the 500 MB/window compact input still exists. Physical RSS overlap depends on page touching.
- Slab and `frame_of`: `frame_off` already encodes the peak-to-frame relationship; `frame_of` materialises it again at 4 bytes/peak. They coexist for all tracing: **4.8 GB duplicated metadata** across 24 windows.
- Slab intensity and `member`: `member` is a one-byte threshold result derived from `inten`; they coexist: **1.2 GB**.
- Slab intensity/member and `order`: `order` is another materialised selection of qualifying peaks: **1.2–4.8 GB**.
- Slab and detected profiles:
  - `Trace::xi` duplicates frame identity/RT indexing;
  - `Trace::xv` duplicates slab intensity;
  - `Trace::xt` duplicates slab TOF.
  
  The slab remains alive because EPD receives `sl`, so the full 12-byte trace profile duplicates data still available from slab indices: **14.4–28.8 GB**.
- `Trace::mz` and `tof+b`: two representations of the trace m/z coexist for every trace.
- `b_of_rt` duplicates the `rt_index → b` association already in the slab. It is tiny, roughly tens of KB/window.
- During EPD conversion, already converted traces exist as `MassTrace/Peak2D`, while unconverted traces still have their original profiles.
- After `splitValleys`, both `mts` and `split` are live: a genuine, chunk-wide duplication of up to **48 bytes/original point**.
- During `toTrace`, input `mts`, output `split`, and the growing compact `Trace` representation coexist: approximately **56 bytes/point**, excluding headers.
- If `FragGrid` is built before traces are freed, `flat` duplicates/interpolates trace profiles and adds **20.4–40.8 GB per window**.

### Not simultaneously live in the claimed volume

- The complete compact frame vectors and complete filled slab are not logically live together. Source frames are released as the slab fills. The full-capacity reservation is simultaneous, but not two complete sets of populated elements.
- The accumulated `list_bytes` value is not live list memory. Only the current trace's list survives in each chunk.
- For a particular trace, its original profile is freed immediately after its `MassTrace` is constructed. There is only a short one-trace overlap, not a whole-chunk `Trace profile + MassTrace` duplication.
- Original compact frames for a window are gone before its traces are detected. They do not coexist with that window's trace output, although unprocessed windows’ compact frames can coexist with processed windows’ slabs/traces.

## 3. Repeated passes

There is no single fixed “reads per peak” count. Sorting and candidate searches are data-dependent, and the code that builds `FragGrid`, scores precursors, and emits spectra is absent.

### Raw/slab peaks

For every compact peak:

1. `toSlab` reads `mzq` once.
2. It reads/copies `inten` once.
3. It reads/copies `imq` once.

For every slab peak during preparation:

4. `prepareTracing` reads intensity once in the frame traversal.
5. It reads `member` once in the order-building pass.
6. For members, it reads intensity again to test `min_apex`.

For each seed:

7. Sorting reads its intensity repeatedly: approximately \(2C\) intensity reads for \(C\) comparator calls. For comparison sorting, \(C\) is typically \(O(S\log S)\), not one pass.
8. Every one of the 12 band tasks scans the entire `tp.order`. Thus each seed index and its TOF are read **12 times just to discover that 11 bands do not own it**.
9. Its owning band reads `visited`, frame, intensity, mobility and m/z-related fields during tracing.

Candidate-window reads are not bounded by a constant. A slab peak can be examined by many trace extensions:

- `tof` is read in binary search and range traversal;
- `member` is read for every candidate;
- `imq` is read for every above-noise candidate;
- m/z calibration is performed for every mobility-acceptable candidate;
- `visited` is tested for the selected winner.

Across independent bands, the same extension peak may be examined—and even used—by multiple band traces because visitation is not shared.

### Accepted trace points

After a point has been accepted:

1. It is recorded in `got`.
2. `got` is traversed once to compute `fmin/fmax`.
3. Valid traces traverse it again to mark `visited`.
4. It is traversed again to build `pts`.
5. `pts` is sorted, adding \(O(L\log L)\) pair reads for length \(L\).
6. `pts` is traversed to populate `xi/xv/xt` and find the apex.
7. EPD traverses `xi/xv/xt` to create `Peak2D` list nodes.
8. `MassTrace(pk)` traverses/copies the list into its vector.
9. `splitValleys` makes an unknown number of passes; its implementation is not supplied.
10. `toTrace(mt)` traverses the split `MassTrace`.
11. The resulting trace is traversed again to find its apex.
12. FragGrid construction, correlation/scoring, and emitted-spectrum construction add unknown passes because their code is absent.

So an accepted point gets at least **eight explicit post-acceptance traversals/copies outside `splitValleys` and FragGrid**, depending on whether marking and sorting comparisons are counted as point reads.

### Passes that should be fused or eliminated

- Partition `tp.order` into 12 band-specific seed lists once. That replaces 12 full order scans with one partitioning pass plus one local scan: approximately an **11/12 reduction in seed-dispatch reads**.
- Compute `fmin/fmax` while accepting points. Eliminate the later validation traversal.
- Keep downward and upward hits separately in frame order. Reverse the downward list and concatenate it with seed/upward hits. This eliminates `pts` construction and its \(O(L\log L)\) sort.
- Build `MassTrace`’s vector directly. Eliminate list construction and list-to-vector copying.
- Find the post-split apex inside `toTrace`. Eliminate one full profile pass.
- The important option is to run valley splitting directly on `Trace` arrays. That removes both representation conversions and most of the EPD peak copying.

An exact count “to emitted spectrum” is impossible from this excerpt because the grid builder, scoring, and emitter are not present.

## 4. The `visited` array

Current cost:

- \(P=50,000,000\) bytes = **50 MB per band**;
- 12 bands = **600 MB/window**;
- 24 windows = **14.4 GB**;
- 288 allocations total.

It cannot simply be resized to the band’s core. Seeds are core-local, but extension candidates can lie anywhere in the window. A core-only array would either index out of bounds or fail to record extension peaks.

The low-risk replacement is a whole-window bitset:

- \(P/8=6.25\) MB/band;
- 75 MB/window;
- 1.8 GB for 24 windows;
- saving: **12.6 GB**, exactly 87.5%.

A byte is being used to store one bit of state. That is indefensible at this concurrency.

Alternatives:

- A sparse visited set keyed by global peak index is correct, but `unordered_set<uint32_t>` would commonly cost 16–32 bytes/visited peak and become worse than the current array once a few percent of peaks are claimed.
- Roaring/compressed bitmaps may win for very sparse visits, but their crossover and lookup cost must be measured.
- One shared global bitset would save more but changes semantics: bands would race and suppress each other’s traces. That can change output and make it schedule-dependent.
- A dense bitset over only above-noise members requires a global-peak-to-member-rank mapping. If that mapping is 32 bits/peak, it loses more memory than the bitset saves.

Use 64-bit bit words local to each band. No atomics are required because each band owns its bitset.

## 5. A more memory-efficient design

Ranked primarily by expected bytes saved relative to implementation/output risk.

### 1. Batch or lazily generate `FragGrid::flat`

Change: score fragments in bounded batches rather than materialising all ~510 interpolated support points for every fragment. A 100,000-fragment batch contains about 51 million pairs:

- 408 MB batch `flat`;
- versus 20.4–40.8 GB/window today;
- saving **approximately 20–40 GB per live window**.

If three grids currently overlap, that is roughly **60–120 GB of avoided potential residency**.

Output: no change if interpolation, means, norms, and accumulation order are reproduced exactly. Changing floating-point reduction order could introduce last-bit changes and must be controlled.

Cost: may trade memory for time if support values are regenerated or downstream consumers require multiple passes. A producer/consumer pipeline can avoid most of that cost.

Verify:

- hash `(fragment, slot, float-bit-pattern)` tuples from batched and existing grids;
- compare `mean` and `invnorm` bitwise;
- compare identified-peptide spectra peak-for-peak;
- measure phase-tagged RSS at batch sizes 25k, 50k, 100k, and 250k.

### 2. Replace per-trace vectors with arena-backed profiles

Change: store all `xi`, `xv`, and `xt` values in contiguous arenas, with each trace holding offsets and lengths instead of three `std::vector` objects.

Direct header saving:

- remove roughly 72 bytes of vector headers;
- replace with perhaps 16 bytes of offsets/lengths;
- net at least 56 bytes/trace;
- across 120–240 million traces: **6.72–13.44 GB**.

Avoiding three small-allocation headers at an assumed 16 bytes each saves another:

- **5.76–11.52 GB**.

Combined plausible saving: **12.5–25 GB**, plus reduced fragmentation and better locality.

Output: no algorithmic change.

Cost: moderate implementation risk because moves, splitting, and lifetime management change. It should improve time rather than cost time.

Verify:

- exact hashes of every trace scalar and profile tuple before EPD;
- allocator profile showing the disappearance of 360–720 million allocations;
- RSS and wall-time comparison at identical OpenMP scheduling.

### 3. Split valleys directly on integer `Trace` profiles

Change: port the valley finder to `xi/xv/xt` or expose a span-based interface, avoiding `list<Peak2D>`, input `MassTrace`, returned `MassTrace`, and `toTrace`.

At the worst conversion point, current representations use roughly:

- 24 B input Peak2D;
- 24 B split Peak2D;
- 8 B output profile;
- total 56 B/point, excluding headers.

A destructive/span implementation should need roughly 8–16 B/point. Saving is approximately **40 B/point**:

- 2.0–4.0 GB/window;
- **48–96 GB** if all 24 windows reach the phase;
- actual saving is capped by the observed overlap and 105 GB total RSS.

Output: this is the highest semantic-risk change. Reimplementing OpenMS valley decisions can change split positions and therefore identified-peptide spectra.

Cost: likely improves both memory and time, but development/validation risk is substantial.

Verify:

- differential tests against `splitValleys` for every trace;
- exact split count and boundary comparison;
- exact output comparison for identified peptides;
- targeted cases for equal intensities, flat valleys, two-point traces, and RT gaps.

### 4. Bit-pack `visited`

Change: `vector<uint64_t>` or an equivalent bitset covering all global peak indices.

Saving:

- current: 14.4 GB;
- replacement: 1.8 GB;
- net: **12.6 GB**.

Output: none. Each band retains independent visitation semantics.

Cost: effectively free in memory terms. It may be faster because 8× less data enters cache, though bit operations add a few instructions.

Verify:

- trace membership hashes before valley splitting;
- identified-peptide spectrum equality;
- thread-sanitizer testing to ensure the implementation remains task-local.

### 5. Reuse or compress `Trace` profile fields

Change A: use `uint16_t` TOF deltas relative to the trace/apex TOF with an overflow escape representation.

Saving from `xt`:

- 2 B/point;
- **2.4–4.8 GB** across 24 windows.

Output: none if overflow is exact and reconstruction returns the original bin.

Change B: free `xt` immediately after valley splitting. The shown code appears to do this indirectly if `toTrace(MassTrace)` returns only `xi/xv`, but that should be asserted and measured.

Cost: low-to-moderate complexity; no intended time penalty.

Verify: round-trip every TOF bin exactly and compare exported apex m/z bitwise.

### 6. Narrow `frame_of`

With approximately 1,400 frames/window, `uint16_t` is sufficient.

Change: `vector<uint16_t> frame_of`, with an explicit assertion `F <= 65535`.

Saving:

- 2 bytes/peak;
- 100 MB/window;
- **2.4 GB** for 24 windows.

Output: none.

Cost: nearly free.

Verify: assert the frame bound, compare every generated trace, and test a synthetic 65,536-frame rejection case.

### 7. Bit-pack `member`

Change: replace one byte/peak with one bit/peak.

Saving:

- from 1.2 GB to 0.15 GB;
- net **1.05 GB**.

Output: none.

Cost: candidate-loop lookups become bit operations; performance could improve from reduced memory bandwidth or regress from extraction overhead.

Verify: exact membership count, trace hashes, wall time and hardware cache counters.

### 8. Partition `order` by band

Change: build 12 seed-order lists during preparation, preserving each band’s global intensity ordering.

Memory: approximately neutral. Total indices remain 4 bytes/seed, though vector capacity fragmentation may add or remove a few hundred MB.

Time: eliminates 11 redundant full seed-list scans per window.

Output: none if the within-band order remains identical.

Verify: compare each band’s seed sequence with filtering the original global sequence.

### 9. Remove the list constructor path

Change: construct the `MassTrace` point vector directly.

Peak memory saving: small, because only one list/EPD chunk is actually live. At average length:

- only about **0.55 MB** across all 1,152 chunks.

It may save more for exceptionally long traces, but not the alleged multi-GB amount.

Output: none if insertion order and values match.

Time: likely a substantial improvement because it removes per-point node allocation.

Verify: compare the `MassTrace` point vectors exactly and profile allocation counts.

### 10. Avoid slab/input double allocation during `toSlab`

Change: transform `mzq` buffers to TOF in place or retain a segmented slab capable of adopting the frame buffers, then flatten only if required.

Maximum allocated-capacity saving:

- up to 500 MB/window;
- **up to 12 GB** at 24 simultaneous slab builds.

Actual RSS saving may be smaller because reserved destination pages are not necessarily resident before being filled.

Output: none; the conversion is already claimed exact.

Cost: segmented access may reduce tracing speed, so this can trade memory for time. Adopting/repacking buffers without segmentation is more complex.

Verify: compare every TOF value, track RSS during `toSlab` separately, and measure candidate-search performance.

Finally, three non-code-local suspects must be measured:

- The unconsumed compact store can own **up to 12.6 GB**.
- Accumulated emitted spectra are unquantifiable because neither spectrum count nor points/spectrum is supplied.
- Small-vector allocator fragmentation can plausibly own **6–12+ GB** just from minimum per-allocation overhead, before retained arenas.

Confirm ownership with phase-tagged RSS plus an allocation profiler that reports live and retained bytes by stack. The current `MemGuard` figures are insufficient because the list accounting demonstrably records objects after they have already been destroyed.
# The staging A/Bs on dataset D (2026-09-10, streaming source, 3 tiles, pitch 600)

Every arm must reproduce the pinned digest `8c1b047f3f70066c`; batch composition and allocator
reclamation are output-invariant by construction, so an arm that differs is the finding.
spock, 100 threads, node load 34-51 across the run.

## 1. The picker's flush (`SPEXTRACTOR_PICK_BATCH`), chain `ms1batch`

| batch | peak RSS | wall | where the peak is | MS1 load par. | MS2 tile-read CPU |
|---:|---:|---:|---|---:|---:|
| 256 (default) | 31.68 GB | 3:02.12 | load, t=9.6 s | 66.6x | 845 s |
| 64 | 28.65 GB | 3:06.27 | load, t=13.1 s | 49.5x | 1,192 s |
| 32 | 28.29 GB | 3:26.49 | load, t=23.4 s | 30.5x | 1,624 s |
| 16 | 28.48 GB | 3:50.26 | **window loop, t=112 s** | — | — |
| 512 | 30.66 GB | 3:05.16 | load, t=8.4 s | — | — |
| 256 (bracket, last) | 32.11 GB | 2:58.67 | load, t=9.1 s | — | — |

The two 256 controls bracket at 31.68 / 32.11 GB and 3:02.12 / 2:58.67, so run-to-run spread on
this node is ~0.43 GB and ~3.5 s. (An earlier version of this line said 31.83 GB and a 0.15 GB
spread; 31.83 GB is the load-trim chain's last control, copied into the wrong row.) Every
difference quoted below should be read against that 0.43 GB. Every arm reproduced the pin. 512 doubles the `scratch` row
(9,211 MiB) without raising the peak: the peak instant is not the staging maximum at that size.

**64 is the best point in the sweep: −9.6% peak for +2.3% wall** against the first control, −10.2%
and +3.3% against the mean of the two. That wall cost is inside the controls' own 3.45 s spread, so
it is not resolved by one arm; the phase table prices it at ~+11 s split between the MS1 pick and
the tile reads. No 128 arm was run, so 64 is not a located knee. Below it the process peak stops
following the MS1 peak: the MS1 peak keeps falling (28,194 -> 27,827 -> 27,207 MiB at 64/32/16) but
the process peak cannot go below the 3-tile window loop (27,574-28,549 MiB across arms), while wall
climbs +10.8% and +23.6%.

**The cost is on the wrong side of the knob.** The memory win is entirely MS1: the picker's staging
is 4,802 MiB of a peak that happens during the load, and the `scratch` row drops out of the top six
by 64. But `kBatch_()` drove BOTH flushes, so the same setting re-batches the MS2 tile reads, whose
WALL rises 15.9 -> 23.2 -> 32.7 s at 256/64/32 while buying no memory. The LOAD(tile) CPU rise that
accompanies it (845 -> 1,192 -> 1,624 s) is `RUSAGE_SELF` and includes idle threads spinning at the
barriers of many short parallel regions -- the MS1 pass under the same knob stays flat at 678-729
CPU-s -- so the MS2-side price is wall, not work. `SPEXTRACTOR_PICK_BATCH_MS1` (commit e39df17)
splits the two flushes. Its code is correct (unset falls back to the shared knob; a C++11 magic
static; used only at the MS1 buffer threshold) but it is not in the binary these arms ran, so
"the MS1 memory without the MS2 cost" is a prediction until chain `compose` measures it.

## 2. What a `malloc_trim(0)` actually costs, measured, no new experiment needed

The tool already logs both of its phase-boundary trims. Across all four arms above:

| trim | RSS before -> after | cost |
|---|---|---:|
| MS1 -> window loop | 19,534 -> 2,547 MB | 1.94 s |
| window loop -> write | 20,026 -> 3,151 MB | 1.79 s |

Consistent to ±0.3 s across every batch size: **one full-arena walk is ~1.7 s and returns ~17 GB.**

### Pre-registered prediction for the load-trim A/B (chain `loadtrim`), written before it ran

`SPEXTRACTOR_LOAD_TRIM=<n>` trims every nth picker flush. The prediction is that **it will not pay
on the streaming shape**, for two reasons that are already measured:

1. At the streaming peak (t=8.8 s, 30,974 MiB) glibc free is only **5,495 MiB**. A trim there can
   return at most ~5.5 GB, against the ~3.0 GB the batch knob already returns for almost no wall.
2. At ~1.7 s a walk, anything approaching "every flush" is tens of seconds. `every1` and `every4`
   should be clearly worse on wall with little to show; `every16` is the only arm with a chance.

The prediction is that this is a RESIDENT-shape lever, not a streaming one: the resident arm's peak
is 45,884 MiB with 12,480 free and a 17.3 GiB drop the moment the boundary trim runs, so there the
ceiling is real. If the arms contradict this, the reasoning above is what was wrong, and the ledger
row that carries the correction is `unattributed` minus `glibc free` at the peak instant.

## 3. Picker versus loader (chain `batch2x2`) -- why a 2x2 and not a sweep

Two staging buffers of 256 frames each sit in the load and they answer to DIFFERENT knobs:
`SPEXTRACTOR_PICK_BATCH` moves `ms1_buf_` (charged, the `scratch` row), while
`SPEXTRACTOR_LOAD_BATCH` moves the calibration patch's own decode batch inside the loader, which
the tool does not allocate and cannot charge. At `PICK_BATCH=32` the residual live-but-uncharged
memory at the peak is ~4.0 GiB (unattributed 14,032 minus glibc free 10,042), and that is the
loader's. Varying only the picker therefore leaves a third of the staging untouched, which is the
whole reason for the 2x2.

## 4. The load-trim A/B, against the prediction written before it ran (chain `loadtrim`)

| `SPEXTRACTOR_LOAD_TRIM` | peak RSS | wall | peak |
|---:|---:|---:|---|
| 0 (first) | 31.70 GB | 3:05.05 | load, t=8.9 s |
| 16 | 31.75 GB | 3:04.47 | load, t=9.1 s |
| 4 | 29.88 GB | 3:12.31 | load, t=10.7 s |
| 1 | 29.75 GB | 3:35.78 | load, t=12.4 s |
| 0 (last) | 31.83 GB | 2:56.02 | load, t=8.8 s |

**The prediction held.** Every 16th flush does nothing measurable. Every 4th takes ~1.9 GB off
for +11.8 s against the mean control (+6.5%); every flush takes ~2.0 GB for +35 s (+19.5%). The
ceiling it approaches is the ~5.5 GiB of free list standing at the peak instant, and it reaches
under half of that. `PICK_BATCH=64` buys 3.0 GB for +2.3%, so on the streaming shape the trim is
dominated outright. It was never tested composed with the batch knob, and it was never tested on
the resident shape, where the pre-registered reasoning says its ceiling is real.

## 5. Picker versus loader (chain `batch2x2`)

| `PICK_BATCH` / `LOAD_BATCH` | peak RSS | wall | peak |
|---|---:|---:|---|
| 256 / 256 (first) | 31.98 GB | 2:56.93 | load, t=8.9 s |
| 32 / 256 | 29.15 GB | 3:22.14 | window loop, t=175.7 s |
| 256 / 32 | 31.86 GB | 3:04.76 | load, t=9.3 s |
| 32 / 32 | 28.15 GB | 3:33.69 | window loop, t=94.9 s |
| 16 / 16 | 28.65 GB | 4:09.26 | — |
| 256 / 256 (last) | 31.96 GB | 3:05.25 | — |

**`LOAD_BATCH` is inert on the MS1 peak**: 256/32 is the control to within 0.1 GB. The MS1 decode
batch is hard-coded at 64 frames (`patch:340`) and pass 1 never enters the MS2 loop the env var
sizes. The 1.0 GB between 32/256 and 32/32 is not attributable: the same `PICK_BATCH=32` setting
measured 28.29 GB in the sweep and 29.15 GB here, a 0.86 GB spread for identical configurations
once the peak has moved into the window loop.

## 6. The measurements the first synthesis asked for, answered

**M-a -- does draining the staging lower the peak, or relocate it into MS1 tracing?** It lowers it.
Per sub-phase of pass 1, RSS high-water in MiB (LOAD = until the load ends; PARTITION = while the
MS1 band partition is live; POST = the rest of pass 1):

| arm | LOAD | PARTITION | POST | process peak |
|---|---:|---:|---:|---|
| stream, 3 tiles, batch 256 | 30,974 @ 8.8 s | 22,375 | 21,277 | load |
| stream, 6 tiles, batch 256 | 30,919 @ 9.6 s | 22,868 | 21,884 | load |
| batch 64 | 28,194 @ 13.1 s | 22,663 | 21,364 | load |
| batch 32 | 27,827 @ 23.4 s | 22,727 | 21,751 | load |
| batch 16 | 27,207 @ 34.6 s | 22,775 | 22,573 | **window loop, 27,935** |
| resident, 1 tile | 45,884 @ 28.0 s | 34,403 | 33,491 | load |

The RSS while the partition is live is FLAT at 22,226-22,868 MiB in every streaming arm, whatever
the batch. The load peak sits 8.4 GiB above it at batch 256 but only 5.4 / 5.0 / 4.3 GiB above it
at 64 / 32 / 16: **the gap shrinks because the load peak falls while the partition does not
move**, so draining the staging lowers the process peak rather than relocating it into MS1
tracing. At batch 16 the load peak is 27,207 MiB (26.6 GiB) and the 3-tile window loop is 27,935 MiB
(27.3 GiB); the two are equal within the loop's own ~1 GiB run-to-run spread. **That window-loop
peak is a soft cap, not a floor.** At its instant 50-62% of RSS is glibc free list, and the
load-trim arms -- whose trim also fires in the tile-read flushes inside the loop -- put the same
loop peak at 22,872-24,995 MiB. The composition that would test how far below it the process can
go (the MS1-only batch plus a trim) is chain `compose`.

**M-c -- the scorer's survivor fraction, and what tiling does to scan work.** Same build, same
precursors (710,356), same survivors per pitch:

| arm | fragment visits | RT-gate survivors | survivor fraction | loop CPU | loop parallelism |
|---|---:|---:|---:|---:|---:|
| stream, 1 tile, pitch 600 | 608.7e9 | 3,813,949,410 | 0.63% | 6,765.7 s | 59.9x |
| stream, 3 tiles, pitch 600 | 299.0e9 | 3,813,949,410 | 1.28% | 6,110.8 s | 44.1x |
| stream, 1 tile, pitch 300 | 620.2e9 | 3,882,998,346 | 0.63% | 6,638.3 s | 55.7x |
| stream, 6 tiles, pitch 300 | 169.6e9 | 3,882,998,346 | 2.29% | 5,661.4 s | 41.0x |

**Tiling halves the scorer's scan at 3 tiles and cuts it 73% at 6, with identical survivors**,
because a tile's precursors are only ever tested against the tile's fragments plus the carry.
That is why loop CPU FALLS 9.7% and 14.7% while wall rises: the work shrank and the occupancy fell
further (59.9x -> 44.1x). **The CPU fall is consistent with the halved scan but not attributable
to it from these runs**: there is no per-stage CPU counter, and the score stage's summed elapsed
fell only 17% and 16% against visit cuts of 51% and 73%, at ~4% of summed stage elapsed (tracing
is ~95%). The 0.63% survivor fraction is also the wrong gate for the arena re-layout family: a
reject is a 2-byte read while a survivor walks a 96-byte record and its arena span, so survivors
are roughly two thirds of the score stage's time. If that family is dropped, the reason is that the
whole score stage is a small share of the loop, and that needs a CPU-share measurement to confirm.

**M-e -- TNBC 009 per-cell density, pitch 600, from `Frames.NumPeaks` without decoding.** 13 cells;
the densest cell holds 9.69% of raw MS2 peaks against a uniform 7.69% (1.26x). Grouping the cells
into fewer, larger tiles:

| cells per tile | tiles | densest tile, fixed stride | densest tile, minimax | smaller by |
|---:|---:|---:|---:|---:|
| 2 | 7 | 18.93% | 18.48% | 2% |
| 3 | 5 | 28.17% | 23.18% | 18% |
| 4 | 4 | 36.84% | 27.61% | 25% |
| 6 | 3 | 52.90% | 37.39% | 29% |

Density-balanced grouping is worth nothing at one cell per tile and 18-29% of the densest tile at
three to six. Two qualifications from verification: the 3-cells-per-tile figure needs one tile of
four cells (capped at three cells it is 9.3%), and on the tool's actual cell edges (10,584 frames per
cell, a short last cell, shares taken from the tile reads) the four figures are 1.5 / 22.4 / 23.6 /
29.8%. It matters only where someone chooses fewer tiles to buy back wall time, and only
if the densest tile, rather than pass 1, sets the peak there.

**M-f -- the TNBC write, re-read from the step-3b gate.** 44.3 s at 32.1x (1 tile) and 41.8 s at
34.1x (13 tiles), 1,424-1,426 CPU-s. The panel's "~50 s at 1.0x" came from a 2026-09-07 table that
predates the parallel writer. A writer agent can hide at most the twelve non-terminal blocks,
~40-41 s if encode time follows spectrum count (38.6 s only if blocks were uniform), and those
encoders already use ~34 cores, so the hidden time is not free of contention with the loop it
would overlap. Treat it as an upper bound, not a projection. Separately, 13 tiles cut the TNBC loop
itself (net of the enclosed read/sort/write) 43,005 -> 21,693 CPU-s (−49.6%); that is consistent
with the scan halving measured on D but inferred, not measured, because the gate's driver did not
extract the score-gate line.

## 7. Verification (14 Fable 5.1 verifiers, 2026-09-10)

Every claim in sections 1-6 went to two independent verifiers: one recomputed every number from the
raw `ledger.tsv`, `e.log` and `t.log` files, the other attacked the mechanism in the source. **All
seven came back "partly"**: the direction of every claim held, and each needed a correction, now
applied in place above. The corrections that change a decision:

- **The window-loop "floor" on D is soft.** Half its RSS is free list, and a trim inside the tile
  reads already lowers it by 3-5 GiB. So R1 and R2 are capped by it only under today's no-trim loop.
- **The load-trim prediction held in direction, but its cost premise was ~7x too high.** A mid-load
  trim costs 0.23-0.9 s, not the ~1.7 s of the phase-boundary trims, because far less is on the
  free list then. `every16` did nothing because pass 1 has only six picker flushes and it never
  fired before the peak; `every4` fired once, right before the peak batch. The prediction text in
  section 2 is left as written, because it was committed before the run.
- **The survivor fraction is not the gate for the arena re-layout family**; the score stage's CPU
  share is, and it is not instrumented.
- **Unit convention.** `/usr/bin/time` reports KiB. Following the project convention (BACKLOG,
  "Units"), the "GB" figures in sections 1-5 are that KiB count divided by 10^6; the ledger's are
  MiB. The verifiers flagged that an earlier draft of section 6 labelled thousand-MiB values as GiB.

Full verdicts: `scratchpad/verify2_digest.md` (session artefact), summarised above.

## 8. The composition (chain `compose`, binary `531dad4`, 2026-09-10 11:16-11:36)

The verifiers said the window-loop cap on D is soft and that nobody had composed the levers. This
chain did, on the build that carries the MS1-only picker batch (`SPEXTRACTOR_PICK_BATCH_MS1`,
e39df17). Dataset D, streaming, 3 tiles, pitch 600, 100 threads, spock. **Every arm reproduces
`8c1b047f`, and the two controls agree to 0.07 GB and 3.0 s**, the tightest bracket of the day.

| arm | wall | peak | vs mean control | MS1 pass | tile reads | loop net of tile reads | node load at start |
|---|---:|---:|---:|---:|---:|---:|---:|
| control, first | 2:57.05 | 31.83 GB | | 10.3 s | 15.9 s | 123.9 s | 21 |
| MS1-only batch 128 | 2:59.03 | 30.55 GB | −1.32 GB (−4.1%) | 12.2 s | 15.8 s | 123.4 s | 49 |
| MS1-only batch 64 | 3:14.72 | 29.19 GB | −2.68 GB (−8.4%) | 15.1 s | 16.6 s | 136.7 s | 40 |
| **batch 64 + trim every 16th flush** | **3:13.09** | **26.99 GB** | **−4.88 GB (−15.3%)** | 16.8 s | 23.5 s | 127.2 s | 32 |
| batch 64 + trim every 4th flush | 3:32.77 | 26.23 GB | −5.64 GB (−17.7%) | 19.3 s | 32.0 s | 135.5 s | 57 |
| control, last | 3:00.05 | 31.91 GB | | 11.0 s | 16.5 s | 126.1 s | 45 |

**The MS1-only knob does what it was built for.** At batch 64 the tile reads take 16.6 s, against
23.2 s under the shared knob in the `ms1batch` chain (a cross-chain comparison, but 6.6 s against a
3 s bracket). What remains is the MS1 pass, whose parallel pick starves as the batch shrinks:
+1.9 s at 128 and +4.5 s at 64 against the mean control.

**The batch-64 arm's other 11.7 s is node load, not the knob.** It sits entirely in the loop net of
tile reads, which the knob never touches, and that arm started at load 40 against 21. The trim-16
arm, at load 32, has the controls' loop time.

**The composition breaks the window-loop cap.** A trim every 16th flush fires once in pass 1 and
then inside the tile reads, which is exactly where the loop's free list builds. It takes the peak
to 26.99 GB for +14.5 s (+8.1%), and this time all of the cost is attributable: +6.2 s in the MS1
pass and +7.3 s in the tile reads, with the loop unchanged. The tile reads end at 13.4 GB of RSS
against ~24.7 GB for the controls.

**The peak has moved back into pass 1, and D's next floor is now visible.** The trim-16 arm peaks
at 26,603 MiB at 16.5 s, the end of the load, with the MS1 map at 13,290 MiB and 10,136 MiB of glibc
free list; only ~2.5 GiB is live but uncharged, down from ~10.7 at the default. So the next memory
on D is the MS1 map itself plus the free list the load leaves behind before the boundary trim.

**Trimming every 4th flush is dominated.** It buys 0.76 GB more than every 16th for +19.7 s, of
which ~9 s is attributable (2.5 s MS1 pass, 8.5 s tile reads) and the rest coincides with load 57.
Its peak carries the same 10.1 GiB of free list: more frequent trims inside pass 1 do not reach the
load-end residue.

**What this recommends, and where it does not reach.** On dataset D in tiled mode,
`SPEXTRACTOR_PICK_BATCH_MS1=64` with `SPEXTRACTOR_LOAD_TRIM=16` is the best measured point:
−15.3% peak for +8.1% wall, class D. **It is untested on TNBC 009**, where the tiled floor is the MS1
partition phase (data4-tnbc.md) and neither knob acts on that phase. Measure it there before either
becomes a default, and read the result against the partition-phase trim that data4 names as the
lead for the long file.


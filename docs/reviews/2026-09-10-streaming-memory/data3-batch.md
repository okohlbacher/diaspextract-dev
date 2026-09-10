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

**The knee is 64: −9.6% peak for +2.9% wall.** Below it the curve turns. 32 buys another 1.3% of
memory for 11% of wall; 16 is WORSE on both, because by then the load staging is gone and the peak
has moved to the window loop, which this knob does not touch. The floor of the knob is ~28.3 GB.

**The cost is on the wrong side of the knob.** The memory win is entirely MS1: the picker's staging
is 4,802 MiB of a peak that happens during the load, and the `scratch` row drops out of the top six
by 64. But `kBatch_()` drove BOTH flushes, so the same setting re-batches the MS2 tile reads, whose
CPU rises 845 -> 1,192 -> 1,624 s while buying no memory at all -- the MS2 slabs are not what peaks.
`SPEXTRACTOR_PICK_BATCH_MS1` (commit e39df17) splits them; the arm that tests it is queued.

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

The partition's high-water sits **~8 GiB below** the load peak in every streaming arm, and stays
there as the staging drains. So the staging levers are real, and their floor is not MS1 tracing:
at batch 16 the load peak is still 27.2 GiB, and the window loop at 3 tiles (~27.9 GiB) takes over
as the process peak. **On D at 3 tiles the reachable floor from pass-1 staging alone is ~28 GiB.**

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
further (59.9x -> 44.1x). It sizes the orchestration prize from a same-build pair rather than a
model, and it says the arena re-layout family is not worth building: at the shipped default only
0.63% of visits survive the RT gate, so the survivor-side walk is a small share of the scan.

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
three to six. It matters only where someone chooses fewer tiles to buy back wall time, and only
if the densest tile, rather than pass 1, sets the peak there.

**M-f -- the TNBC write, re-read from the step-3b gate.** 44.3 s at 32.1x (1 tile) and 41.8 s at
34.1x (13 tiles), 1,424-1,426 CPU-s. The panel's "~50 s at 1.0x" came from a 2026-09-07 table that
predates the parallel writer. A writer agent can hide at most the twelve non-terminal blocks,
~38 s, and those encoders already use ~34 cores, so the hidden time is not free of contention with
the loop it would overlap. Treat ~38 s as an upper bound, not a projection.


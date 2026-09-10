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

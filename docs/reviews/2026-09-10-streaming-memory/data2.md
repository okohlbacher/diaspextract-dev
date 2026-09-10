# Dataset D, re-measured with the repaired ledger (2026-09-10, chain `instr3`)

Binary `4258d16` (`/ceph/.../instr_ledger2`, binary_sha256 `a2905f71…`), spock, 224 cores,
100 threads, MemAvailable ~1 TB, load 3-60 across the run. `INSTR3_RESULT PASS`: **every arm
reproduces its pinned digest**, so the instrumentation repair is output-identical.

The arms are two CONTROLLED pairs, one per cell pitch, so grouping is the only variable inside a
pair. The previous pass compared a 600 s one-tile arm against a 300 s six-tile arm, which confounds
pitch with grouping; a reviewer called that out and it is fixed here.

## The five arms

| arm | wall | peak RSS | ledger peak, when, phase | charged | unattributed | glibc free |
|---|---:|---:|---|---:|---:|---:|
| resident, 1 tile | 2:29.83 | 46.77 GB | 45,884 MiB @ 28.0 s, load | 26,711 | 19,173 | 12,480 |
| stream, 1 tile, pitch 600 | 2:30.71 | 41.71 GB | 40,709 @ 88.0 s, loop | 23,239 | 17,470 | 12,350 |
| **stream, 3 tiles, pitch 600** | 2:55.30 | **31.76 GB** | 30,974 @ 8.8 s, load | 14,744 | 16,230 | 5,495 |
| stream, 1 tile, pitch 300 | 2:36.90 | 38.02 GB | 37,265 @ 78.9 s, loop | 23,739 | 13,526 | 12,125 |
| **stream, 6 tiles, pitch 300** | 2:55.49 | **31.76 GB** | 30,919 @ 9.6 s, load | 14,744 | 16,175 | 6,412 |

## Three things this says that the previous pass could not

**1. Tiling on D is finished, and 3 tiles finishes it.** The 3-tile and 6-tile arms peak within
**1 MB of each other** (31,757,788 vs 31,758,716 kB) and finish within 0.2 s of each other, at two
different cell pitches and two different digests. They are not converging by luck: both are pinned
by the SAME event, the MS1 pass at t≈9 s, which no amount of MS2 tiling touches. Inside the window
loop the six-tile arm is far smaller (slab 3,548 MiB against 5,779 at three tiles), and none of it
reaches the process peak. **More tiles is now free and worth nothing; the next gain has to come out
of the MS1 pass.**

Within a pair, grouping is worth:

| pitch | 1 tile -> tiled | peak | wall |
|---|---|---:|---:|
| 600 | 1 -> 3 | −23.9% | +16.3% |
| 300 | 1 -> 6 | −16.5% | +18.5% |

**2. The cell pitch itself moves the one-tile peak, and stops mattering once tiled.** At one tile,
600 s peaks at 41.71 GB and 300 s at 38.02 GB (−8.8%): the peak is in the window loop, and a
smaller cell is a smaller detection working set. Once tiled, both land on the MS1 floor and the
pitch is irrelevant to the peak. So `tile:rt_sec` is a science knob, not a memory knob, wherever
`tile:cells_per_tile` is set.

**3. The two peaks are made of different things, and only one of them is reclaimable.**

- The **resident** arm's peak is 45,884 MiB at t=28.0 s with 19,173 unattributed and 12,480 of
  glibc free list. Two seconds later RSS is 28,052 MiB with the **charged total unchanged**. That
  17.3 GiB was never live data: it is one load's worth of allocator free list, returned by the
  end-of-load `malloc_trim`.
- The **streaming** arm's peak is 30,974 MiB at t=8.8 s inside the loader, and there glibc free is
  only 5,495 MiB. So **~10.7 GiB is LIVE and uncharged** at the exact peak instant, and no trim can
  touch it. It is the two staging buffers of the load: `ms1_buf_` (charged, the `scratch` row at
  4,235 MiB) and, behind it, the calibration patch's own 256-frame decode batch plus the opentims
  raw uint32 buffers, neither of which the tool allocates and neither of which it can charge.

That distinction sets the two experiments that follow: a trim during the load can only help the
resident shape, while the batch sizes are the only knobs on the streaming shape. They are separate
knobs -- `SPEXTRACTOR_PICK_BATCH` moves `ms1_buf_`, `SPEXTRACTOR_LOAD_BATCH` moves the loader's
decode batch -- which is why the follow-up is a 2x2 and not a sweep.

## What the repair changed in the numbers

| row | before | now | why |
|---|---:|---:|---|
| `band_arena` at the MS1 phase | 605 MiB | **13,579 MiB** | the MS1 band partition was carried under `ms1_map` until detection returned |
| `spectra` | 1,965 MiB, after the stage | 3,492 MiB, during it | charged at emission, plus the empty slot header per owned precursor |
| `TOTAL(measured)` | 105-109% | ≤100% | enclosed phases are no longer summed into their parent |
| the unit | "MB" | MiB | the values were always `>>20` of a byte count |

The handover is exact rather than additive: `ms1_map` 13,830 -> 0 and `band_arena` 0 -> 13,579 MiB
in ONE 250 ms sample, then draining band by band as detection consumes each one.

**Still unattributed, and honestly so:** MassTraceDetection's own internal copy of each band (it
cannot be charged without patching OpenMS), and the loader-side staging above. `band_arena` also
does double duty -- the MS1 partition during the load phase, the MS2 band arenas during the loop --
which never overlap in time, and the report prints the phase of each peak so the two are
distinguishable.

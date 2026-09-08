# SpeXtractor

Extract pseudo-DDA ("pseudo-MS/MS") spectra from Bruker timsTOF **diaPASEF** data.

SpeXtractor turns a data-independent acquisition into a set of pseudo-tandem spectra that any
ordinary DDA search engine can read. Each emitted spectrum pairs one precursor hypothesis with the
fragment traces that co-elute with it in both retention time and ion mobility. The output is mzML
(or mzPeak, following the `-out` extension), so it feeds Sage, MSFragger, Comet or anything else that
reads mzML — no library, no spectral prediction, no enumeration of the search space in advance.

That last point is the reason the tool exists: because the search space is not enumerated before
the search runs, an **open or blind search** over the output can report variants and unexpected
modifications that a library-based DIA workflow cannot represent.

SpeXtractor is BSD-3-Clause and is a standalone application. **OpenMS is a prerequisite, not a
host** — the tool links against an OpenMS installation but lives outside the OpenMS source tree.

## Requirements

| | |
|---|---|
| OpenMS | the development commit pinned in `patches/openms.lock` (bd4b895, 2026-04-24; it identifies itself as a 3.6.0 pre-release), patched by `scripts/apply_openms_patches.sh` and built `WITH_OPENTIMS` to read Bruker `.d`. No released OpenMS package works |
| Compiler | C++20 — GCC 13+ or Clang 16+ |
| OpenMP | required |
| CMake | 3.21+ (OpenMS's own requirement; the tool itself needs 3.16) |
| **Memory** | **~57 GB peak** on a 30-minute gradient and **~170–190 GB** on a 2-hour acquisition at the shipped defaults (the 30–60 min cohort spanned 68–109 GB before the memory work); it scales with the acquisition |
| Disk | mzML output was 6.2 GB for 656k spectra (30-minute run) and 19–20 GB for a 2-hour run at the previous default; the current default emits 30–70% more spectra. mzPeak is about a third of that |

The memory figure is not a suggestion. A full-depth diaPASEF acquisition holds millions of mass traces
in flight: a 30-minute in-house acquisition needs ~57 GB and a 2-hour one ~190 GB, while low-load
public files (PXD017703) ran in 10–26 GB. Peak usage is reported at the end of every run, so you can
size a node from your own data. Memory figures throughout are peak RSS as `/usr/bin/time` reports
them (kB ÷ 10⁶).

## Install

```bash
git clone https://github.com/okohlbacher/spextractor.git
cd spextractor
scripts/apply_openms_patches.sh /path/to/OpenMS    # see "OpenMS patches" below
cmake --build /path/to/OpenMS/build -j             # rebuild OpenMS: the patches change its headers and libOpenMS
cmake -B build -DOpenMS_DIR=/path/to/OpenMS/build
cmake --build build -j
export OPENMS_DATA_PATH=/path/to/OpenMS/share/OpenMS  # a source-built OpenMS has no installed share/; the binary dies on --help without it
```

The binary is `build/spextractor`. `cmake --install build` puts it in `<install prefix>/bin` (set `-DCMAKE_INSTALL_PREFIX`).

### OpenMS patches

`scripts/apply_openms_patches.sh` installs `src/TdfMzCalibration.h` into the OpenMS tree and applies
four patches. **All four matter. The build stops without the first and the third; it does not
notice a missing second or fourth:**

- **Vendor m/z calibration.** Without it the Bruker reader converts flight time to m/z with a
  two-point linear-in-sqrt chord that is **−5 to −11 ppm biased** (m/z dependent) on every file
  measured, worth roughly **6–11% more closed-search Sage identifications** on the three files measured. Every emitted mzML
  records which calibration was used in the `spx:mz_calibration` userParam
  (`tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`). An unsupported calibration
  table **fails closed** rather than silently producing biased masses.
- **Lock-free elution-peak detection.** OpenMS guards a shared vector with a program-global critical
  section. Called from inside SpeXtractor's parallel window loop, that one lock serialises the tool.
- **`MassTrace` move operations.** OpenMS declares a defaulted destructor and copy operations on
  `MassTrace`, which suppresses the implicit moves, so every `std::move` deep-copied its points. A
  `static_assert` stops the build without this one.
- **Parallel mzML serialisation.** Writing the spectrum list is CPU-bound, not I/O-bound — measured,
  it sustains ~400 MB/s against a filesystem that does 4.0 GB/s — and the stock writer does it on
  one thread. Encoding one spectrum is independent of every other, so this encodes chunks in
  parallel and appends them in index order, giving byte-identical output. Each thread needs its own
  handler and validator: the writer memoises CV-term validation in mutable state, and sharing one
  handler corrupts the heap. Measured on a 30-minute acquisition: **20.1 s → 5.9 s**.

Optionally, `OPENMS_BRUKER_SDK_PATH=/path/to/libtimsdata.so` uses Bruker's own library for the
conversion instead. It is an independent cross-check, not a requirement, and is not redistributed.

### Optional: `.mzpeak` input

Build the mzPeak C++ library once against the same Arrow/Parquet/libzip that OpenMS uses
(`scripts/build_mzpeak_lib.sh`), then configure with `-DMZPEAK_ROOT=<checkout>`. This also needs the
OpenMS mzPeak integration (the OpenMS/mzpeak fork), which the pinned commit does not carry; the plain recipe above builds without it,
reads `.d` and mzML, and writes mzML. `.d` remains the primary input and is faster.

## Run

```bash
spextractor -in sample.d -out pseudo.mzML -threads 64
```

That is the complete command. Every default is the configuration the project benchmarks; a run that
needed extra flags to reproduce a published figure would be a bug. The end-to-end suite pins the
shipped detector and the charge floor (it passes a few extraction options of its own, so it is not a
test of the whole default set).

Then search the output like any DDA file:

```bash
sage sage.json -o results pseudo.mzML
```

### Options worth knowing

| option | default | what it does |
|---|---|---|
| `-threads` | all cores | worker threads; an explicit `-threads 1` on the command line is honoured (only the command line is inspected: `threads = 1` in an ini file is treated as unset). Parallelism is isolation windows × flight-time bands, and the window loop reaches ~78× (30-min) to ~89× (2-hour) thread occupancy at 100 threads; window concurrency is bounded by a free-RAM admission gate, not by core count |
| `-out_type` | follows the extension | `mzML` or `mzpeak`; in a build with mzPeak, `.mzpeak` when the extension says nothing (a plain build writes mzML only). Search engines read mzML, so write `.mzML` whenever a search comes next |
| `-trace:detector` | `integer` | `integer` works on the instrument's flight-time bin; `openms` uses OpenMS `MassTraceDetection`. Different algorithms — see below |
| `-charge:min_charge` | 1 | lowest precursor charge to emit. Singly charged precursors are genuine on tryptic data (their mobility sits on the 1+ trend line) and are 14–20% of Sage peptides on a 2-hour acquisition, though only ~1.7% on a 30-minute one. Their stratum carries 3–9% entrapment FDR under a pooled 1% cut (file-dependent), so control FDR per charge downstream. `-charge:min_charge 2 -charge:im_charge_veto false` restores the old behaviour (the veto runs first, so `2` alone keeps its re-called 2+) |
| `-charge:im_charge_veto` | `true` | the 2+ and 3+ ion-mobility trend lines are fitted per run from the run's own confident precursors; a z=1 call on the 2+ line (11–26% of z=1 calls depending on the file: a halved 2+ envelope) is re-called 2+, one on the 3+ line is dropped. Genuine 1+ ions are untouched |
| `-charge:im_veto_band` | 2.5 | half-width of the veto's mobility band, in MAD-sigma of the fitted residuals |
| `-assembly:require_isotope_support` | `true` | drop precursor hypotheses with no isotope partner. `false` roughly doubles emission, was ~7× slower (measured 2026-09-04, before the scheduling fixes) and identifies fewer peptides |
| `-perf:malloc_trim` | `true` | return the allocator's free pages at the two phase boundaries (glibc). Trades **-30% peak memory for +8.5% wall** on a 2-hour acquisition (the loop re-faults the returned pages cold); byte-identical output either way. Off when time, not memory, is the constraint |
| `-perf:stream_load` | `true` | read the `.d` frame by frame. `false` holds the whole run in memory (90 GB floor) **and changes the output**: measured, it is slightly *more* sensitive on a large file (+2.0% Sage peptides at unchanged entrapment FDR) for 1.75× the memory and ~1.7× the wall |
| `-perf:ms1_trace_bands` | 48 | band-parallel MS1 mass-trace detection (exact partition with a halo). Raised from 12 on 2026-09-07: MS1 tracing 2× faster; peptide counts within 0.01–2% on both engines and both gate datasets (set overlap 99.4% on dataset D, 89–99% on dataset A); 1 = off |
| `-trace:max_span_sec` | 120 | trim a mass trace to this many seconds around its apex |

`spextractor --helphelp` lists every option, most with the measurement behind the default.

### Reading the output

Emitted spectra are MS2 with a synthetic precursor. Provenance is recorded as userParams on the
run — `spx:detector`, `spx:require_isotope_support`, `spx:mz_calibration` — so a file can always be
attributed to the configuration that produced it.

## Two detectors

`-trace:detector` selects between genuinely different algorithms, not two implementations of one.

- **`integer`** (default) finds a peak's candidate traces by arithmetic on the instrument's own
  flight-time index, and never converts its compact store back to double m/z. It needs the vendor
  calibration and falls back to `openms` — loudly — without it.
- **`openms`** runs OpenMS `MassTraceDetection` on a materialised peak map.

They agree on about 85% of the union of identified peptides. Which one identifies more depends on
the search engine and on the file, so **the reason `integer` is the default is memory** — roughly
40% less — not a peptide gain. If you are chasing identifications on a particular dataset, it is
worth trying both.

## Performance

Measured at the shipped defaults, 100 threads:

| | 30-minute gradient (33,553 frames) | 2-hour acquisition (PXD047793 run 009) |
|---|---|---|
| wall time | 2:54 | 11:18 |
| peak RSS | 57 GB | 187 GB |
| pseudo-spectra emitted | 0.85 M | 3.9 M |

Both figures are **11.6% and 17.7% faster than v2.0.0** respectively, from four byte-identical
changes made after that release (see the CHANGELOG): the Savitzky-Golay coefficients are cached,
mzML spectra are serialised in parallel, the canonical sort sorts keys rather than 750-byte spectrum
objects, and the assembled PeakMap takes its vector whole. Every one reproduces the pinned digests
on both files, so identifications are unchanged.

On the 2-hour file, on the same node, v2.0.0 was **0.61× the wall time and 0.55× the peak memory** of
the reference implementation, with 1.28× its Sage peptides at parity (0.996) with MSFragger under
per-charge FDR control (docs/REFERENCE-COMPARISON-2026-09-08.md); the changes above take the wall
ratio to roughly **0.54×** on the same measurement, and leave every peptide count untouched.

The allocator's retained free pages were the largest single memory item on a 2-hour acquisition;
`perf:malloc_trim` returns them at the phase boundaries (−30% peak for +8.5% wall) and is on by
default. Preloading `tcmalloc_minimal` measured −7% peak RSS (wall-neutral, byte-identical) before the
trim shipped; it has not been re-measured with it, so the two are not known to be additive.

Runtime is dominated by the window loop, which is parallel across isolation windows and, within a
window, across flight-time bands. The loader is 10–14%. Memory, not CPU, sets how many
windows can be in flight: an admission gate re-decides concurrency from free RAM at every window admission.

## Determinism

The spectrum data is **byte-identical across thread counts** for a fixed binary at the default loader
batch: 8 vs 100 threads on two real-data pairs (measured at v0.3.0, before the compaction fix; no
real-data pair has been re-taken since), and 1 vs 4 threads in the end-to-end suite, which exercises
the fallback detector on synthetic input. The loader batch size is *not* free: 1024 and 4096 change
the digest, and 4096 loses 7% of peptides, so it is not a knob.
`bench/semantic_digest.py` hashes `<spectrumList>`..`</spectrumList>`, excluding the wall-clock
stamp, the recorded parameters and the trailing byte-offset index — none of which can match across
invocations.

This does **not** survive a code change: a last-ulp difference in one arithmetic path cascades to
~2% in peptide counts. Compare two builds by the accepted peptide **set** and the ppm median, never
by raw counts. The two statements are about different things and both have been measured.

## Tests

```bash
python3 test/test_spextractor.py build/spextractor
```

Thirteen end-to-end checks against a synthetic acquisition: isotope ownership, the charge floor,
parameter validation, thread-count determinism, mass-trace extension across missing cycles, and
that the shipped detector is the one that actually runs. No fixtures, no framework, no network.

`tests/` additionally holds the calibration unit tests and the entrapment-FDR scoring used for the
benchmark record.

## Layout

```
src/        the tool (one translation unit) plus three headers: the calibration model, the tdf reader
            and the mzPeak streaming loader
patches/    the three OpenMS patches and the pinned OpenMS commit (openms.lock)
scripts/    build helpers, OpenMS patch application, cluster deployment
test/       the end-to-end suite
tests/      calibration and entrapment tests, golden calibration values
bench/      benchmark drivers, the semantic digest and the cluster launcher
harness/    the benchmark harness and the sample-registry template
docs/       measurements, design notes and review records
```

## Documentation

- [docs/BASELINE.md](docs/BASELINE.md) — the decision record: every default, what was
  measured to justify it, and what was falsified
- [docs/MZ-AXIS-DESIGN.md](docs/MZ-AXIS-DESIGN.md) — the flight-time index and the integer detector
- [docs/charge-inference.md](docs/charge-inference.md) — charge assignment, its coupling to MS1
  splitting, and the levers that did not work
- [CHANGELOG.md](CHANGELOG.md)

## Citing

See [CITATION.cff](CITATION.cff).

## License

BSD-3-Clause. Derived from OpenMS (BSD-3-Clause) — see [NOTICE](NOTICE).

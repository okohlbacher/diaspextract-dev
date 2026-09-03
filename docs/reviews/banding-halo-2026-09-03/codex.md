## 1. Is the hypothesis right, wrong, or incomplete?

**Verdict: substantially right, but incomplete.** Banding is not exact. The observed N-dependent output is expected from the implementation, not evidence of a sorting problem. However, two parts of the hypothesis misdescribe the actual OpenMS path:

- Acceptance is not simply “within `mass_error_ppm`.” OpenMS initializes a standard deviation from the ppm value, tests candidates within **±3 standard deviations**, and dynamically re-estimates that deviation by default. See [`MassTraceDetection::findBestPeak_` and `isPeakAcceptable_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:288), [`MassTraceDetection::processPeak_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:384), and the default `reestimate_mt_sd=true` in [`MassTraceDetection::MassTraceDetection`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:26).
- `min_sample_rate` does not terminate extension in this configuration. speXtract changes its value but leaves `trace_termination_criterion` at OpenMS’s default `"outlier"`; the sample rate is therefore applied as a final validity filter. See [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:979), [`MassTraceDetection::MassTraceDetection`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:40), and [`MassTraceDetection::isTraceValid_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:445). The comments at [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:987) are inaccurate on that point.

The three proposed mechanisms evaluate as follows.

1. **Halo sizing: correct.** The asymmetric arithmetic was a real defect; the current working-tree fix sizes each side from its own edge in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1044). But `20.0` remains an unsupported empirical constant. Nothing in the detector establishes a 20-ppm-multiple span bound.

2. **Trace drift: correct in conclusion and stronger than stated.** The running intensity-weighted centroid is updated after each accepted peak, while the allowed standard deviation can also expand. See [`MassTraceDetection::updateIterativeWeightedMean_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:62), [`MassTraceDetection::processPeak_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:417), and [`MassTraceDetection::run_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:537). Even with a fixed tolerance, repeated movement relative to a running mean has no input-independent total-span bound. With variance re-estimation, the failure can be much faster. speXtract also leaves maximum trace length disabled unless explicitly positive in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:991).

3. **Detection non-locality: correct, but the argument is incomplete.** OpenMS processes intensity-ordered apices through one greedy `peak_visited` state; only peaks belonging to valid traces become visited. Changing the peak set can therefore change later seeds and assignments. See [`MassTraceDetection::run`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:216) and [`MassTraceDetection::run_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:471).

There is an additional, cleaner non-locality defect: **speXtract drops a spectrum completely from a band if it has no raw peak inside that band’s halo** in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1041). OpenMS distinguishes an absent spectrum from a present spectrum containing an out-of-tolerance peak when counting misses and visited scans. Thus even a zero-width mass trace can change validity under banding.

Valley splitting is not an independent source of the initial discrepancy. It runs only after band results have been filtered and concatenated in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1090) and [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1100). It can amplify an already altered trace, but if the incoming `MassTrace` set and memberships were identical, per-trace splitting would not manufacture a band-count dependency.

The centroid-core filter is also weaker than its comment claims. It suppresses duplicate detections only when independent band runs reconstruct the same trace with the same centroid. It cannot prevent two changed reconstructions from landing in different cores, or both reconstructions from moving away from the original core. See [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1073). Ownership moreover uses the pre-split intensity-weighted `MassTrace` centroid, whereas emitted `Trace::mz` may be the apex, median, or mean in [`toTrace`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:275).

### Concrete example 1: drift exceeds the 20× halo

This demonstrates mechanisms **1 and 2** using the actual dynamic-standard-deviation implementation.

Use 21 consecutive spectra, constant IM, `mass_error_ppm=15`, `min_trace_length=0`, valley splitting off. The first peak has intensity 100; all later peaks have intensity 99. Starting at 1000, choose each next m/z to be the current running centroid plus `2.9 × current_sd`, so it is inside OpenMS’s `3 × sd` acceptance window:

```text
RT:  m/z
 0   1000.000000000
 1   1000.043500000
 2   1000.081433517
 3   1000.131502312
 4   1000.196457169
 5   1000.279153606
 6   1000.382592573
 7   1000.509935741
 8   1000.664510575
 9   1000.849811224
10   1001.069497614
11   1001.327393743
12   1001.627485634
13   1001.973919177
14   1002.370997951
15   1002.823181096
16   1003.335081252
17   1003.911462578
18   1004.557238855
19   1005.277471678
20   1006.077368719
```

Because every spectrum has one peak, the two-band quantile edge is sample element 10: `1001.069497614`, under the calculation in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1026).

The halos are approximately:

```text
lower-band upper limit = 1001.369818463
upper-band lower limit = 1000.769176765
```

The unbanded detector accepts all 21 points and produces a true intensity-weighted centroid of approximately `1001.784379570`, in the upper core. Neither band contains all 21 points. The lower band receives points 0–11 and can produce a different trace with centroid approximately `1000.460927687`; the upper band lacks points 0–8 and cannot reproduce the unbanded trace. No subsequent canonical sort can repair different memberships; the sort only normalizes ordering in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2538).

### Concrete example 2: a zero-span trace changes validity

This demonstrates mechanism **3** independently of drift.

Use two bands and these 13 spectra, all at the same IM:

```text
RT  m/z   intensity
0   1000  100
1   2000   11
2   2000   11
3   1000  110   <- first apex
4   2000   11
5   2000   11
6   1000  100
7–12 1500 11
```

With one peak sampled from every spectrum, the median quantile edge is 1500. The lower band’s upper halo is about 1500.45, so it includes the 1000 and 1500 spectra but omits the four 2000 spectra.

In the full map, the 1000 trace has three hits over seven adjusted scans: `3/7 < 0.5`, so [`MassTraceDetection::isTraceValid_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:445) rejects it. In the lower-band map, the four internal 2000 spectra do not exist because [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1068) only appends nonempty band spectra. The three 1000 spectra become adjacent in the sub-map, yielding quality `3/3`; the trailing 1500 misses are terminal and are subtracted by the OpenMS validity calculation. The identical zero-span trace is rejected unbanded and retained banded.

That destroys the proposition that a bound on final trace span alone establishes locality.

Finally, “no halo width can repair this” is literally too strong. A halo covering the entire window makes every band run on the whole map and is exact after core ownership—but it performs essentially N full detections. What does not exist is a useful finite halo derived solely from `mass_error_ppm`.

## 2. Can banding be made exact at all?

| Approach | Exact? | Cost and conditions | Verification |
|---|---|---|---|
| **(a) Halo from a real trace-span bound** | **Not from span alone.** Exact only if the bound covers the detector’s entire causal influence and reproduces full-map scan/miss semantics. | Running centroid and adaptive SD make the worst-case algorithmic bound approach the entire m/z range. A whole-window halo is exact but duplicates essentially all peaks and all MTD work N times. | Compare exact per-trace peak memberships and validity with `bands=1`, not just centroids. Include drift, competing-apex, missing-spectrum and threshold-boundary synthetic tests. |
| **(b) Partition at large m/z gaps** | **Not as stated.** A gap wider than every final trace is insufficient because unrelated peaks across the gap still determine whether a spectrum is “nonempty” and therefore whether a miss is counted. | It can be exact only with a proven separation of the complete interaction graph and faithful preservation of scan-presence semantics. Components may be extremely uneven or collapse into one component, defeating load balancing. Current sampled quantiles do not search for gaps; they deliberately target load balance in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1024). | For each proposed component, compare the detector’s peak-assignment partition and rejected traces against a full-window run. Test spectra populated exclusively by peaks in other components. |
| **(c) Detect the whole window** | **Yes.** This is the reference semantics. | It gives up the reduction in candidate population and within-window trace parallelism: approximately the stated 18 minutes/160 GB instead of 12:58/102 GB. It can still run different windows concurrently subject to memory admission. | Repeat `bands=1` for determinism, then make it the oracle for every optimization. Require exact trace membership and final semantic equality. |
| **(d) Declare banding approximate and pin it** | **No, but reproducible.** | Fix N and the edge algorithm independently of thread count. Different worker counts may schedule the same fixed tasks, but cannot change the scientific partition. “Independent of band count” is possible only by removing band count as a variable or making the algorithm genuinely exact. | Verify identical output across thread counts at fixed N, then publish N-versus-1 error measurements. |

The only straightforward exact implementations are whole-window detection or the degenerate whole-window halo. A useful gap partition might be exact, but the proof obligation is substantially stronger than “no final trace crosses the gap.”

## 3. What should the default and “auto” mode be?

The scientifically defensible default is:

```text
perf:trace_bands = 1
perf:ms1_trace_bands = 1
```

Both currently default to 12 and both use the same approximate wrapper in [`TOPPDIAPseudoSpectra::registerOptionsAndFlags_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:904). Banding MS1 is particularly capable of amplification because the resulting traces feed greedy precursor inference after canonical sorting in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2129).

**Thread-derived auto should not exist for scientific output.** The current MS2 auto mode reads `omp_get_max_threads()` and computes `ceil(threads/windows)` in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2366). That makes the input, parameters, and software insufficient to specify the result: the available machine changes N, and N changes the accepted-peptide set.

If approximate banding is necessary operationally, expose it as an explicit approximation preset with a fixed N—12 may be a reasonable performance default for that preset—and record the resolved N. Do not call it exact, and do not derive it from hardware.

There is also an inconsistency: MS1 value 0 is annotated as auto by the bound-setting comment, but is resolved to 1 rather than to a thread-derived count in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2030).

Under a build gate requiring accepted-peptide **set equality**, the effect is not “too small to matter”: any nonzero symmetric difference fails the project’s declared criterion. Evidence could justify an explicitly approximate performance mode, but it cannot restore the word “exact.”

## 4. How to measure the approximation error

Use one full `bands=1` run as the immutable reference and compare N = 4, 6, 12 and 25 against it. Do not rerun the 160-GB reference for every comparison.

The primary reported statistic should match the project gate:

\[
\text{peptide disagreement rate}
= \frac{|P_N \triangle P_1|}{|P_N \cup P_1|}
= 1-\text{Jaccard}(P_N,P_1)
\]

Report all of:

- `|P1 \ PN|`: peptides lost by banding.
- `|PN \ P1|`: peptides gained by banding.
- `|P1 ∩ PN|`, Jaccard, and net count change.
- The same quantities for accepted PSMs, using the identical search, competition and FDR procedure.

A net peptide-count delta is inadequate: equal numbers of losses and gains can conceal a large set disagreement.

At the trace stage, dump or hash exact trace membership before valley splitting: window, input frame, peak m/z, IM and intensity for every member. After optimal matching by member overlap, report:

- Fraction of reference traces with no exact membership match.
- Fraction of above-noise peaks assigned to a different trace or changed between assigned/unassigned.
- Jaccard distribution of member sets for changed traces.
- `|Δm/z|` in ppm, `|ΔRT|`, profile cosine/correlation and intensity change.
- All rates stratified by distance from the nearest N-specific band edge.

At the pseudo-spectrum stage, compare canonical full-spectrum hashes, then report coordinate-only additions/removals separately from shared coordinates whose complete peak lists or intensities changed.

The existing [`traceDigest_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:486) is only a tripwire. It sorts individual m/z, RT and intensity bit patterns together, omits IM and profile membership, and provides no magnitude or direction. The upstream compact-map digest in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2484) is useful for proving that every run started from the same picked peaks.

Because MS1 and MS2 have separate band parameters, measure them separately:

1. MS1 N versus 1 with MS2 fixed at 1.
2. MS2 N versus 1 with MS1 fixed at 1.
3. Both banded at the proposed production setting.

That distinguishes precursor-population changes from fragment-trace changes instead of reporting only their combined downstream effect.

## 5. Can parallelism be retained without the partition?

**Pipeline parallelism: yes. Equivalent within-window MTD parallelism: no, not under the “do not rewrite OpenMS” constraint.**

The current master/worker pool already provides exact parallelism across isolation windows in [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2440). Valley splitting and default precursor scoring also create independent tasks in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1115) and [`TOPPDIAPseudoSpectra::main_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2610). With `bands=1`, different windows can therefore be tracing, splitting and scoring concurrently.

But the task pool does not make one MTD call parallel. OpenMS’s trace detector still walks the intensity-ordered apex list serially through one shared visited set in [`MassTraceDetection::run_`](/Users/kohlbach/Claude/OpenMS-mzpeak-build/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:471). During a phase when every in-flight window is inside MTD, useful trace concurrency is capped by the number of admitted windows—at most the acquisition’s window count and possibly less under the memory gate.

Therefore the statement that bands are “no longer needed to fill cores” is only partly true. They are no longer needed to avoid the old rigid nested-team grid, but the band `taskloop` still creates the additional MTD work units in [`TOPPDIAPseudoSpectra::detectTraces_`](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1073). Removing it also removes within-window trace concurrency.

Practical exact choices without modifying OpenMS are limited to:

- One unbanded MTD task per window, with current heaviest-first and memory-bounded scheduling.
- Overlap whole-window MTD tasks with EPD and scoring tasks from other windows.
- For throughput rather than single-file latency, process independent input files concurrently.
- Reduce concurrent windows if the 160-GB path threatens memory; this sacrifices wall time, not correctness.

The measured superlinear benefit is algorithmic, not merely parallel: smaller bands reduce each MTD call’s candidate population. Consequently, there is no wrapper-level trick that simultaneously preserves whole-window semantics, per-band peak counts, current memory, and current speed. One of those properties must be surrendered.
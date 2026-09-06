• I've read `src/DIAPseudoSpectra.cpp` and the OpenMS `MassTraceDetection` source it calls (checkout at `~/Claude/OpenMS`, `src/openms/source/FEATUREFINDER/MassTraceDetection.cpp` — the patched tree this project builds against). Verdict up front: your hypothesis is **right, and understated**. There are at least three mechanisms you didn't list, one of which falsifies the help text's premise before your mechanism 1 even gets started.

  ## 1. Is the hypothesis right?

  Right, and incomplete. The measured N-dependence (digests differ at N=4/6/25) is overdetermined — several independent channels each suffice.

  **What you got right, with citations:**

  - **Running-centroid acceptance (your mechanism 2).** Confirmed exactly as you describe. The centroid is seeded from the apex (`MassTraceDetection.cpp:508-512`) and updated by intensity-weighted mean after *every* accepted peak (`processPeak_`, line 418). Acceptance is `candidate.mz ∈ centroid ± 3·ftl_sd` (`isPeakAcceptable_`, lines 355-356, 365-368). The walk is real.
  - **Non-locality (your mechanism 3).** Confirmed and worse than you state (see below).
  - **The empirical falsification.** Since the semantic digest changes with N, the "exact" claim in the help text (`DIAPseudoSpectra.cpp:909`) and the comments at `DIAPseudoSpectra.cpp:1020-1021` and `2380-2381` are empirically false regardless of which mechanism dominates.

  **What you missed — three additional mechanisms:**

  **(i) The help text's premise is off by 3× before drift is considered.** "Traces cannot span more than trace:mass_error_ppm in m/z" is wrong even for a single accepted peak: `ftl_sd` is initialised as `centroid_mz/1e6 · mass_error_ppm` (line 537) and the acceptance window is **±3·ftl_sd** (lines 301-302, 355-356). One step spans 3× ppm, not 1×. So the "20× halo" is really a 6.7-step-width halo, not a 20-step one.

  **(ii) `reestimate_mt_sd` defaults to `"true"` (line 34) and speXtractor never overrides it** (no `reestimate` or `trace_termination` anywhere in `DIAPseudoSpectra.cpp`). Every accepted peak re-estimates `ftl_sd` from the gathered peaks via `updateWeightedSDEstimateRobust` (lines 178-191, called at 440), and that update has **no cap tying it back to `mass_error_ppm`**. So the per-step acceptance width is itself a function of which peaks the band gave the trace. This is simultaneously a strengthening of your mechanism 2 (span bound is not just unbounded, it's not even expressible in ppm) and an independent instance of mechanism 3 (the window width differs between band counts on identical underlying data).

  **(iii) Global apex-order contention via `peak_visited`.** `run_` processes apices in *decreasing intensity* across the whole map (line 494 iterates `chrom_apices.crbegin()`) and claims peaks into one global `boost::dynamic_bitset peak_visited` (line 477); a visited peak is rejected for all later traces (lines 382-387). Banding forks that bitset per band (`DIAPseudoSpectra.cpp:1077-1081` — each band runs its own `MassTraceDetection`). Two apices in different bands whose traces reach the same halo-region peak are mutually exclusive in the unbanded run (higher-intensity apex wins) but **both claim it** in the banded run. This is the strongest of all the channels: it needs no drift, no pathological input, and fires entirely *inside* the halo, so **no halo width can fix it** — widening the halo enlarges the contested region.

  One correction to your framing, in the hostile spirit: you say `min_sample_rate` "terminates extension when occupancy drops." It doesn't in this configuration. Termination-by-sample-rate only happens in `trace_termination_criterion="sample_rate"` mode (lines 581-593, 635-647); the default is `"outlier"` (line 41; 5 consecutive misses, line 43), which speXtractor never changes. `min_sample_rate` is here only a *post-hoc validity filter* in `isTraceValid_` (lines 462-468). The comment at `DIAPseudoSpectra.cpp:987-990` is wrong about the code path actually taken. This doesn't weaken your case — a validity flip is still a band-dependent deletion — but get the mechanism right in the writeup.

  **Concrete examples:**

  *Example 1 — mechanism 2 (drift defeats any fixed multiple).* ppm = 20, apex at scan 50, m/z 500.000, intensity 1000. Initial `ftl_sd` = 0.010, window ±0.030. At scans 51-61, place one peak per scan at `centroid + 0.0295`, with intensity doubling each scan (2000, 4000, …). Each peak is inside its ±0.030 window (the σ re-estimation only widens it further as the walk spreads the points). The centroid moves ≈0.0197 per step; after 11 steps it sits ≈500.19-500.21, i.e. **past the 20× halo half-width of 0.200** (`DIAPseudoSpectra.cpp:1048-1049`). Put a band edge at 500.200 and the unbanded run keeps growing this trace while the banded run loses the later peaks — different trace, different centroid, possibly different core ownership. With constant instead of doubling intensity the walk is ≈0.0295·ln L, needing ~2400 scans to cross — slower, still unbounded. The point: **the span is not bounded by any multiple of ppm; 20 is a magic number and some magic numbers lose.**

  *Example 2 — mechanism 3(iii) (contention, fires inside the halo).* ppm = 20, edge at 500.100, halo ±0.200 (band A sees up to 500.300, band B down to 499.900). Spectrum at scan 101 contains one IM-eligible peak p at 500.110, intensity 5e5. Apex a (intensity 1e6) at 500.090, scan 100 → T_A's window covers p. Apex b (intensity 9e5) at 500.120, scan 102 → T_B extends down and its window covers p. **Unbanded:** a is processed first (higher intensity), claims p; when b's trace reaches scan 101, p is visited → miss → T_B has a gap, lower sample rate, different centroid. **Banded:** band B's private bitset lets T_B claim p; band A's run *also* claims p for T_A. Output: T_B differs in membership, centroid, and validity between N=1 and N=12 — and if T_A's banded centroid lands at 500.0999 while T_B's lands at 500.1001, the core filter at `DIAPseudoSpectra.cpp:1083-1088` keeps **both**, emitting a duplicated near-edge trace where the unbanded run had one. Note the core filter dedups only when both versions' centroids land in the *same* core; banding-induced centroid shifts near an edge defeat it.

  *Example 3 — mechanism 3 via validity flip.* Extend Example 2 so T_B visits 6 scans with 3 hits banded (rate 0.5, passes `isTraceValid_`, line 468) versus 2 hits unbanded (rate 0.33, rejected). A band boundary has now created/annihilated a trace wholesale. Valley splitting (`ElutionPeakDetection`, called at `DIAPseudoSpectra.cpp:1000-1011`) then amplifies whatever membership differences exist, since split points are computed from the gathered intensity profile.

  Minor fourth channel for completeness: `DIAPseudoSpectra.cpp:1080` skips any band with <3 spectra, deleting every trace whose core is in that band — band-count-dependent loss. Dense DIA fragments make it unlikely; it's still a channel the unbanded path (`:1096`) doesn't have symmetrically.

  ## 2. Can banding be made exact?

  **(a) Halo from a real span bound — no.** No a priori bound exists (running centroid + uncapped σ re-estimation). An empirical bound is circular: span measured at band count N is itself N-dependent. An adaptive fixpoint ("widen the halo until no kept trace's m/z extent touches a halo boundary") converges only on the *truncation* channel; Example 2 fires entirely inside the halo, so the fixpoint can certify nothing. Cost: reruns; verdict: still an approximation.

  **(b) Gap partitioning — conditionally exact, and this is the one worth building.** Cut only at gaps in the m/z distribution. Then ship a **runtime exactness certificate**: after tracing, verify for every trace that its inflated extent `[min_member_mz − 3σ, max_member_mz + 3σ]` does not cross any cut. If no trace's reach crosses a cut, no two traces in different bands can share a peak, the `peak_visited` interactions are disjoint, apex ordering across bands is irrelevant, and the banded output is *provably* identical to the unbanded run. Cost: cuts won't coincide with equal work, so you need bin-packing of gap-delimited segments into balanced bands; and in dense windows there may be no usable gap at all, forcing fewer bands (or N=1) there. Note the data may cooperate — your own comment at `DIAPseudoSpectra.cpp:1024-1025` says density varies by orders of magnitude, i.e. sparse regions exist. Verification: the certificate is cheap (one pass over output traces per window) and can be logged next to the existing span instrumentation at `:1139-1155`. Bonus: gap-derived band counts are **data-derived, not machine-derived**, which incidentally fixes your question-3 problem for this scheme.

  **(c) Whole-window detection, parallelise elsewhere — exact by construction.** N=1 *is* the reference semantics. Cost is real and measured by you: trace CPU rises superlinearly with band size (your own numbers at `:2505-2507`: 2,972 → 11,168 s going 24 → 5 bands; N=1 is worse), and window-level parallelism caps at 24. Mitigations inside the rules: heaviest-first scheduling and cross-window task stealing already exist (`:2440-2452`); push parallelism into the other ~51% of the loop. Verification: none needed.

  **(d) Pin N as a method constant — not exact, but deterministic.** Banding stays an approximation, but the output stops depending on the machine and on user whim. The error becomes a fixed, measurable property of the method (measured per section 4), like a random seed baked into a published pipeline. Cost: zero. Verification: golden digest in CI at the pinned N.

  My ranking: (b) if the gap analysis pans out, otherwise (c) for gated/scientific runs with (d) as the documented concession if the 30% wall-time price is genuinely unaffordable.

  ## 3. Default and "auto"

  **"auto" should not exist.** It resolves to `ceil(n_threads / n_windows)` (`DIAPseudoSpectra.cpp:2392-2393`): 5 bands on a 100-core box, 10 on a 224-core box. Since N changes the trace set (measured), auto makes the accepted-peptide set a function of the machine the run happened to land on. For a tool whose results are gated on peptide-set equality between builds, that is not a performance feature; it is a reproducibility bug with a help text. The comment at `:2338` ("canonically sorted, so output is thread-count-independent") is also false and should be corrected in the same pass — sorting fixes order nondeterminism, not set dependence on N.

  Default: pin a constant (12 is as good as any — it's what your measurements were taken at) and treat it as part of the **method definition**, documented alongside `trace:mass_error_ppm`, with release notes when it ever changes. Same treatment for `perf:ms1_trace_bands` (`:908`), which has the identical defect and whose help text copies the same false exactness claim. Remove 0=auto from both, or make 0 a hard error. And fix the three false comments (`:909`, `:1020-1021`, `:2380-2381`).

  ## 4. Measuring the approximation error honestly

  Reference: the existing unbanded path (N=1, `:1094-1097`) on the same input. One 18-min / 160-GB run per representative dataset, re-run only when the trace stage changes — not per commit.

  The comparison, in layers:

  1. **The gating statistic, first.** Accepted-peptide set symmetric difference between N=1 and N=12, reported as counts each direction and Jaccard distance. This is the number your gate cares about; lead with it.
  2. **Trace level, per window.** Match traces between the two runs (centroid within 3σ, RT-overlap ≥ 50%); report unmatched-fraction each way, the centroid Δppm distribution, and the member-set-identity fraction. This attributes error to windows (wide vs narrow tiles will differ).
  3. **Zero-cost incidence instrumentation, every run.** Extend the `span_log` block (`:1139-1155`) with per-window **m/z** extents: max trace extent vs the halo width (mechanism-2 incidence) and the count of traces whose ±3σ-inflated extent straddles a band edge (an upper bound on mechanism-3 exposure). Then every production run reports its own exposure instead of claiming exactness.
  4. **Cheap continuous guard.** You already emit per-window trace digests (`:2524`) and a precursor digest (`:2165`). On a small file where N=1 is cheap, wire "N=1 vs N=12 digest equality" into CI as the regression tripwire; if they diverge after a code change, you learn immediately rather than at the next 18-minute reference run.

  If the layer-1 number comes back at, say, <0.1% Jaccard with no systematic direction, I'd accept a pinned-N approximation as a documented method choice. If near-edge duplicated traces (Example 2) show up in layer 2 at non-trivial rates, pinning is not enough.

  ## 5. Parallelism without the partition

  Here is the uncomfortable part, stated plainly: **your banding speedup is not only parallelism — it is algorithmic work reduction, and the work it skips is exactly the work that made the output correct.** The measured CPU fall with more bands (`:2505-2507`) comes from giving each `MassTraceDetection` call fewer candidate peaks per apex; changing the candidate set is precisely what changes the output. So "keep the bands' cost profile and the unbanded semantics" is not available without rewriting OpenMS, which is off the table.

  What remains, in order of preference:

  1. **Gap-partition with certificate (2b).** Keeps most of the parallelism, eliminates the approximation *where the certificate holds*, and is machine-independent. Prerequisite measurement: the distribution of m/z gaps per window vs the p99 trace m/z extent (which 4.3 gives you). If dense windows lack usable gaps, they run with fewer bands and a logged certificate failure mode, and you know it from the log rather than from a digest diff three releases later.
  2. **Window-level parallelism only (N=1), buy back the tail.** With the task pool, the 24-window ceiling mostly hurts at the end of the run; schedule heaviest-first (you do) and let the tail's idle cores absorb the MS1 pass and EPD chunks. Pay the ~2-4× trace CPU as the honest price of exactness.
  3. **Pinned-N approximation (2d).** Keep the 12:58 / 102 GB profile, declare 12 part of the method, report the section-4 error budget alongside every benchmark. This is defensible *only* with the measurement done; without it, the help text is doing exactly what you said — claiming away an unmeasured error.

  One closing observation: the sentence in the help text has now been falsified three ways — analytically (±3σ per step, uncapped σ, running centroid), constructively (Examples 1-3), and empirically (your own digests at N=4/6/25). Whatever you choose among 1-3, the claim and its three echoing comments should not survive the week.


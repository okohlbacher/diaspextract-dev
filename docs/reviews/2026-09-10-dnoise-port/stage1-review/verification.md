
# sort-order

## [REFUTED/none] kimi #2: the prune takes the stride-97 edge sample after sortByPosition, while pre-change detectTraces_ sampled spectra 'as stored', so MS1 spectra not m/z-sorted at load (centroided mzML that skips pickIMCluster, or streaming) get different band edges with the prune on. Second-order claim: the band builder now takes the src_sorted lower_bound path instead of the old scan fallback.

EVIDENCE: PRE-CHANGE ORDER (the premise is a misreading). At HEAD cc39a66, spextractor.cpp:3909 `ms1_map.sortSpectra();` runs before the MS1 detectTraces_ call at 3972, whose sample loop is at 2458. In the stage-1 snapshot the same call is at 4048, before detectTraces_ at 4117. It sits in code shared by the streamed and resident paths, after both `if (!streamed)` blocks, and there is only one MS1 detectTraces_ call. OpenMS MSExperiment.h:1101 declares `sortSpectra(bool sort_mz = true)`. MSExperiment.cpp:792-803 sorts by RT, then calls `sortByPosition()` on every spectrum. So the old stride-97 sample was always taken from m/z-sorted spectra, on every path.

WHAT THE PRUNE CHANGES. Ms1Prune::frame (snapshot 1713) calls the same MSSpectrum::sortByPosition: MSSpectrum.cpp:405-421 returns early if is_sorted, otherwise stable_sorts an index vector and applies it with select (MSSpectrum.h:361-366). It runs on the same picked spectrum: between the pick and line 4048 no MS1 peak is changed ([ms1-hist] only reads; dispatch is a move). The sort is deterministic, so the permutation is the same. The value at each rank of a sorted sequence does not depend on how ties are ordered either, so the sample multiset is identical. `select(keep)` with ascending indices (MSSpectrum.cpp:21-55) returns a sorted subsequence, so after the change the sortByPosition at 4048 is a no-op. I also checked NaN m/z, the one case where is_sorted can be true on unsorted data: the chain never drops a NaN-m/z peak or the peak after it, so the prune cannot expose a hidden inversion.

SECOND-ORDER CLAIM. Before the change, `src_sorted = s.isSorted()` (HEAD 2497, snapshot 2613) was already true after sortSpectra. Both arms take the MZBegin lower_bound path; the scan fallback is not reached for MS1 in either.

REACHABILITY (also false by default). The mzML loader already sorts every spectrum by m/z: PeakFileOptions.h:241 `bool sort_spectra_by_mz_ = true`, MzMLHandler.cpp:146-148 `if (getSortSpectraByMZ() && !isSorted()) sortByPosition()`, and FileHandler.cpp:899-902 passes default options. The snapshot never sets PeakFileOptions. .d MS1 frames are sorted at BrukerTimsFile.cpp:1563 and 1604; picked frames at PeakPickerIM.cpp:1236, inside pickIMCluster, which starts at 992. mzPeak stable_sorts by m/z (MzPeakStreamLoad.h:239) and marks spectra IM_PROFILE, so they are picked. mzML is never streamed (snapshot 3733).

PROBE. I ran the stage-1 binary on ibminode05: provenance src_sha256 ca6880b3 matches the snapshot; binary sha 2990f23f. The input was check 19's fixture with every MS1 spectrum stored in descending m/z order, IM array in lockstep. In Python, the as-stored stride-97 sample, and the 2- and 48-band edges built from it, differ from the sorted ones, so the fixture can detect the claimed bug. Across bands 1/2/48 and prune off/on, nothing differed: semantic digest e497f850…, [ms1-edges] fnv (bands 2: 120710643281931212; bands 48: 3772659732559210863), [det] MS1 band spectra, MS1 traces, sorted traces and precursors. Descending input also gave exactly the ascending fixture's result, with the prune off and on.

Caveat: I could not force the pickIMCluster skip. MS:1003441 had no effect even with an obo overlay that defines it: 181 of 202 stored peaks were picked in every arm. The refutation rests on sortSpectra(sort_mz=true) at 4048 plus the loader sort, which the probe confirms end to end.

FIX: None required. Optional hardening: a comment at snapshot 4048 saying that sort_mz=true is what made the prune-off sample sorted. Changing it to sortSpectra(false) would make prune off and prune on sample different orders for any spectrum that arrives unsorted.

TEST: Extend e2e check 19 with a stored-order arm: write every MS1 spectrum in descending m/z order (IM array in lockstep) and assert, at bands 2 and 48, that the digest, [ms1-edges] and every [det] line match with the prune off and on, and match the ascending fixture. A ready version exists as /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/kimi2/probe.py, which passes on stage 1. This pins the whole pipeline (loader sort plus sortSpectra), not frame()'s own sort alone.

NOTES: Kimi #2 is refuted: detectTraces_ never sampled spectra 'as stored'. `ms1_map.sortSpectra()` (default sort_mz=true) ran before the MS1 call both before the change (HEAD cc39a66:3909) and at stage 1 (snapshot:4048). The mzML loader, the .d loader, the picker and the mzPeak loader also each sort MS1 spectra by m/z first. Kimi's own 'areas checked' section says edge-sample order is irrelevant and the multiset is identical; that is consistent with this finding and contradicts their finding #2.

Probe files:
- Local: /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/kimi2/probe.py, plus test_spextractor_stage1.py rebuilt from cc39a66 and the stage-1 diff (sha ec807c9b).
- Cluster: /scratch/kohlbach/verify_probe/kimi2/ holds a private copy of the stage-1 binary and libraries, probe.log, and probe_obo.log (the rerun with an obo overlay that defines MS:1003441). Nothing in the repo, the install or prune_gate was modified. The prune_gate chain had already finished (DRIVER_DONE 17:18) before I copied its binary.

Unresolved side observation, not needed for the verdict: an mzML spectrum carrying MS:1003441 still loses its duplicate peaks, 202 stored down to 181 picked, even when the obo defines the term. Either the IM_CENTROIDED branch (MzMLHandler.cpp:1539) is not reached for this fixture's cvParam, or something other than pickIMCluster merges the pairs. So the 'picker skipped' path kimi describes may be harder to reach from mzML than the brief assumes. Worth a look only if IM-centroided mzML input matters.

# stream-fallback

## [CONFIRMED/low] codex #3: if the stream load adds MS1 spectra to ms1_map and then fails, the resident fallback appends the whole run on top, and the stage-1 prune precondition (frames == ms1_map.size()) rejects the run

EVIDENCE: MECHANISM (snapshot spextractor.stage1.cpp)
- Only an Exception::BaseException falls back. FrameTableError is rethrown (3832-3837).
- ms1_map is filled only in flushMS1_, which runs the prune batch (1981), then ms1_.addSpectrum (1983). flushMS1_ is called every kBatchMS1_ frames (1938; default 256 via 2049-2059), at the first MS2 spectrum (1996) and in finish() (2014).
- The fallback calls only ms1_prune.reset(), and its comment admits the spectra stay (3871-3876). The resident dispatch then appends R more (3949-3955), the prune counts R frames (3945), and 4111 throws.

CONCRETE FAILING INPUT (cluster, stage-1 binary /scratch/kohlbach/prune_gate/bin/spextractor; its provenance src_sha256 ca6880b3... equals the snapshot)
- Input: dataset D .d cut to 1300 frames (100 MS1), with IsolationMz = 0 on the first window of group 1. Script: /scratch/kohlbach/verify_probe/c3/run.sh; logs in the same directory.
- Why only the stream fails: FullSwathFileConsumer::consumeSpectrum throws InvalidParameter for center <= 0 (OpenMS SwathFileConsumer.h:224-228). readDIAWindows (BrukerTimsFile.cpp:676-752) does not filter such windows, and resident loadDIA_ sets prec.setMZ(win->mz_center) and accepts them.
- r1, resident (-perf:stream_load false): exit 0, MS1 100 frames, 8599 MS1 traces, 176 spectra, digest 69f0a146.
- r2, SPEXTRACTOR_TILE_RESIDENT=1 SPEXTRACTOR_PICK_BATCH_MS1=1, prune on (default): '[stream] streaming load failed (InvalidParameter)'. Then 'MS1 200 frames / 6954832 peaks' (2 x 3477416), and exit 8 with '[ms1-prune] the pre-prune m/z sample covers 100 spectra ... but the MS1 map holds 200'.
- r3, resident, prune off: digest 69f0a146 (the prune changes nothing, as claimed).
- r4, the r2 trigger with prune off: EXIT 0, silently wrong. MS1 200 frames / 35616874 peaks, 14006 MS1 traces vs 8599, 367 spectra vs 176, digest c0f5af44.
- r6, IsolationMz = 0 in group 12, so groups 1-11 filled partial MS2 slabs first, prune off: compact store 10.5M peaks vs 5.8M, exit 8 with 'window frames are not in retention-time order'.
- r7, default config (streaming .d source): pass 1 (MS1 only) succeeds, then the pass-2 tile read fails fatally by design (4899), exit 6. The default .d config never reaches the fallback with this trigger.

PRE-STAGE-1
- Yes, a double-load bug already. cc39a66 has the same fallback, only without reset() and the precondition.
- Every stage-1 addition on this path checks ms1_prune.on (diff lines 199, 236, 302, 311, 335), so r4 and r6 are exactly the cc39a66 behaviour: silent corruption when only MS1 was delivered, loud when partial MS2 slabs exist.
- Stage 1 turns the silent MS1 case into a refusal, but its message recommends '-perf:ms1_prune false', which is exactly r4's silent path.
- The design note already raised this as an open question (understand/ms1-prune.md:318, 329).

EVERY WAY THE STREAM CAN FAIL AFTER MS1 IS IN ms1_map
(a) The FullSwathFileConsumer precursor checks (no precursor, or center <= 0). Stream-only; the fallback succeeds; reproduced above. Reachable only when MS2 is streamed: an mzPeak archive, or a .d with SPEXTRACTOR_TILE_RESIDENT=1. The default .d pass 1 streams no MS2.
(b) PeakPickerIM::pickIMCluster InvalidValue (PeakPickerIM.cpp:748-760) inside flushMS1_ or flush_. The resident pick runs the same code with the same parameters, so the fallback fails the same way.
(c) MSSpectrum::select Precondition on a float-array size mismatch (MSSpectrum.cpp:42-46) in the stream prune. The stream prunes every MS1 spectrum (1981), the resident path only spectra with IM data (3945). The .d reader does not produce such spectra.
(d) compactifyInto InvalidValue 'picked frame larger than its raw region' (887). MS2 only, and the picker never grows a frame.
(e) mzPeak decode InvalidValue (MzPeakStreamLoad.h:157-199, 398), after run(ms1) has delivered MS1. The fallback there is OpenMS MzPeakFile, which per project memory returns 0 spectra (not re-verified in this build). The run then exits at the IM check (3897-3902) before the precondition, with a misleading error.

Never trigger the fallback:
- opentims decode errors (std::runtime_error), SQLite::Exception, bad_alloc: not BaseExceptions, so they propagate.
- readDIAWindows and the frame-to-group mapping swallow SQLite errors.
- mzML input: openTimsDataHandle throws FileNotReadable before any spectrum, so nothing has been added and the fallback is clean. This is the only path the e2e suite takes.

STATE THE PARTIAL STREAM LEAVES THAT IS READ AFTER THE FALLBACK
1. ms1_map.
2. ms2_by_window: flush_ append plus FrameTab pads (1896-1919) and the finish() tail (2018).
3. cstat: stats_ += st (1887). It feeds the [compact] report (3970) and cstat.unmapped_frame > 0, which downgrades the integer detector (4612-4621). That changes behaviour, not just a log line.
4. ms1_prune: already reset.
5. Ledger LC_MS1MAP and LC_SLAB (SPEXTRACTOR_LEDGER only): added to at 1982/1923, only overwritten by the resident dispatch (3980).

Already safe:
- tile_source is reset (3840).
- run_tables and frame_table_src are assigned only after streamed = true.
- The consumer's buffers, frames_seen and tables_ die with it.
- cfg is used only by the loaders.
- ms1Hist_ and flush_wall_ are read only on success (3809-3819).
- lastDIAFrameTable is read only by the tablefn.
- The resident load() resets g_mz_calibration before it is stamped (4791).

FIX: At the top of `if (!streamed)` (snapshot 3871), before loadExperiment, discard everything the failed attempt produced:
  ms1_map = PeakMap();        // MSExperiment.h:113 lvalue move-assign
  ms2_by_window.clear();
  cstat = CompactStats();
  ms1_prune.reset();
  ledSet_(LC_MS1MAP, 0); ledSet_(LC_SLAB, 0);
Then reword the comment at 3873-3875 so it no longer says the spectra stay.

One-line alternative, arguably the better contract: in the BaseException catch (3833), add `if (consumer.frames_seen > 0) throw;`. This never falls back once a spectrum has reached the consumer, the rule already used for FrameTableError and for pass-2 tile reads. frames_seen == 0 exactly means nothing reached ms1_map, ms2_by_window, cstat or the prune. The resident fallback also silently ignores trace:native_ms1/ms2_neighbors (cfg is never passed to FileHandler).

TEST: The in-repo e2e cannot reach this: its mzML input fails to open as a .d before any spectrum is delivered, and the suite builds no .d or mzPeak input. Pin it with the cluster probe /scratch/kohlbach/verify_probe/c3/run.sh (dataset D first 1300 frames, IsolationMz = 0 on group 1 and on group 12).

With SPEXTRACTOR_TILE_RESIDENT=1 SPEXTRACTOR_PICK_BATCH_MS1=1 and both -perf:ms1_prune true and false, assert exit 0 and a spectrum digest equal to the -perf:stream_load false run (69f0a146, 176 spectra).

Today the prune-on run exits 8 (Precondition), the prune-off run returns 367 spectra (c0f5af44), and the group-12 run exits 8 (slab RT order).

If the refuse alternative is chosen instead, assert a non-zero exit whose log names 'Swath scan does not provide any precursor isolation information' and has no 'Split into MS1' line.

NOTES: Local copy of the probe driver: /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/c3_run.sh. Cluster outputs (g1.d/g12.d are mini tdf copies whose analysis.tdf_bin is a symlink to the raw dataset D .d; r1-r7 .log/.mzML): /scratch/kohlbach/verify_probe/c3/. No repo file was edited.

Severity is low because neither the default .d config nor mzML can reach the fallback in a state where it would succeed. Doing so needs streamed MS2 (SPEXTRACTOR_TILE_RESIDENT=1 or mzPeak) plus a failure only the stream path has. The consequence is still silent wrong output with prune off, and the stage-1 refusal message points users to exactly that setting. The mzPeak fallback outcome (OpenMS MzPeakFile returning 0 spectra) comes from project memory and was not re-checked in this build.

The first launch attempt did nothing: backgrounding a whole && list gives it /dev/null as stdin, so run.sh was written empty. It was relaunched correctly. A pgrep over ssh also matched its own command line; the anchored ps match avoided that.

# fixture

## [CONFIRMED/low] codex #6: e2e check 19 does not isolate the interior witness chain. Anchors and gap endpoints already keep every band alive, the negative control drops anchors too, and the assertion accepts 'traces differ OR bands differ'.

EVIDENCE: How it was tested. I built a mutant from the stage-1 snapshot (sha ca6880b3) with the in-tree g++-13 flags. In mode 0 it reproduces the stock stage-1 binary (/scratch/kohlbach/prune_gate/bin/spextractor, sha 2990f23f) on all 18 arms: two fixtures, bands 1/2/48, off/on/nowit, with identical [det], [ms1-edges] and [ms1-prune] lines.

1) SPX_VERIFY_PRUNE_MUT=1 removes only `keep.push_back(cand)` at candidate promotion (snapshot spextractor.stage1.cpp:1730). `last = cand` stays, so survivors, the first peak, gap far sides and the last peak are unchanged. Stage-1 c19, executed verbatim from test_spextractor.py:553-593, returned RESULT PASS. Its band vectors, traces (n=6) and precursors (n=2) at bands 2 and 48 equal prune-off.

2) Mode 2 (survivors plus first and last peak, no gap endpoints) FAILS at 48 bands. Bands 9-20 lose cycle 8's 400.2 gap far side (9 to 8, 21 to 20). So the fixture pins gap endpoints but not interior links.

Why links are never needed here. At 48 bands the edges are {0, 200, 300, 400.2, 450, MAX}. Every range that covers cycles 11-13's chain ([400.07994, 400.32006) and [400.07994, 450.135)) also holds that frame's first peak 400.2, which is always kept. At 1 and 2 bands the outer ranges [0, hi) and [lo, inf) always contain a frame's first or last peak whenever they hold any peak. So neither links nor gap endpoints can matter there; mode 1/2 band counts at 2 bands were identical on both fixtures.

3) NO_WITNESS (snapshot :1725) keeps survivors only, so it drops anchors and gap endpoints as well. On the stock binary it changes both signals: traces 6 to 7, precursors 2 to 3, bands 21,21 to 16,21 at 2 bands and minus 6 in bands 9-20 at 48 bands. The `or` at test :591 can therefore be `and`.

4) The output-mzML digest is blind to this fixture: e497f850308c in every arm, including the 7-trace / 3-precursor ones. Only the [det] lines detect the change.

5) A band model (verify_probe/c19/band_model.py) predicted every band vector the binary logged, exactly.

FIX: Code (one flag plus one line): add `bool no_chain` to Ms1Prune, set from SPEXTRACTOR_MS1_PRUNE_NO_CHAIN, parsed separately from NO_WITNESS whose `*e != '0'` test would swallow other values. At :1730 write `if (!no_chain) keep.push_back(cand); last = cand; cand = none;`. Add a matching NOT-identical suffix to the [ms1-prune] log.

Test: tighten :591 to `and`, and assert `n_nowit == n_off + 1` and `ms1_traces_near(tsv, 400.25) == [3]` (verified at 2 and 48 bands). Add a second input, prune_chain.mzML: synth(n_cycles=21), IM 0.80 for the edge peaks and 0.95 for trace and chain. Extras per cycle:
- cycles 0-5: (399.9, 150).
- cycles 15-20: (400.6, 150).
- cycles 6/10/14: (200.0, 50) and (400.25, 150 / 500 / 150).
- cycles 7-9 and 11-13: (200.0, 50) and a chain 399.70..400.80 in 0.05 steps at intensity 50 (23 peaks).

Why it works. The stride-97 sample is 200.0 x9, 399.9 x6, 400.6 x6. At 48 bands the core band of 400.25 is band 34, edges [399.9, 400.6), range [399.78003, 400.72018). In chain frames that range holds only promoted links 399.80..400.70. The anchors (first peak 200.0, gap far side 399.70, last peak 612.61) all lie outside it.

Asserts:
- For bands 1, 2 and 48, prune off and on give equal digest and equal traces, prec, bands and edges lines. No trace near 400.25 (3 hits in 9 scans).
- NO_CHAIN at 48 bands: survivors unchanged (141). Witnesses 81 fall to exactly 15 (9 first peaks plus 6 gap far sides). Edges line unchanged.
- NO_CHAIN band deficit is exactly 6 in exactly 26 bands and 0 elsewhere.
- NO_CHAIN traces 6 to 7, and ms1_traces_near(400.25) == [3].

The block is verify_probe/c19/c19b_proposed.py. Bump `total` by 1.

TEST: Proposed c19b (scratchpad verify_probe/c19/c19b_proposed.py), verified on the cluster:
- Correct prune with the NO_CHAIN control (mutant mode 0): PASS.
- Links omitted everywhere (mode 1): FAIL, 'bands 48: traces differs … n=6 … n=7'.
- Mode 2: FAIL.
- Stock stage-1 binary, which lacks the control: fails only at the control assert (witnesses 81 -> 81).

Plus the tightened nowit `and` assert in c19.

## [PARTLY/low] kimi #5: the streaming-side prune (PickCompactConsumer::flushMS1_ -> Ms1Prune::batch) has no in-repo e2e coverage; kimi proposes reusing check 18's synth_tdf + SPEXTRACTOR_MZPEAK_TDF machinery.

EVIDENCE: The gap is real.
- With perf:stream_load true (the default), an mzML input still builds the consumer (:3721). The code then calls BrukerTimsFile().loadDIAStreaming on the mzML (:3806), which throws before any frame is delivered.
- All 36 probe arms logged '[stream] streaming load failed (FileNotReadable); falling back to loadExperiment' and 'Loaded 42 frames'.
- So e2e reaches only the resident path, a single batch() call over exp (:3945). The prune in flushMS1_ (:1981) and batch's cross-call `at = sample.size()` offsets (:1742-1755) never run in e2e.
- The pass-2 consumer (:4887) carries no prune.

The proposed remedy does not work.
- synth_tdf (test :137-171) writes only MzCalibration, Frames(Id, T1, MzCalibration) and GlobalMetadata. There is no analysis.tdf_bin and no frame or window tables.
- SPEXTRACTOR_MZPEAK_TDF is only a calibration/flight-time-axis candidate path (:3686, :4587).
- The .d streaming source requires FileTypes::BRUKER_TDF (:3733).
- mzPeak streaming (:3801) would reach flushMS1_, but MzPeakStreamLoad.h:114-119 refuses anything but an ims-compact archive (a point.tof column with mzpeak:transform_params). The repo ships only the reader, and neither the repo nor the cluster has a writer; the only archive is the real S30 one.

It is harness-only today, and it is covered there. data7-ms1-prune.md records D .d streamed prune off/on at 8c1b047f: 1,343 MS1 frames give 6 flushMS1_ batches at kBatchMS1_ = 256, so the cross-batch path ran.

Another verifier's ad-hoc input (/scratch/kohlbach/verify_probe/c3/g1.d: a real analysis.tdf trimmed to 1,300 frames with the vendor tdf_bin symlinked) runs the streamed prune in seconds and logged '[ms1-prune] … sample 183647 m/z from 100 spectra'. It shows a cheap cluster gate is feasible, but it rests on a non-redistributable vendor file.

FIX: No e2e test is possible without a redistributable .d or an ims-compact mzPeak writer.

1) Say so explicitly: in the check-19 comment and the test docstring, note that mzML input always takes the resident path and that the flushMS1_ prune is gated on real data only.

2) Add a cluster-only gate to the verify/publish chain. Take a trimmed .d (the Frames/DiaFrameMsMsInfo cut used in verify_probe/c3, without the zeroed window). Run it streamed with SPEXTRACTOR_DET=1 and SPEXTRACTOR_PICK_BATCH_MS1=7 (many batches with an uneven tail), -perf:ms1_prune false vs true, same build. Assert equal [ms1-edges] fnv, [det] MS1 band spectra, [det] MS1 traces and precursors digests, plus the semantic digest.

TEST: None in-repo (harness-only): the D .d prune off/on semantic digest 8c1b047f, plus the proposed trimmed-.d streamed arm pair at SPEXTRACTOR_PICK_BATCH_MS1=7.

NOTES: I edited no repo files. Probe files are in /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/c19/, mirrored in /scratch/kohlbach/verify_probe/c19/ on ibminode05:
- make_mutant.py: asserted single-hit replacements that turn the snapshot into the mutant.
- build_mut.sh: in-tree flags from flags.make and link.txt.
- probe_c19.py: runs c19 verbatim, the proposed block, or per-arm probes.
- band_model.py, chain_fixture.py, c19b_proposed.py, run_mut.sh.
- test_stage1.py: the stage-1 test, rebuilt as cc39a66 plus the test hunk of stage1_tracked.diff.

The working-tree test file has moved on since stage 1 (a check 20 was added), so I did not use it.

The mutant binary is /scratch/kohlbach/verify_probe/c19/spextractor_mut. It was built against the cc39a66 MzPeakStreamLoad.h and TdfLoad.h, because the in-tree headers changed at 17:43 (TdfLoad.h now includes DnoiseMs1.h). Its mode 0 matched the stock stage-1 binary on all 18 off/on/nowit arms.

Two points for whoever writes the fix:
(a) The digest(on)==digest(off) assert in c19 cannot see this fixture's MS1 changes: the output hash was e497f850308c in every arm. Keep SPEXTRACTOR_DET on in these arms; the [det] lines are the only sensors.
(b) At 1 and 2 bands, neither gap endpoints nor interior links can ever affect band membership, so the chain control is only meaningful at 3 or more bands. At 48 bands a check must place a band range strictly inside a sub-threshold chain, away from the edge-setting first peaks.

# memory

## [PARTLY/medium] kimi #6: select() releasing capacity is asserted, not shown; if it does not shrink, the 20 B/peak ledger understates the pruned MS1 map

EVIDENCE: The conclusion is right, but the mechanism and size are wrong. select() is not in-place: it reallocates. In the built tree (ibminode05:/scratch/kohlbach/OpenMS/src/openms/source/KERNEL/MSSpectrum.cpp), line 25 `tmp.reserve(indices.size())` plus the swap at 33 leave the peaks right-sized. Every data array, however, reserves the OLD size: line 49 `mda_tmp_float.reserve(float_data_arrays_[i].size())` then swap at 54, and likewise 71 (string) and 93 (int). So the Ion Mobility array keeps capacity n. The slack is 4 B per PRUNED peak, not 20-25 B. The prune-off map has no slack at all: PeakPickerIM.cpp:1223-1226 calls shrink_to_fit on both the peaks and im_data.

Probe against the in-tree libOpenMS.so (g++-13, /scratch/kohlbach/verify_probe/select_openms.cpp):
- select(108,000 of 540,000): peaks usable capacity 108,031; IM capacity 540,000, size 108,000.
- 96 frames in a raw -> pick -> prune pattern, 8 threads: ledger 197 MiB. malloc in-use is 356 MiB with select vs 198 MiB with select + shrink_to_fit. RSS after malloc_trim(0) is 387 vs 221 MiB, so the slack is resident (carved from recycled arena memory), not virtual.

Real data (prune_gate D_off / D_on, same build), malloc in-use minus ledger at the end of LOAD:
- D: 1,122 MiB off vs 3,492 MiB on, a difference of +2,370 MiB. Predicted: 4 x (725,116,915 - 140,081,167) = 2,232 MiB of IM slack + 87 MiB of sample capacity = 2,319 MiB.
- dnoised pair: +44 MiB measured vs 36 + 5 MiB predicted.
- The D delta also grows with the loaded fraction at the pick peaks: 776 / 1,486 / 1,895 / 2,370 MiB, against 542 / 1,103 / 1,694 / 2,232 MiB predicted.

Consequences:
- The pruned D map really holds 16K + 4P = 4,904 MiB, not the 2,671 MiB in the ledger, the [ms1-prune] log line and data7-ms1-prune.md. The map shrinks 2.8x, not 5.2x.
- The D pass-1 peak row (ledger rss 22,994 MiB at t=29.27, 76% loaded, during the pick of the last full batch) carries about 1.7 GiB of this slack. D's run peak (loop2, 26.49 GB) is not directly moved.
- TNBC (4,797 frames, P = 2.39 G): 4(P - K) = 7.4-7.8 GiB, held from each flush until the distribution's s.clear(true) frees it (MSSpectrum.cpp:170/177). That is the MS1 phase, which spextractor.stage1.cpp:2664-2666 records as TNBC's 13-tile process peak. The true TNBC pruned map is about 14.6-16.0 GiB vs a ledger of 6.8-8.6 GiB.
- The design note understand/ms1-prune.md (lines 20, 149, 289: 'select rebuilds peaks and float arrays into right-sized buffers') is wrong at MSSpectrum.cpp:49.
- Output is unaffected.

FIX: At spextractor.stage1.cpp:1737:
`if (keep.size() != n) { s.select(keep); for (auto& a : s.getFloatDataArrays()) a.shrink_to_fit(); for (auto& a : s.getIntegerDataArrays()) a.shrink_to_fit(); for (auto& a : s.getStringDataArrays()) a.shrink_to_fit(); }`

This costs a momentary +4k-byte copy per frame. Also correct the comment: select right-sizes the peaks but its data arrays keep the old capacity (MSSpectrum.cpp:49). Fix the data7 table and the log's 'MB as PeakMap' figure to match.

TEST: Add `im_slack` to Ms1Prune::Counts: the sum of FloatDataArray capacity() - size() after the prune (the peak capacity cannot be read, because MSSpectrum.h:41 inherits std::vector<Peak1D> privately). Print it in the [ms1-prune] line and assert `im_slack 0` in e2e check 19, whose fixture frames do run select().

Real-data gate on D: prune-on (arena - free - ledger ms1_map) at '[stream] frame-by-frame load done' must be at most the prune-off residue + sample capacity + 150 MiB. Today it is +2,370 MiB; about +90 is expected after the fix.

## [CONFIRMED/medium] codex #7 (capacity sub-claim): the inline code does not establish that OpenMS select() releases capacity; 'right-sized buffers' is unverified

EVIDENCE: Same evidence as kimi #6. The claim is not only unverified, it is false for the data arrays: MSSpectrum.cpp:49/71/93 reserve the pre-select size. Only the Peak1D container is right-sized (lines 25, 33).

The libOpenMS probe gives IM capacity 540,000 after keeping 108,000 peaks. On D the measured excess is +2,370 MiB of malloc in-use at the end of LOAD vs 2,319 MiB predicted. This is the material part of codex #7; the transient part is small (next entry).

FIX: Same one-liner as for kimi #6: shrink_to_fit every data array after s.select(keep) at spextractor.stage1.cpp:1737, and correct the 'right-sized buffers' comment.

TEST: Same as kimi #6: assert `im_slack 0` in the [ms1-prune] line in check 19, plus the D end-of-LOAD in-use-vs-ledger gate.

## [PARTLY/low] codex #7 (transient sub-claim): frame() builds an index vector even for all-survivor frames, select() transiently holds more than 2x the spectrum, and batch() concurrency multiplies it (plus sample.resize)

EVIDENCE: The mechanisms are real:
- `std::vector<Size> keep` grows by push_back with no reserve (spextractor.stage1.cpp:1716-1735), so its capacity rounds up to a power of two. Probe: 131,072 for 108,000 entries; 1,048,576 for 540,000.
- It is built even when keep.size() == n and select is skipped (line 1737).
- Inside select, the old peaks and old IM array live until return, while the new peaks (16k B) and a new IM array reserved at the OLD size (4n B) are alive. Extra over the frame's 20n is E = 8*P2(k) + 16k + 4n, where P2(k) is the next power of two >= k.
- batch() is an `omp parallel for` over the whole 256-frame batch (lines 1751, 2049-2059), so up to 100 frames are in flight.

Magnitude at defaults is small:
- D (n = 539,923; measured k = 0.193n = 104,305): E = 1.00 + 1.59 + 2.06 = 4.65 MiB per frame, so 465 MiB at 100 threads = 2.0% of the 22,994 MiB pass-1 peak.
- TNBC (n = 498,574; k about 75-94k): 4.0-4.3 MiB per frame, 404-433 MiB total.
- dnoised D: about 76 MiB.

Worst cases need a lowered trace:noise_threshold_int or dense survivor frames:
- k = n-1: 18.3 MiB per frame (2.8x the 10.3 MiB frame including the original), 1,830 MiB on D (8.0%), 1,351 MiB on TNBC.
- k = n: select is skipped, but the keep growth still peaks at 12 MiB per frame, 1,200 MiB on D, for zero saving.

For scale: the pick step in the same flush adds about 6 GiB of uncharged in-use (D_on ledger 25.63 -> 26.89 s: 5.9 -> 11.5 GiB). After the batch, the buffer drops from 2.64 GiB to 0.93 GiB (0.51 GiB with the shrink fix), so bounding concurrency is not warranted.

sample.resize (line 1748) grows as size + max(size, add):
- D: 87 MiB capacity for 57 MiB of data, 130 MiB during the last reallocation.
- TNBC: 321 MiB capacity for 188 MiB, 482 MiB transient.
Small, as codex says.

FIX: Count first. Factor the chain loop into a lambda taking a sink:
1. `kept = chain(count_only)`
2. `if (kept == n) { c.picked += n; c.kept += n; return; }` (the sample is already written, and the frames/sample_n accounting is unchanged, so the precondition still holds)
3. `keep.reserve(kept); chain(push)`

Optional: skip select when n - kept < n/16. That is still output-identical, but 'kept' then means 'retained'. No change to sample and no concurrency bound.

TEST: Output identity is already pinned by check 19 (prune on/off digests at 1/2/48 bands). Add a check-19 arm with -trace:noise_threshold_int 0, so every frame is all-survivor, asserting digest equality with prune off and `kept == picked` in [ms1-prune]. That exercises the skip path.

NOTES: No repo file was edited. Probes:
- ibminode05:/scratch/kohlbach/verify_probe/select_openms.cpp (g++-13, linked to /scratch/kohlbach/OpenMS/build/lib/libOpenMS.so)
- /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/select_mimic.cpp (Apple clang / libc++ transliteration: same capacities)

Measured data came from scratchpad/tiles/prune_gate/{D_off,D_on,DN_off,DN_on}/{e.log,ledger.tsv}. The '22,994 MiB' figure is ledger rss_mib at t=29.27 s, during the pick of the last full 256-frame batch; the charged sum there is only 6,262 MiB.

Key finding: MSSpectrum::select right-sizes the peaks but keeps every data array's old capacity (MSSpectrum.cpp:49/71/93). The prune therefore leaves 4 B per pruned centroid allocated and resident:
- D: 2,232 MiB, confirmed by +2,370 MiB of malloc in-use over the ledger at the end of LOAD.
- TNBC: 7.4-7.8 GiB, predicted.

The documents that state 'right-sized' or report the ledger map as the real map need correcting:
- data7-ms1-prune.md: 'MS1 map 2,671 MiB', 'map ... shrink 5.2x'
- understand/ms1-prune.md fact at line 289
- the comment at spextractor.stage1.cpp:1737

The transient part of codex #7 is real but about 2% of the D pass-1 peak at defaults. Since TNBC prune-on is unmeasured (data7 still has the TNBC_PRUNE_GATE_ROWS placeholder), the TNBC figures are arithmetic from the recorded picked/≥100 counts. The witness count W is unmeasured there, so they are given as the range between survivors only and the witness ceiling.

# header-robustness

## [REFUTED/none] codex #5 / kimi #1 / vibe #2 -- __cpp_lib_to_chars does not reliably indicate floating-point std::from_chars (libc++ fallback dead, GCC 8-10 compile break, CI 'both paths' illusory)

EVIDENCE: Every library checked defines the macro only where floating-point from_chars exists, so the #if picks the right branch.
- libstdc++ 13 (cluster /usr/include/c++/13): <charconv>:48-50 and <version>:91-93 define the macro only when float and double are IEEE (and size_t is at least 32 bits). The float/double/long-double from_chars declarations at <charconv>:668-679 use a wider guard, `defined __cpp_lib_to_chars || _GLIBCXX_HAVE_USELOCALE`, so the macro implies the overload.
- GCC 11.1: <charconv> and <version> define the macro under `#if _GLIBCXX_HAVE_USELOCALE`, the same guard as the floating declarations.
- GCC 10.5: the define is commented out behind '// FIXME: Define when floating point is supported'. GCC 9.5 and 8.5 have no macro and no floating overloads. GCC 8-10 therefore take the #else stream branch, which compiles; the claimed compile break does not exist.
- libc++ (Apple clang 21, SDK 26.5): <version>:374 has the define commented out, and :606 has `# undef __cpp_lib_to_chars` with a commented define. A probe shows the macro undefined at -std=c++17 and -std=c++20, so the stream fallback is the live path on macOS and the header comment at :223 is right.
- libc++ availability: floating from_chars carries _LIBCPP_AVAILABILITY_FROM_CHARS_FLOATING_POINT, which is LLVM 20, i.e. macOS 26.0 (availability.h:141, 371-372). It compiles at the default target arm64-apple-macosx26.0.0. At -mmacosx-version-min=15.0 it fails with "'from_chars' is unavailable: introduced in macOS 26.0". kimi's `!defined(_LIBCPP_VERSION)` idea is unnecessary; forcing from_chars on libc++ would be the actual break. libc++ already gates availability-dependent feature macros (<version>:430 gates __cpp_lib_format on TO_CHARS_FLOATING_POINT).
- MSVC STL: current yvals_core.h defines __cpp_lib_to_chars 201611L for C++17 as the P0067R5 marker. No Windows host, not probed.
- CI matrix (tests.yml at HEAD): ubuntu-latest gcc, ubuntu-22.04 gcc-11 and windows msvc compile the from_chars branch; macos-latest AppleClang compiles the stream branch. Both branches do run in CI.
- Correct rounding: a 270,000-string corpus with Python float() as oracle, normal range, including exact binary64 midpoints and +-tiny perturbations up to 1,053 chars. libc++ stream, libc++ from_chars, glibc/libstdc++-13 stream and libstdc++-13 from_chars each gave 0 mismatches and 0 failures. The result is the same under a de_DE.UTF-8 C locale, where plain strtod("99.990834") returns 99.
- The branches differ only outside the normal range:
  - "1e-999": libstdc++ from_chars refuses; libc++ stream sets failbit; libstdc++ stream returns 0 without failbit.
  - "1e-320": from_chars accepts on both libraries; libc++ stream sets failbit.
  - "2.2250738585072011e-308": libc++ stream sets failbit; the others accept.
  So acceptance of subnormal and underflowing strings is platform-dependent today (see the codex #1 verdict).

FIX: None needed for the macro. Simplest robust path, verified: use one classic-locale istringstream path everywhere. Drop the `#if defined(__cpp_lib_to_chars)` branch and the conditional <locale>/<sstream> include; keep <charconv> for parseU32. Replace the post-parse check with a rule that does not depend on the library: track in the grammar scan whether any mantissa digit is non-zero, then `const double a = std::fabs(v); if (in.fail() || (mantissa_nonzero ? !(a >= DBL_MIN && a <= DBL_MAX) : v != 0.0)) return false;` (needs <cfloat>). A copy of the header with this change passes the existing test_dnoise_ms1 on Apple clang 21 and g++-13, and accepts and refuses identical sets on libc++ and glibc. MSVC's stream path (UCRT strtod) was not probed.

TEST: test_dnoise_ms1.cpp parse block. Add "1e-999", "-1e-999", "1e-320" and "2.2250738585072011e-308" to the must-fail list. Add {"0e999",0.0}, {"-0",-0.0}, {"2.2250738585072014e-308",DBL_MIN} and {"1.7976931348623157e308",DBL_MAX} to the accept list. With the current code "1e-320 must fail" passes on macOS but fails on Linux and MSVC, so the test pins the cross-platform consistency. The existing halfway cases stay.

## [CONFIRMED/low] codex #1 / kimi #7 -- parseF64 refuses inf, nan and out-of-range literals that Rust's f64::from_str accepts, contradicting the bit-identity contract

EVIDENCE: - Rust (rustc 1.96 probe; dnoise pins 1.97.1; the float parser is unchanged since the 1.55 rewrite):
  - "inf", "+inf", "INF", "Infinity" and "iNfInItY" give inf.
  - "nan", "NaN", "-nan" and "+nan" give NaN.
  - "1e999" and "1.7976931348623159e308" give inf.
  - "1e-999" gives 0, "-1e-999" gives -0, "1e-320" gives a subnormal (bits 0x7e8), "2e-324" gives 0.
  - Rejected: "infinit", "nan(1)", " 1", "1 ", "0x10", "1_0", ".", "1e" and "1e+".
  - Otherwise the grammar matches the port's pre-check: "+1.5", "1.", ".5" and "1E5" parse.
- dnoise: timsrust metadata_reader.rs parse_value errors only on a parse Err, and writer.rs build_dia_ms1_gate uses whatever value comes back. dnoise therefore completes a run with a degenerate gate. Example: MzAcqRangeUpper "1e999" gives tof_slope = inf, t0 = t1 = 0, TOF box [0,0], and every MS1 point gated out.
- The port refuses inf/nan spellings through the grammar (DnoiseMs1.h:203-216) and overflow through from_chars ec, failbit or isfinite (:221, :229, :231).
- Underflow and subnormals are handled differently per platform (probe):
  - "1e-999" is refused on the cluster (libstdc++ from_chars out_of_range) and on macOS (libc++ stream failbit).
  - The libstdc++ stream path would accept it as 0.
  - "1e-320" is accepted on Linux and MSVC (from_chars) and refused on macOS (stream).
- The header admits the divergence only in the function comment (:200). The file-level contract (:15, 'BIT-IDENTITY') and GateBuild::error (:241, 'dnoise refuses the run here') are unqualified.
- Reachability: spextractor.stage1.cpp does not include DnoiseMs1.h (0 grep hits), so at stage 1 this affects only the tests. Bruker writes values like "0.600000" and "99.990834", and the D and TNBC metadata are all normal-range, so real files never hit it.

FIX: Keep the refusal, document it, and make it the same on every platform; do not emulate Rust, since dnoise's gate from such values is noise.
1. :15 contract: add 'for GlobalMetadata values that are finite decimal literals equal to zero or of magnitude in [DBL_MIN, DBL_MAX]. A value dnoise would parse otherwise (inf/infinity/nan in any case, overflow to inf, underflow to 0 or a subnormal) makes the port refuse the run where dnoise builds a degenerate gate.'
2. :241: 'non-empty: the run is refused here -- timsrust MetadataReader errors, or a metadata value is outside the port's finite-decimal domain'.
3. Enforce the domain with the explicit range rule from the __cpp_lib_to_chars verdict: `in.fail() || (mantissa_nonzero ? !(a >= DBL_MIN && a <= DBL_MAX) : v != 0.0)`. That makes "1e-999", "1e-320" and "1e999" fail on libc++, libstdc++ and MSVC alike. Verified identical on libc++ and glibc.

TEST: test_dnoise_ms1.cpp:
- Refuse list: add "1e-999", "-1e-999", "1e-320", "2.2250738585072011e-308", "INF", "-nan" and "Infinity".
- Accept list: add "0e999", "-0", "2.2250738585072014e-308" and "1.7976931348623157e308".
- Add a buildMs1WindowGate case with D's metadata but one_over_k0_acq_range_lower = "1e-999": expect gate empty and error == "GlobalMetadata OneOverK0AcqRangeLower '1e-999' is not a finite number".

## [CONFIRMED/low] codex #2 -- contraction guards do not cover reassociation, reciprocals, finite-math or excess precision; parseF64/asU32 NaN handling is unguarded (is #error on __FAST_MATH__ plus FLT_EVAL_METHOD != 0 a sound guard?)

EVIDENCE: The snapshot unit test, which pins D's 24 gate boxes, breaks under several flag sets.

Fails:
- Apple clang 21 -O2 -ffast-math (with or without -ffp-contract=off): 'D box 9: scans [0,604] want [0,605]', box 13, and others.
- clang -O2 -ffp-model=fast: 4 FAIL lines.
- clang -O2 -freciprocal-math -ffp-contract=off: 3 FAIL lines.
- clang -O2 -ffinite-math-only: 'FAIL line 223: asU32 is Rust's saturating as u32', i.e. NaN no longer maps to 0.
- g++-13 -O3 -ffast-math (with or without -march=x86-64-v3): 'D box 2: scans [543,943] want [542,943]', box 4, and others.
- g++-13 -O3 -funsafe-math-optimizations -ffp-contract=off: D boxes 9 and 13.
- g++-13 -mfpmath=387 at -O2 or -O0, even under strict -std=c++20 (excess-precision=standard): D boxes 2 and 4. This is codex's excess-precision point on real data.

Passes:
- clang or g++ with -fassociative-math -fno-signed-zeros -fno-trapping-math alone.
- g++ -freciprocal-math alone and g++ -ffinite-math-only alone.
- g++-13 -O3 -march=x86-64-v3 -std=gnu++20, and clang -O2 at its default contraction: the existing contraction guard works.

So the claim at :35-36, 'whatever the including translation unit's flags', is false.

The proposed guard is sound but incomplete:
- No false positives: it compiles under clang -O2 and -ffp-contract=on, and under g++-13 -O2, -O3 -march=x86-64-v3 and gnu++20. The cluster OpenMS build has CMAKE_CXX_FLAGS empty and Release '-O3 -DNDEBUG'; compiler_flags.cmake adds only -ffp-contract=off for GNU and Clang.
- It fires as intended for -ffast-math, -Ofast and clang -ffp-model=aggressive (__FAST_MATH__), and for g++ -mfpmath=387 (__FLT_EVAL_METHOD__ 2).
- It misses three configurations that do break the boxes. Clang -ffp-model=fast and -freciprocal-math define neither macro. g++ -funsafe-math-optimizations does not define __FAST_MATH__.
- -ffinite-math-only alone defines only __FINITE_MATH_ONLY__=1.
- FLT_EVAL_METHOD stays 0 under clang -ffast-math, so it only catches x87.

On codex's helper claim: asU32 and parseF64 lie outside the GCC region, but they contain no a*b+c, so contraction is irrelevant. Finite-math genuinely breaks asU32 on clang. parseF64's std::isfinite at :231 folds away under finite-math, but it is redundant: range errors are already caught by ec or failbit, and no parse test failed under clang -ffinite-math-only. Moving the helpers into the region would not help, because the pragmas do not restore NaN semantics.

codex's 2^53 counterexample is arithmetically right (strict gives [1,2], reassociated gives [0,3]), but the D box flips above are the real-data evidence.

Severity: no current build (CI defaults, cluster flags) uses these flags, and the stage-1 tool does not include the header. The failure is silent, though: a single -Ofast or -ffp-model=fast moves 2-4 gate boxes by one scan.

FIX: Verified on a header copy with Apple clang 21 and g++-13.
1. After the includes: `#include <cfloat>` plus `#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__) || defined(_M_FP_FAST) || (defined(FLT_EVAL_METHOD) && FLT_EVAL_METHOD != 0)` / `#error "DnoiseMs1.h needs strict IEEE binary64: no -ffast-math, -ffinite-math-only, /fp:fast or x87 excess precision"` / `#endif`.
2. :249 becomes `#pragma GCC optimize("fp-contract=off", "no-unsafe-math-optimizations")`.
3. After :250 add `#if defined(__clang__)` / `#pragma float_control(precise, on, push)` / `#endif`. Before :319 add `#if defined(__clang__)` / `#pragma float_control(pop)` / `#endif`. Keep the in-function `#pragma clang fp contract(off)`: precise mode sets contraction to 'on', and the function-scope pragma overrides it.
4. Reword :35-36 to 'contraction, reassociation and reciprocal rewrites are switched off for the builder; flags that cannot be switched off (fast-math, finite-math, x87) are refused at compile time'.

Results with the fix: the test passes at default flags, clang -ffp-model=fast, clang -freciprocal-math, g++ -O3 -funsafe-math-optimizations and g++ -O3 -march=x86-64-v3 -std=gnu++20. It stops at the #error on both compilers under -ffast-math and -ffinite-math-only, and on g++ under -mfpmath=387. MSVC _M_FP_FAST is unprobed; MSVC could also take `#pragma float_control(precise, on, push)` at file scope.

TEST: - CI arms that build test_dnoise_ms1 with clang `-O2 -ffp-model=fast` and gcc `-O3 -funsafe-math-optimizations`; both must pass, which pins the pragmas.
- A CMake check_cxx_source_compiles, with CMAKE_REQUIRED_FLAGS=-ffast-math, on `#include "DnoiseMs1.h"` plus int main(){}; it must FAIL, which pins the #error. Repeat with -mfpmath=387 on x86-64 GCC.
- The existing D-box and asU32 checks are the detectors; they already fail under every breaking configuration listed.

## [CONFIRMED/low] codex #4 -- denoiseMs1Frame bounds: num_scans + 1 wraps at SIZE_MAX, scan UINT32_MAX + 1 wraps at num_scans = 2^32, point-count check comes after keep.assign

EVIDENCE: - num_scans = SIZE_MAX (probe oob_probe.cpp): iterations = 0 skips streakPass, whose stamp.assign(SIZE_MAX) would otherwise throw length_error. With halo on and one point at scan 0, the scan check at :453 passes. :495 `w.row.assign(num_scans + 1, 0)` becomes assign(0), and :496 `++w.row[w.scan[j] + 1]` indexes row[1].
  - ASan, fresh Scratch: 'SEGV on unknown address 0x000000000008 ... DnoiseMs1.h:496'.
  - ASan, Scratch reused after a valid frame: 'container-overflow ... READ of size 8 ... DnoiseMs1.h:496'.
  - Plain -O2: 'Bus error' (exit 138).
- num_scans = 2^32: scan UINT32_MAX passes :453. `w.scan[j] + 1` is unsigned-int arithmetic, so it counts in row[0] instead of row[2^32]. After the prefix sums cursor[UINT32_MAX] = row[UINT32_MAX] = 1, and :505 writes htof[1] while m = 1: an out-of-bounds write. Analysis only; not run, because it needs at least 64 GiB on a shared node.
- Point count: :447 keep.assign(n, 0) runs before the n > 2^32-1 check at :449. An oversized n allocates at least 4 GiB before the documented invalid_argument, or throws length_error instead. Wasteful, not UB.
- Reachability: the stage-1 tool never calls the function. The live integration passes fr.num_scans, a std::uint32_t (TdfLoad.h:152), so num_scans <= 2^32-1 and both wraps are unreachable from the tool. dnoise's own num_scans comes from scan_offsets.len()-1 (frame.rs:25); real frames have about 1,000 scans. This is public-API hardening.

FIX: At the top of denoiseMs1Frame, replacing lines 447-449:
`if (n > std::numeric_limits<std::uint32_t>::max()) throw std::invalid_argument("dnoise: more than 2^32-1 points in one frame");`
`if (num_scans > std::numeric_limits<std::uint32_t>::max()) throw std::invalid_argument("dnoise: more than 2^32-1 scans in one frame");`
`keep.assign(n, 0);`
`if (n == 0) return c;`

Why this suffices: num_scans <= 2^32-1 bounds every scan at 2^32-2, so `w.scan[j] + 1` at :496 cannot wrap, and `num_scans + 1` <= 2^32 cannot wrap in a 64-bit size_t. OpenMS is 64-bit only; a 32-bit port would need `>= UINT32_MAX` instead. Update the doc comment at :440 to mention the num_scans limit.

TEST: In test_dnoise_ms1.cpp, call denoiseMs1Frame directly with p.iterations = 0 and the halo on, using one point {scan 0, tof 5, I 1}:
- num_scans = std::numeric_limits<std::size_t>::max() must throw std::invalid_argument.
- num_scans = std::size_t(1) << 32 must throw std::invalid_argument.
Both must throw before any allocation, so the test stays cheap. Also check that n = std::size_t(UINT32_MAX) + 1 with the same 1-element arrays throws invalid_argument and leaves `keep` untouched, proving the check precedes keep.assign and the read loop.

NOTES: No repo file was edited. All work used the stage-1 snapshot or copies of it. Two things the reviewers did not raise:
1. Metadata values that underflow or are subnormal are accepted on some platforms and refused on others today. For example, "1e-320" is accepted by from_chars on Linux and MSVC and refused by the libc++ stream path on macOS. The range rule proposed under codex #1 makes every library refuse the same set.
2. The contraction guard already holds under g++-13 -O3 -march=x86-64-v3 -std=gnu++20 (FMA hardware, GNU contraction default) and under Apple clang's default. That is evidence for kimi #3 and vibe #1, which were not assigned to me.

Probe sources and results:
- Mac, /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/:
  - parse_probe.cpp: from_chars vs stream, edge cases, corpus mode and de_DE locale mode.
  - rust_parse.rs: Rust f64::from_str semantics.
  - gen_corpus.py and corpus.txt: 270,000 correct-rounding cases with Python float() as oracle.
  - oob_probe.cpp: the ASan out-of-bounds case.
  - guard_probe.cpp: which flags trip the proposed #error.
  - clangpragma/: header copy with float_control(precise).
  - fixed/DnoiseMs1.h and fixed/edge.cpp: the header with all proposed parse, guard and pragma fixes, which passes the unit test on both toolchains.
- Cluster, ibminode05:/scratch/kohlbach/verify_probe/:
  - Copies of the same probes.
  - gcc_no-unsafe-math-optimizations/ and gcc_no-fast-math/: header copies with the GCC pragma variants.
  - fixed/: the same fixed header.
Toolchains: g++-13.3.0 with libstdc++ 13 and glibc on the cluster; Apple clang 21 with libc++ from SDK 26.5 on this Mac.
Web sources: gcc-mirror tags releases/gcc-8.5.0, 9.5.0, 10.5.0 and 11.1.0 for <charconv>, plus the 11.1.0 <version>; microsoft/STL main yvals_core.h. The MSVC claims are from that source only; nothing ran on MSVC.
Line numbers refer to the snapshot DnoiseMs1.h.

# prune-misc

## [REFUTED/none] vibe #3: the streaming prune takes every spectrum in ms1_buf_ (true) but the resident prune takes only containsIMData() && MS level 1, so a spectrum without IM data could make the two paths differ in output or in the frames/sample accounting

EVIDENCE: Each predicate is exactly its own path's dispatch, which the frames/sample precondition requires.

Streaming path:
- OpenMS FullSwathFileConsumer::consumeSpectrum sends only MS level 1 to consumeMS1Spectrum_ (SwathFileConsumer.h:194-196), so no other MS level can enter ms1_buf_.
- flushMS1_ then adds every buffered spectrum to ms1_ unconditionally (snapshot 1983), so `take = true` (1981) matches that dispatch.

Resident path:
- The dispatch adds only containsIMData() && getMSLevel()==1 (3951-3954), and the predicate at 3945 is the same test.
- The prune cannot flip containsIMData(): select() swaps only the vector base, so the array name survives. Check 19 runs exactly this path with the prune on, and the check at 4111 would throw otherwise.

Spectra without IM data do reach ms1_buf_:
- BrukerTimsFile.cpp:1194 (frameToSpectrum) and :1241 (centroidMS1Frame) return on num_peaks==0 before the IM array is pushed (1223/1274). Those frames are still handed over (1614).
- On real data, den.d (dnoised D, a prune gate input) has 2 of 1343 MS1 frames with NumPeaks=0 (python sqlite3 on the cluster). The raw S30/S08/S23 files have 0.
- mzPeak drops empty spectra and always attaches the IM array (MzPeakStreamLoad.h:235, 245).

On an empty spectrum, Ms1Prune::frame does nothing: sortByPosition is a no-op, n=0, no sample, no select. It only adds 1 to frames and 0 to sample_n, so output and accounting are unchanged.

Vibe's fix would break a real input. Streaming den.d would count frames=1341 against ms1_map.size()=1343, and the Precondition at 4111 would refuse the run.

Separately, and not caused by the prune: the streaming map keeps these empty spectra while the resident map drops them.

FIX: none. Do NOT apply vibe's predicate change: it turns every streamed .d with an empty MS1 frame (den.d) into a Precondition failure. At most add a comment at 1981 and 3945 that each take predicate must equal its own path's dispatch.

TEST: The existing cluster gate (prune OFF vs ON on dnoised D den.d, which streams 2 empty MS1 frames with no IM array) should assert no [ms1-prune] Precondition and an equal semantic digest. The e2e suite cannot stream a synthetic .d: synth_tdf is only a calibration table.

## [PARTLY/low] vibe #5: NaN m/z is not handled in Ms1Prune::frame; reach() is false for NaN, so a NaN peak is dropped unless first, last or a survivor, which could corrupt the band partition

EVIDENCE: Vibe's mechanism is a misreading, but NaN m/z does break prune-on/off identity by another route, shown with a concrete input.

Why the mechanism is wrong: a NaN peak is never dropped. With reach() false it falls through to the 'far side of a gap' keep (1741), and the peaks immediately before and after it are kept too. In the probe, 400,000 of 400,000 and 799,751 of 799,751 NaN peaks were kept.

The real route:
- is_sorted compares adjacent pairs only, so a spectrum with a NaN in the middle still counts as sorted. The band builder then takes the MZBegin path (2613, 2629-2630), a lower_bound with PositionLess (MSSpectrum.cpp:206-211).
- The NaN makes `elem < hi` non-partitioned, so where lower_bound lands depends on the spectrum's length, which the prune changes.

Concrete input (identical result with libc++ and g++-13 libstdc++; model at verify_probe/nan_prune.cpp):
- Peaks, sorted as stored: (400.048,50) (400.065,500) (NaN,50) (400.107,50) (400.126,50) (400.153,50) (400.189,500).
- Settings: noise 100, 15 ppm, edges {0, 399.8080898, 399.98654, DBL_MAX}.
- The prune drops 400.126 and 400.153.
- In the last band (hi = +inf), lower_bound lands at index 7 in the unpruned spectrum but at the NaN (index 2) in the pruned one.
- Survivor 400.189 therefore reaches MassTraceDetection with the prune off and not with it on.

Probe totals:
- 1 NaN per spectrum: 29,661 existence and 122,987 survivor mismatches in 1,199,856 band checks.
- NaN-free control: 0 of 1,199,991.

Keep or drop:
- Keeping the whole spectrum whenever any m/z is non-finite gives 0 mismatches (nan_prune_fix.cpp).
- Dropping NaN peaks inside the prune alone is unsafe, because the prune-off arm still has them.

Reachability:
- Not from .d: m/z comes from the calibrated TOF.
- Only from malformed mzML:
  - NaN in the m/z array of an MS:1003441 IM-centroided spectrum (MzMLHandler.cpp:1539), which skips the pick (3934/1962).
  - In a profile-IM spectrum: an +inf intensity gives out_mz = inf/inf = NaN, and a NaN m/z point joins its neighbour's cluster, because std::min/max(finite, NaN) return the finite value, which makes the centroid NaN (PeakPickerIM.cpp ~1113-1190).

With the prune off, such input is already unreliable: the NaN also enters the stride-97 edge sample. std::sort with a NaN depends on input order, and prune-on concatenates the sample in arrival order while prune-off uses RT order after sortSpectra. Those differ only for mzML not ordered by RT or with RT ties.

FIX: Minimal fix, restores identity (probe-verified):
- In Ms1Prune::frame, compute `const double x = s[i].getMZ();` for every peak and track `fin = fin && std::isfinite(x)`.
- Finish with `if (fin && keep.size() != n) s.select(keep);`.
- When !fin, charge c.kept += n and count a bad_mz counter for the [ms1-prune] log.

More robust fix, also cleans the edge sample: drop MS1 peaks with non-finite or <= 0 m/z right after picking, before [ms1-hist], the sample and the prune. Do it in both flushMS1_ and the resident loop, regardless of perf:ms1_prune, as compactifyInto/compactify already do for MS2 (893, 919). This changes output only for corrupt input.

TEST: Add a check-19 arm to test/test_spextractor.py:
- Mark the MS1 spectra of the synthetic mzML with MS:1003441, so they reach the prune in stored order.
- Put one NaN m/z (struct.pack('<d', nan)) in the middle of the dense sub-threshold peaks, below a survivor near the top band.
- Assert digest(prune on) == digest(prune off) and equal [det] MS1 traces/band-spectra lines at -perf:ms1_trace_bands 2 and 48.
- It fails on the stage-1 code and passes with the fix.

## [PARTLY/none] kimi #8: reach() `x <= m + hop * m` is FMA-contractible where spextractor.cpp is compiled without -ffp-contract=off (claimed: the in-tree OpenMS build, MSVC); benign given the factor-2 margin

EVIDENCE: Contractible only where no flag is passed, and a 1-ulp change cannot cross the margin, so prune-on vs prune-off identity holds. Kimi's in-tree premise is wrong, and its secondary reason is wrong too.

Codegen probes:
- AppleClang 21 on arm64, -O2 with no flag, emits `fmadd d0,d0,d2,d2` for reach(). With -ffp-contract=off it emits fmul+fadd.
- g++-13 at -O3 -march=x86-64-v3 or -march=native emits vfmadd132sd.
- g++-13 with -mssse3 (the in-tree flags) or with -ffp-contract=off emits mulsd/addsd.

The premise is false for the cluster in-tree build: /scratch/kohlbach/OpenMS/build/src/topp/CMakeFiles/spextractor.dir/flags.make has `-O3 ... -mssse3 ... -ffp-contract=off`, from OpenMS cmake/compiler_flags.cmake:104 (GNU) and :134 (Clang). Those flags are PRIVATE per target but are applied to this TOPP target. The project CMake adds the flag for GNU/Clang/AppleClang (CMakeLists.txt:21), and MSVC /fp:precise does not contract. The remaining exposure is a hand build outside both CMake files.

Margin probe (verify_probe/margin.cpp), same result locally and with g++-13:
- Setup: narrowest band (edge[b] == edge[b+1]); left kept peak = the largest double below lo; farthest reachable peak = the reach bound.
- All four fused/unfused combinations of the band builder's lo/hi and of reach: 0 failures in 2M edges per ppm, for ppm from 50 down to 5e-12.
- Minimum slack between the farthest reachable peak and hi: 1.35e12 ulps at 15 ppm, 91 at 1e-9, 2 at 1e-11. At 1e-12 ppm h rounds away and reach becomes exact equality.
- Contraction moves the bound by at most 1 ulp.

The secondary reason fails because reach() runs only with the prune on. The factor-2 margin is what makes it safe.

FIX: none

TEST: none

NOTES: All probes, read-only (no repo files edited), in /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/:
- nan_prune.cpp: a verbatim model of Ms1Prune::frame, the band builder with a MZBegin lower_bound, and MassTraceDetection's '> noise' filter. The NaN-free control shows 0 mismatches.
- nan_prune_fix.cpp: the same model with the whole spectrum kept when any m/z is non-finite.
- margin.cpp: the kimi #8 margin probe.
- reach.cpp: the codegen probe.
The same files were run on ibminode05 under /scratch/kohlbach/verify_probe/ with g++-13 -O3 -mssse3 -ffp-contract=off (libstdc++), with identical results.

Empty MS1 frames were counted with python sqlite3 (the cluster has no sqlite3 CLI): den.d has 2 of 1343; raw S30, S08 and S23 have 0. The review brief records no prune on/off run on den.d, so the empty-frame case is covered by the code path argument, not by a recorded gate.

Unrelated to the prune: the streaming path keeps empty MS1 spectra without an IM array in ms1_map, while the resident path drops them.

# refutation-candidates

## [REFUTED/none] kimi #4: Ms1WindowGate::fromBoxes folds a box whose scan range lies entirely past the last scan onto the last scan instead of dropping it

EVIDENCE: The description of the behaviour is accurate, but it is exactly what dnoise does, so it is not a defect under the bit-identity contract.

1. dnoise source, checked out at tag v0.1.0 (git describe v0.1.0, commit fa750c92, the same commit named at DnoiseMs1.h:7). dia_ms1.rs:48-56:
```
if b.tof_hi < b.tof_lo { continue; }
let lo = b.scan_lo.min(num_scans as u32 - 1);
let hi = b.scan_hi.min(num_scans as u32 - 1);
for s in lo..=hi { per_scan[s as usize].push(..) }
```
The only skipped box is one with tof_hi < tof_lo; a box starting past the last scan is clamped to lo == hi == num_scans-1 and added there. The doc comment at :41 says "boxes are clamped into 0..num_scans".

2. The builder has the same asymmetry in both codebases.
- dnoise writer.rs:1008 leaves scan_lo unclamped and :1009 clamps scan_hi to num_scans-1; :1020 builds the gate.
- The port matches: DnoiseMs1.h:311-312 (builder) and :134-136 (fromBoxes, including the tof skip).
- The wrapping i64-as-u32 row cast is ported too (tdf/mod.rs row cast; DnoiseMs1.h:264).

3. The case is already pinned by a test.
- test_dnoise_ms1.cpp:168-170 builds {150,200,10,20} over 100 scans (scan_lo 150 > 99). It asserts contains(99,15) && !contains(98,15) && !contains(100,15), with the message "a box past the last scan is clamped onto it".
- The fuzz loop also covers it: num_scans = 1+below(40) (:579), box scans below(50), gate size num_scans+below(3) (:613-616), all compared against the transliteration.

Adding kimi's `if (b.scan_lo >= num_scans) continue;` would make the port diverge from dnoise on exactly this input.

Real-world reach: it needs a DiaFrameMsMsWindows row whose padded scan range starts at or past MAX(NumScans). On D and TNBC 009 every box's scan_lo is below 944/918 (pinned boxes). Either way, both tools do the same thing.

FIX: none

TEST: Already present: tests/test_dnoise_ms1.cpp:168-170 (the {150,200,10,20}/100-scan clamp) plus the random-gate fuzz at :579/:613-616. Optionally cite dia_ms1.rs:52-53 in the CHECK message.

## [REFUTED/none] vibe #4: the prune over-keeps a sub-threshold peak that starts a new chain after an unbridgeable gap (i.e. out of reach of the last kept peak, no candidate pending)

EVIDENCE: That gap anchor is required for exactness.

**Concrete counterexample** (probe verify_probe/vibe4_band.cpp; prune logic copied from spextractor.stage1.cpp:1711-1738, band range from :2618-2638).
- Settings: noise 100, trace:mass_error_ppm 15, so hop = 15e-6*20 = 3e-4 (:3657).
- Frame: 400.0/1000, 400.05/50, 400.08/1000, 500.0/50, 600.0/1000.
- Run-sample edges: {0, 499.9, 500.1, DBL_MAX}. Edges are quantiles of the whole run's sample, so any m/z can be an edge.
- Band 1 range is [499.75003, 500.25003) and contains only 500.0, the sub-threshold gap anchor.

Results:
| Arm | Kept peaks | Band-1 spectrum for this frame |
|---|---|---|
| Unpruned | all | present (0 work peaks) |
| Shipped prune | 400, 400.08, 500, 600 (drops 400.05) | present |
| vibe's stated intent (keep sub-threshold peaks only within reach of a kept peak, or first/last) | 400, 400.08, 600 | absent |

An absent band spectrum removes a scan that MassTraceDetection counts toward min_sample_rate. That is condition (ii) in ms1-prune.md, and e2e check 19's no-witness control shows it changes output.

**Brute force** (verify_probe/witness_nogap.py): exec's witness_lemma.py's generator, edges and band model verbatim, same seed.
- Shipped chain: 0 of 360,968 band checks mismatched (reproduces the lemma).
- No gap anchor: 27,720 mismatches. 13,914 are with sample-derived (realistic) edges and 13,806 with adversarial edges; all are presence-only, i.e. identical work peaks but a missing spectrum.
- No witnesses at all: 37,119.
- 1,958,028 gap anchors were dropped.
- First realistic failure: ppm 5, 3 bands, range [214.38, 589.39) holding only sub-threshold peaks.

**Proof.** P4's invariant (ms1-prune.md:202) says a peak is dropped only while it is within reach of the previous kept peak k_L. A peak out of reach of k_L cannot be dropped, because a band range can start after k_L(1+hop) and still contain it.

**vibe's own code** (vibe.md:62-67), completed and run, keeps 500 anyway: it defers the peak and emits it at the next out-of-reach peak. So the proposed fix is a no-op on this frame, and implementing the stated intent breaks identity.

**Real-world relevance.** Large in-frame m/z gaps are common in sparse wash frames and especially in dnoised MS1 frames, where the window gate removes out-of-window points. The anchor is kept by design.

FIX: none

TEST: Pinned by the brute force: witness_lemma.py, plus witness_nogap.py as a sensitivity arm (27,720 mismatches). When the planned C++ Ms1Prune property test is written, add the 5-peak frame above with edges {499.9, 500.1} as a named negative-control case (dropping the anchor must remove the band-1 spectrum). e2e check 19 already asserts that missing band spectra are observable (no-witness arm).

## [REFUTED/none] vibe #1: the volatile only protects scan_slope*scan; the later additions, fmax and divisions for s0/s1 can still be fused under -ffp-contract=fast, so every intermediate needs a volatile

EVIDENCE: **What contraction can fuse.** Contraction only merges a multiply with an add or subtract (FMA/FMS/FNMA/FNMS: GCC's convert_mult_to_fma, LLVM's `contract` flag, AllowFPOpFusion). There is no fused division, sqrt or fmax, and -ffp-contract=fast does not allow reassociation.

**Every shape in buildMs1WindowGate (DnoiseMs1.h:288-312):**
- tof_slope, scan_slope, t0/t1: sqrt, subtract and divide only.
- s0/s1 = (fmax(im0,im1)+pad-intercept)/slope: add, subtract, divide, no multiply. Nothing to fuse.
- The halo compare (:525) multiplies inside a comparison, with no add.
- The only other multiply-add shape is mz_lo/mz_hi = isolation_mz ∓ isolation_width/2.0. Both compilers rewrite /2.0 as *0.5 (exact reciprocal), and GCC then fuses it. That product is exact, so a fused result equals the unfused one bit for bit (except for subnormal widths). It cannot change output.

**Disassembly with only the volatile guard, under -ffp-contract=fast:**
- g++-13 x86 (-march=native, host has FMA), drv_volatile: exactly 2 FMA instructions in buildMs1WindowGate, at ffc8 `vfnmadd132sd` and ffcd `vfmadd132sd`. The factor is the constant at 0x117c0 = 0x3fe0000000000000 (0.5), the operands are WindowRow+0x10/+0x18 (isolation_mz/width), and the result then has Params+0x58 (mz pad) subtracted.
- drv_none (unguarded) has those 2 plus the im0/im1 fusions at fdf4/fdfe (`cvt(scan)*slope + intercept`).
- g++-16 arm64 smoke: `fmov #0.5; fmsub; fmadd` on the same operands.
- AppleClang 21 volatile-only: 0 fused ops.

**Measured output.** With only the volatile, D's boxes 11/15/16 stay at [0,583]/[0,547]/[428,943] in every build tried:
- g++-13 x86 driver on the dnoise oracle: 0 of 2,020,547 kept points differ on 24 frames, 0 on frame 8724.
- Unit test: passes on g++-13 x86, g++-16 arm64 and AppleClang 21 arm64, at default and fast.
- Unguarded header: 49 points in 12 frames differ.

Wrapping every intermediate in a volatile would protect nothing more.

FIX: none (optional: one comment line in DnoiseMs1.h noting that isolation_width/2.0 may be fused and is exact)

TEST: Existing D-box pins at tests/test_dnoise_ms1.cpp:130-141 (boxes 11/15/16). Verified to fail with the unguarded header on g++-13 x86 -march=native, g++-16 arm64 and AppleClang 21 arm64, and to pass with the volatile alone.

## [REFUTED/low] kimi #3: the contraction guards are unproven where they are the only guard; volatile-alone sufficiency is asserted, not measured; the GCC optimize pragma may no-op; the in-tree OpenMS build gets neither flag

EVIDENCE: **Volatile alone, measured on the cluster** (/scratch/kohlbach/dnoise_port on ibminode05; host g++ 13.3.0, fma=1).
- run_D.sh:27 builds drv_volatile with `g++ -O3 -ffp-contract=fast -march=native -Ig_volatile`.
- g_volatile/DnoiseMs1.h differs from the shipped header (sha 6a4d474e, equal to the snapshot) only by removing both pragma lines (:249 and :257) plus a comment. The removals are made with make_aux.py's asserted single-occurrence replacements.
- run_D.log, 'volatile' arm: boxes 11/15/16 at [0,583]/[0,547]/[428,943]; 24 frames, 2,020,547 kept, 0 mismatching points; frame 8724: 0 mismatches.
- 'none' arm (negative control): boxes at 582/548/429; 49 mismatching points in 12 frames, 13 on frame 8724.

**GCC pragma, not a no-op.** The 'pragma' arm (pragma kept, volatile removed) gives 0 mismatches, and drv_pragma contains 0 FMA instructions in the builder.

**My fresh runs of the unit test on the cluster** (g++-13 -O3 -ffp-contract=fast -march=native):
| Header | FMA instructions | Result |
|---|---|---|
| g_volatile | 2 (the exact /2.0 ones) | OK |
| g_pragma | 0 | OK |
| g_none | 4 | FAIL :124/:139 |
| shipped | 0 | OK |

**arm64** (hdr_smoke.cpp with D rows 11/15/16, and the unit test copied into a directory without a header, so the ablation header is actually used):
- AppleClang 21 and g++-16, at default, =on and =fast: volatile-only is correct in every case. g_none fails in every case.
- clang pragma-only fails under explicit -ffp-contract=fast, and so does the old port/hs_pragma binary. On clang the volatile is therefore the sole effective guard there, and it is measured sufficient.
- The port/hs_*/hsg_* binaries reproduce these results.

**In-tree OpenMS build.** The cluster build of SpeXtractor is in-tree: /scratch/kohlbach/OpenMS/build/src/topp/CMakeFiles/spextractor.dir/flags.make has `-O3 -std=gnu++23 ... -mssse3 ... -ffp-contract=off`. OpenMS cmake/compiler_flags.cmake adds -ffp-contract=off itself (:104 GNU, :134 Clang), and -mssse3 has no FMA instructions. So that build gets the flag and cannot contract at all. MSVC/clang-cl are not project targets.

**What remains (low severity).** Stage-1 CMake gives test_dnoise_ms1 `SPX_NO_FP_CONTRACT` (stage1_tracked.diff:42), and baseline x86-64 cannot emit FMA. So portability CI never exercises the header guards alone; the proof above lives only in scratch probes. kimi's suggested CI arm is cheap and worthwhile, but it is not needed to establish that the guard works.

FIX: No code change to the guards. Optionally add one ctest variant of test_dnoise_ms1 compiled WITHOUT ${SPX_NO_FP_CONTRACT} and with -ffp-contract=fast (plus -mfma on x86). On AppleClang arm64 this build already fails if the volatile is removed, because the clang pragma is ignored under explicit fast. It then pins the volatile alone in CI instead of in /scratch probes.

TEST: tests/test_dnoise_ms1.cpp:130-141 compiled at -O3 -ffp-contract=fast without the CMake flag. It fails with the volatile removed on AppleClang 21 arm64 (pragma present but ignored), on g++-13 x86 -march=native, and on g++-16 arm64 with both guards removed. It passes with the volatile alone.

NOTES: **Probe artefacts** (all in scratchpad/verify_probe/ and /scratch/kohlbach/verify_probe/ on ibminode05; no repo file touched):
- vibe4_band.cpp: the concrete band counterexample.
- witness_nogap.py / witness_nogap.out: brute force with a no-gap-anchor arm, same seed as witness_lemma.py.
- guard_matrix.sh: arm64 smoke across compilers, contraction settings and guards.
- bin/ut2_*: arm64 unit-test ablations.
- ut13_* (cluster): g++-13 unit-test ablations.

**Probe pitfall (bears on kimi #3's recommended CI arm).** The snapshot's test_dnoise_ms1.cpp sits next to a copy of DnoiseMs1.h. Its `#include "DnoiseMs1.h"` searches the including file's directory before -I, so my first local ablation built against the shipped header. Those results were discarded; I re-ran with the test copied into a directory without a header. The repo layout (tests/ with no header, header in src/) and the cluster dnoise_port layout do not have this problem. Any CI ablation job must not place a header copy next to the test.

**Cluster facts.** There is no clang on ibminode05, so clang evidence is arm64/AppleClang 21 only. The cluster in-tree build uses gnu++23 with -mssse3 and OpenMS's own -ffp-contract=off. Even with every guard removed, the shipped cluster binary could not contract.

**Kimi #4.** The source was verified at tag v0.1.0 (fa750c92), not against the dnoise binary with a doctored window table. The source is authoritative for this pure-function path, and the port's transliteration fuzz shares it.

# build-and-omp

## [PARTLY/low] kimi #9: tests/test_dnoise_ms1.cpp is built and registered only under SPEXTRACTOR_TESTS_ONLY, so the primary build that ships never compiles it

EVIDENCE: The narrow fact holds, but the impact is overstated and the proposed fix targets the wrong build.

What is true:
- CMakeLists.txt:29-42 adds test_dnoise_ms1 and add_test(dnoise_ms1) only inside if(SPEXTRACTOR_TESTS_ONLY), which ends in return().
- The full path (lines 44-73) builds only spextractor.

Why the impact is overstated:
1. At stage 1 nothing ships the header. spextractor.stage1.cpp does not include DnoiseMs1.h at all (grep 'Dnoise|dnoise' finds nothing). No header edit can reach a shipped binary.
2. The test already runs on every push and PR. tests.yml runs ctest on gcc, gcc-11, appleclang-arm64 and msvc.
3. The repo's full CMake path is only used by build.yml (weekly cron, v* tags, manual dispatch). That workflow has no ctest step. Registering the test in the full path would build it but never run it.

The cluster build never sees the repo's CMakeLists.txt:
- spextractor is registered in /scratch/kohlbach/OpenMS/src/topp/executables.cmake:28, with an mzPeak block in src/topp/CMakeLists.txt:72-84.
- scripts/sync_cluster.sh copies only spextractor.cpp, TdfMzCalibration.h, TdfLoad.h and MzPeakStreamLoad.h, then runs make spextractor.
- find /scratch/kohlbach/OpenMS -maxdepth 4 -iname '*dnoise*' finds nothing.
- So kimi's fix never reaches the binary that is deployed.

Registering the test anywhere needs no OpenMS: it includes only std headers and DnoiseMs1.h. Probes, all passing all 3 OK lines with exit 0:
- g++-13 with the in-tree target's exact CXX_FLAGS (from build/src/topp/CMakeFiles/spextractor.dir/flags.make: -O3 -DNDEBUG -std=gnu++23 -mssse3 -ffp-contract=off -fopenmp).
- g++-13 -O3 -march=native on an FMA CPU without -ffp-contract=off.
- Apple clang 21, -std=c++20 -O2.

The real gap (comes later):
- Deploys are gated only on git status --porcelain, not on CI.
- Once a later stage includes DnoiseMs1.h, sync_cluster.sh neither copies it nor lists it in its dirty-file check or tool_headers_sha256.
- The build then fails with a missing file, or silently uses a stale hand-copied header, the same drift the script's own comment records for TdfLoad.h.

FIX: 1) For the cluster (the part that matters), in scripts/sync_cluster.sh:
- Add src/DnoiseMs1.h to the git status --porcelain file list and to HDRS_SHA.
- Add src/DnoiseMs1.h and tests/test_dnoise_ms1.cpp to the scp to /scratch/kohlbach/OpenMS/src/topp/.
- In the remote block, after cd build and before make spextractor, add:
  FL=$(sed -n 's/^CXX_FLAGS = //p' src/topp/CMakeFiles/spextractor.dir/flags.make); /usr/bin/g++-13 $FL -I../src/topp ../src/topp/test_dnoise_ms1.cpp -o /scratch/kohlbach/test_dnoise_ms1 && /scratch/kohlbach/test_dnoise_ms1 || { mv '${REMOTE_SRC}.bak' '$REMOTE_SRC'; echo 'dnoise unit test FAILED' >&2; exit 2; }

2) Optional, in the repo:
- Move enable_testing() plus the four test_dnoise_ms1 lines above if(SPEXTRACTOR_TESTS_ONLY), and delete the copies inside it.
- Add 'ctest --test-dir spextractor/build --output-on-failure' to build.yml after 'Build SpeXtractor'.

TEST: The deploy itself runs test_dnoise_ms1 with g++-13 and the in-tree flags; add a 'dnoise_test=OK' line to bin/spextractor.provenance. The build.yml ctest step covers the full CMake path.

## [PARTLY/low] codex #8: exceptions can escape OpenMP blocks in the MS1 path (the parallel/single around detectTraces_, its taskloops, Ms1Prune::batch)

EVIDENCE: The mechanism is real, but almost all of it predates stage 1, and the new part is diagnostic-only.

Pre-existing, identical at HEAD cc39a66:
- The MS1 call's parallel + single (HEAD 3970-3972, snapshot 4115-4117) has no try.
- detectTraces_ contains no try or catch at all (HEAD 2395-2660).
- Its three taskloop bodies have none either: distribution (snapshot 2603), band MassTraceDetection::run (2681), valley split (2734).
- The MS2 window task's try/catch (snapshot ~5529) does not reach into those nested tasks.

g++-13 probe (/scratch/kohlbach/verify_probe/omp_exc.cpp, -fopenmp, 4 threads):
- Throw from the single body: 'terminate called after throwing std::bad_alloc', rc=134.
- try/catch inside the single, rethrown after the region: caught, rc=0.
- Throw inside a taskloop task: rc=134 with or without that containment. This confirms codex's point that catching around the call does not cover the tasks.

New with stage 1, inside the region:
- 2569 sample.swap: noexcept. With the prune on, it also removes the old sample.push_back allocation loop from the region.
- 2580-2582 [ms1-edges]: a vector of bands+1 values, String building and writeLogInfo_. Can only throw bad_alloc; detDigest_ (932-938) cannot throw.
- 2652-2654 [det] MS1 band spectra: String building, bad_alloc only.
- Both run only under SPEXTRACTOR_DET, allocate a few KB right after the same block allocated the whole band partition, and are not inside tasks.
- The taskloop change at 2618-2619 (20.0 -> kBandHaloPpmMul, a constexpr) adds no throw.

Ms1Prune::batch (1742-1770) is correct:
- The parallel-for body has try/catch plus critical, with rethrow after the region.
- Its setup allocations (1743-1748) and the rethrow run outside any OpenMP region at both call sites.
- flushMS1_ (1981) is reached only via consumeSpectrum, which every reader calls serially: BrukerTimsFile.cpp:1564, :1614 (after its region rethrow), :1785 ('serial hand-off'), :1914; MzMLHandler.cpp:192; MzPeakStreamLoad.h:413 (after rethrow).
- The resident call (3945) sits at function scope after the pick rethrow (3943).
- Such an exception reaches the stream try at 3796 or TOPPBase's catch around main_ (TOPPBase.cpp:477), so the run exits with an error code.
- The new Precondition check is deliberately placed before the region.

Net: the new exposure means SIGABRT instead of an error exit only on a few-KB bad_alloc with SPEXTRACTOR_DET set. The serious exposure is inside the tasks (bad_alloc in the partition copy, OpenMS exceptions from MassTraceDetection or peak detection) and is pre-existing.

FIX: Containment for the new code only (3 lines; the non-throwing path is unchanged). Replace snapshot 4115-4117 with:
  std::exception_ptr ms1_err;
  #pragma omp parallel
  #pragma omp single
  try { ms1_traces = detectTraces_(ms1_map, ms1_store, ..., LC_MS1MAP, LC_MS1BAND, &ms1_prune); } catch (...) { ms1_err = std::current_exception(); }
  if (ms1_err) std::rethrow_exception(ms1_err);

This contains both new [det] blocks and all pre-existing non-task code in detectTraces_ (probe: rc=0). It does not contain throws inside the three taskloop bodies. Those are pre-existing and need their own change: a per-task try/catch that stores the first exception under omp critical and rethrows after each taskloop. That change would also protect the MS2 window path.

Ms1Prune::batch needs no change.

TEST: No portable test can force a few-KB bad_alloc. To pin the containment:
- Add a test-only fault hook (e.g. SPEXTRACTOR_TEST_THROW=ms1_det throws Exception::Precondition inside the [ms1-edges] block).
- Add an e2e check with bands 2 and SPEXTRACTOR_DET=1 asserting returncode > 0 (a TOPP exit code), not -6 (SIGABRT).
- omp_exc.cpp already pins the pattern: single contained rc=0, task not contained rc=134.

NOTES: No repo files were edited.

Probe artefacts:
- Local: /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_probe/ — omp_exc.cpp, and the Apple clang build of test_dnoise_ms1 (t_mac, t_mac.out).
- HEAD copy of the tool source used for the pre-existing/new comparison: /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify_head.cpp (git show cc39a66:src/spextractor.cpp).
- Cluster: /scratch/kohlbach/verify_probe/ — omp_exc.cpp, t_intree (in-tree flags) and t_fma (-march=native, no -ffp-contract=off), each with its .out.

Side observation for whoever verifies kimi #3 (fp-contract): with g++-13 -O3 -march=native on an FMA-capable ibminode05 CPU and without -ffp-contract=off, test_dnoise_ms1 still reports D's 24 boxes with the FMA-sensitive boxes 11/15/16 intact. So the header's own guards suffice on the cluster compiler. That is evidence for g++-13 only, not MSVC.

Caveat for kimi #9: the portability CI runs the test on every push, but cluster deploys are gated only on git status, not CI. A pushed-but-red CI does not block sync_cluster.sh.

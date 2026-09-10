
# intensity-contract

## [REFUTED/none] kimi #1: raw-intensity recovery computes r*corr (corr = 100/atof(text)) while opentims might compute (raw*100)/at or read AccumulationTime as REAL, so at exact .5 ties a wrong raw count could pass uniquely (silent divergence)

EVIDENCE: Premise is wrong. opentims computes exactly what the recovery inverts. opentims.cpp:74 is `100.0 / atof(sql_row[4])`, where sql_row comes from sqlite3_exec text rows (sqlite_helper.h:17 and :87, query at opentims.cpp:287), not REAL or column_double. opentims.cpp:225 is `intensities[idx] = static_cast<double>(intensities[idx]) * intensity_correction + 0.5;` into a uint32_t* (opentims.h:165). BrukerTimsFile.cpp:1244-1248 fills a uint32 vector via save_to_buffs, and :201 does static_cast<float>. The recovery (spextractor.final.cpp:1923, `(uint32_t)(r * corr + 0.5)`, corr from TdfLoad.h:208/:220 `100.0/std::atof(sqlite3_column_text)`) uses the same operations in the same order. No (raw*100)/at exists anywhere.

Exhaustive brute force over every raw in [0,2^24) (verify2/brute_corr.cpp, brute_ties.cpp, brute_ulps.cpp):
- AccumulationTime values tested: 99.958, 99.953, 50, 100, 125, 100.042, 166.67, 99.5, 49.979, 100.000001, 96, 48, 99.2, 72, 88, 120, 80, plus corr = 1+1ulp and 1+2^-40.
- Contracted (fma) and uncontracted forward agree for every raw at every value.
- All four truth x recovery combinations (U/C x U/C): WRONG_UNIQUE = 0.
- Recovery corr off by 1-4 ulps: WRONG_UNIQUE = 0. The tie-prone values (96, 48, 99.2, 72, 88, 80) refuse 0.13-3.4 M values at -1..-4 ulps and are unchanged at +ulps.
- D and TNBC corr are 50000/49979 and 100000/99953. Odd denominators keep r*corr at least 5e-6 from any .5 tie, so 2^-28-scale rounding cannot matter.

Contraction: the cluster libopentims_cpp.a and spextractor contain 0 FMA instructions. The macOS OpenMS build compiles opentims without -ffp-contract=off (-std=gnu++20 -arch arm64), which is harmless per the above.

What is real is documentation only:
- spextractor.final.cpp:1814 (`(uint32)(raw * 100 / AccumulationTime + 0.5)`) and DnoiseMs1.final.h:25 (`floor(I * 100 / AccumulationTime + 0.5)`) misstate the operation order.
- TdfLoad.h:142-143 claims "the same library in the same process". That holds only in-tree: the tool has no SQLite of its own and resolves the 278 sqlite3_* symbols exported by libOpenMS.so (bundled 3.31.1, `%!.15g` at sqlite3.c:75548).
- The standalone build links SQLite::SQLite3 (CMakeLists.txt:47,50; CI libsqlite3-dev). SQLite 3.53.4 renders CAST(99.95799999999999 AS TEXT) as '99.957999999999984'; 3.31.1, 3.45.1 and 3.51.0 give '99.958'.
- This is bounded in practice: all 49 local .d files store AccumulationTime values that round-trip at 15 digits (D and TNBC: 0 mismatches), and a few-ulp corr difference causes refusals, not divergence.

FIX: Doc fix: make spextractor.final.cpp:1814 and DnoiseMs1.h:25 read `(uint32)(double(raw) * (100.0 / atof(AccumulationTime as SQLite text)) + 0.5)`. Drop "with the same library" from TdfLoad.h:143, or make it true.

Optional hardening that also closes the SQLite-version gap and kimi #10:
1. Take x = sqlite3_column_double for a REAL or INTEGER AccumulationTime.
2. Require that std::to_chars(x, general, 15) parses back to exactly x; refuse otherwise.
3. Set corr = 100.0/x.

When step 2 passes, this equals opentims' C-locale atof of either SQLite rendering.

TEST: Factor the per-point intensity inversion into a header function and add a unit test:
- For corr in {100/99.958, 100/99.953, 1, 2, 100/96}, every raw in [0, min(2^24/corr, 2^20)) inverts to itself with hits == 1.
- With corr = nextafter(100/96, 0) as the recovery corr and 100/96 as the truth, at least one refusal and zero wrong unique raws.


## [PARTLY/low] kimi #10 / vibe #2: std::atof on AccumulationTime is locale-sensitive; is mirroring opentims' atof correct, and does OpenMS/TOPP ever set a non-C LC_NUMERIC?

EVIDENCE: Plain atof is not a mirror of opentims. TimsDataHandle::read_sql (opentims.cpp, the RAIILocaleHelper just before the :287 query) calls std::locale::global(std::locale("C")) around the Frames read. Because "C" is a named locale, that also calls setlocale(LC_ALL,"C"). So opentims' corr is always the C-locale parse. TdfLoad.h:220 parses in the ambient locale, and it runs before any opentims handle opens (dnoise.setup at spextractor.final.cpp:3964, "before the load").

Probe verify2/locale_probe.cpp (macOS, de_DE.UTF-8), recovery over raw [0,2^18), which covers the largest MS1 MaxIntensity (145,043) across 49 local .d files:
- The tool's atof("99.953") = 99; opentims' guarded atof = 99.953000000000003, identical to a classic-locale istringstream.
- 99.953 and 99.958: 259,471 wrong unique raws and 2,623 refusals, so the run is refused at the first frame, spuriously.
- "100.042" and "100.5": the tool's corr is exactly 1, giving 260,953 / 262,043 wrong unique raws and 0 refusals. That is silent.
- "96.5": 251,189 wrong, 10,866 refusals.
- After the RAII guard, LC_ALL is left at "C".

No code path sets a non-C LC_NUMERIC today:
- A process starts in "C" whatever LANG is.
- The OpenMS library's only setlocale is Types.cpp:17-39 (save, set "C", restore): a no-op at static init.
- QCoreApplication is constructed only in openms_gui sources (TOPPAS vertices, ExternalProcessMBox, TVToolDiscovery).
- spextractor main sets OPENMS_DISABLE_UPDATE_CHECK=ON if unset (:6014, checked at TOPPBase.cpp:444-449), and UpdateCheck uses NetworkGetRequest without a QCoreApplication.
- Environments use a decimal point anyway: cluster LANG=en_US.UTF-8, mac LANG=C.

Smaller inaccuracies in vibe #2:
- atof follows setlocale, not the "global C++ locale".
- "0.1 -> corr=inf silently refused later" is wrong: setup refuses corr >= 1e6 up front (:1844).

Net: a latent hazard. It turns silent only with a comma-decimal LC_NUMERIC plus an AccumulationTime in (100,101).

FIX: TdfLoad.h:220: parse in the classic locale and require the whole text to be consumed:
`double at; if (!spx::dnoise::detail::parseF64(std::string(reinterpret_cast<const char*>(acc), (size_t)sqlite3_column_bytes(st, 4)), at) || !(at > 0.0)) return fail("frame " + std::to_string(id) + ": AccumulationTime is not a positive decimal number"); f.corr = 100.0 / at;`

parseF64 converts via strtod in the C locale, correctly rounded, which is bit-identical to opentims' guarded atof for every text it accepts. Anything else fails closed. (The column_double + 15-digit round-trip variant from kimi #1 also works.) Land this together with the corr >= 1 setup guard (codex #4). With both, "100.042" is refused up front instead of passing as corr = 1.

TEST: Unit test on the parse:
- Under setlocale(LC_NUMERIC, "de_DE.UTF-8") (skip if that locale is unavailable), "99.953" gives corr bit-equal to 100.0/99.953 as parsed in the C locale.
- "100.042" gives corr < 1.
- "99,953" and "abc" are refused.
- If TdfLoad.h is testable with SQLite (standalone CMake), run it through a temporary analysis.tdf with one Frames row.


## [CONFIRMED/low] codex #4: AccumulationTime > 100 ms (corr < 1) makes raw counts collide and refuses mid-run; corrected intensity >= 2^24 is refused; should setup refuse corr < 1 up front with a clear message, and should the error text name the 2^24 bound?

EVIDENCE: Setup accepts corr in (0.5, 1e6) (spextractor.final.cpp:1843-1845; the comment covers only corr <= 0.5), but collisions start just below 1. Brute force over raw < 2^24:
- AT=125 (corr 0.8): 3,355,443 collisions; the first is raw 3 -> v 2, so raws 2 and 3 both give 2, exactly codex's case. 6,710,886 raws are refused with hits >= 2.
- AT=166.67: first collision raw 2 -> v 1; 13.4 M refused.
- AT=120: first collision raw 4 -> v 3.
- AT=100.042: first collision raw 1191 -> v 1190 (14,086 ambiguous values). Mean MS1 MaxIntensity per frame is ~16-19k on D and TNBC, so the first frame almost surely refuses.

corr >= 1 is collision-free: 0 collisions below 2^24 at AT 100, 99.958, 99.953, 99.5, 99.2, 96, 88, 80, 72, 50, 49.979, 48 and at corr = 1+1ulp and 1+2^-40.

When the refusal fires: perf:stream_load defaults to true (:2584), so it comes at the first MS1 batch flush (dnoise->frame, :2159). D's whole MS1 stream load is 16 s wall (fix_gate F3 LOAD(stream)), so this is seconds, not hours. On the resident path (:4218) it comes after the full load.

2^24 case: corr=2, raw 8,388,608 -> 16,777,216 is unique but is refused by `v < 16777216.0f` (:1921). At AT=50, 8,388,608 raws hit that guard. The message says "(0 found)" (:1925) and does not name the bound.

Real-world impact is nil today:
- All 49 local .d files (D, TNBC and 47 others) have AccumulationTime 99.953 or 99.958.
- The largest MS1 MaxIntensity is 145,043, 115x below 2^24.

It would bite an acquisition with a TIMS accumulation time over 100 ms.

FIX: Setup (:1843-1845): change the test to `!(corr >= 1.0 && corr < 1e6)`. Message: "MS1 frame N: AccumulationTime T ms exceeds 100 ms, so opentims' intensity correction 100/T = c < 1 maps several raw counts to one intensity and the raw counts dnoise filters cannot be recovered". Update the comment to match.

frame() (:1921-1925): refuse `v >= 16777216.0f` separately, with "intensity >= 2^24 = 16777216: the loader's float32 intensity no longer identifies one raw count". Keep the conservative cut; relaxing it would need the float cast inside the forward check, which is not worth it at a 145k maximum.

Apply after the classic-locale parse fix (kimi #10), or a comma locale turns 100.042 into corr = 1.

TEST: Unit test on the factored recovery and setup check:
- corr = 100/125 is refused with text containing "AccumulationTime".
- corr = 100/99.958 is accepted.
- v = 16777216.0f throws text containing "2^24".
- The threshold premise holds: corr in {1, nextafter(1,2), 100/99.958, 100/96} has no two raws below 2^24/corr mapping to the same value (exhaustive, or up to 2^20 for CI time).


## [PARTLY/none] vibe #5: intensity recovery search bounds (+-1 around (v+-0.5)/corr) are arbitrary and wasteful; for extreme corr (0.1) the loop iterates 20x more

EVIDENCE: The margin is redundant. Bounds floor((v-0.5)/corr)..ceil((v+0.5)/corr) give identical hits and raw for every raw in [0,2^24), at all 19 corr values and all contracted/uncontracted combinations (tight_mismatch=0 in brute_corr and brute_ties).

Cost is negligible:
- Candidates per point: 4.94-5.0 (shipped) vs 2.94-3.0 (tight) at corr ~1; the maximum is 5.8 vs 3.8 at corr 0.6.
- On data (x86, g++ -O3 -mssse3 -ffp-contract=off, the tool's flags; two reps within 0.02 ns): 14.1 vs 9.9 ns per point.
- For D's 927,158,066 raw MS1 points that is 13.1 vs 9.2 CPU-s, a saving of 3.9 CPU-s. Compare dnoise filter CPU of 254-379 s and 10,193 CPU-s for the run (F3: 02:49:53 h): about 0.04%, roughly 0.04 s wall at 100 threads.

The "corr 0.1 -> 20x" case cannot happen: setup refuses corr <= 0.5 (:1844), and codex #4's fix raises that to corr < 1.

FIX: None needed. If the loop is touched anyway, drop the -1.0/+1.0 and keep floor/ceil. That rounding already contains every preimage, as the exhaustive test shows.

TEST: The exhaustive recovery unit test from kimi #1 (every raw inverts to itself uniquely) covers any bound change. Optionally assert that the shipped and floor/ceil bounds give identical (hits, raw) for raw < 2^20 at corr 100/99.958 and 100/96.


# fp-and-build

## [REFUTED/none] kimi #4: the -ffp-contract=off guard does not reach DnoiseRun::frame's recovery arithmetic in the in-tree cluster build, so contraction can shift the intensity forward check at .5 ties (usually a refusal, occasionally a unique wrong raw count)

EVIDENCE: 1) The flag is present and FMA is impossible anyway. The in-tree tool's flags.make is `-O3 -DNDEBUG -std=gnu++23 -fvisibility=hidden -fPIC -mssse3 ... -ffp-contract=off ... -fopenmp` (/usr/bin/g++-13, 13.3.0). There is no -march or -mfma. The flags come from OpenMS cmake/compiler_flags.cmake: -mssse3 at :92 (PUBLIC), -ffp-contract=off at :104 (GNU) and :134 (Clang). That file is dated 2026-04-24 and has no .orig, so it is upstream. libOpenMS has the same flags. The EPYC 7763 CPU has fma/avx2, but a -mssse3 target cannot emit FMA: clang -target x86_64 with -mssse3 -ffp-contract=fast gives 0 fused instructions on the opentims loop shape and the recovery shape, while -mfma or -march=znver3 gives 4. The deployed binaries of the running arm (/ceph/.../dnoise_s2b) confirm it: bin/spextractor has 822,423 instructions and 0 FMA; lib/libOpenMS.so has 10,887,732 and 0 FMA.
2) opentims is not built the same way. build/_deps/opentims-build/.../opentims_cpp.dir/flags.make is `-O3 -DNDEBUG -std=gnu++20 -fPIC -fvisibility=hidden -O3 -g -Wall -Wextra -w`: its own options (opentims CMakeLists:36-39), with no -ffp-contract=off and no -mssse3. That is harmless on x86-64 (no FMA ISA). On arm64 it would fuse: the opentims.cpp:224-225 loop compiles to 11 fused instructions with Apple clang and 6 with g++-16.
3) Even if it contracts, the intensity check cannot change. opentims.cpp:225 is `static_cast<double>(raw) * intensity_correction + 0.5` into a uint32, the same expression as spextractor.final.cpp:1923. Truncating x+0.5 gives the same integer fused or unfused whenever the exact x is >= 0.5. For n >= 2, n-0.5 is never a power of two, so both forms round on the same grid and both reduce to x < n-0.5-u/2. setup() refuses corr <= 0.5 (spextractor.final.cpp:1843-1845), so every raw r >= 1 has r*corr > 0.5.
   Probe verify2/k4/trunc_invariance2.cpp: 108,628,878 adversarial near-tie (r,c) pairs gave 52,746 disagreements. All have exact r*c < 0.5 (the 0-vs-1 edge); 0 have corr > 0.5 and 0 land on a value >= 2.
   Exhaustive check over every raw < 2^24 at the real AccumulationTimes (REAL '99.958' on D, '99.953' on TNBC): 0 fused/unfused differences.
4) The TOF round trip and 1/K0 table are far inside their tolerances. verify2/roundtrip_probe.cpp covers every TOF bin at the MS1 T1 extremes with MzCalibration fused or unfused on the loader side and the tool side (4 combinations). Max |tof - roundtrip| is 2.33e-10 bins on D and 1.16e-10 on TNBC, identical across all 4 combinations, against kTofTol 1e-6 (:1823, :1914). In the setup 1/K0 table (:1852), 0 of 944 (D) and 0 of 918 (TNBC) float32 values change under fusion (kImTol 1e-6, minimum scan step 8.8e-4).
5) macOS and CI. build.yml builds the full tool only on ubuntu x86-64, where the default target has no FMA; tests.yml runs TESTS_ONLY on macOS arm64 and Windows. The gate's own pragma+volatile holds: the unit test passes with Apple clang at default contraction, with -ffp-contract=fast, and with g++-16 defaults (fp-contract=fast on arm64). Kimi's side remarks are true but moot: the in-tree flag is inherited rather than asserted, and the node unit test's TU does not contain the recovery code.

FIX: No code fix needed. Add one comment at spextractor.cpp:1923 saying why contraction cannot matter, so no one later adds volatiles or a flag dependency:
- truncating x+0.5 is fusion-invariant for x >= 0.5, which the corr > 0.5 refusal guarantees, on either side, including opentims, which is built without -ffp-contract=off;
- the TOF and 1/K0 recoveries are tolerant, with fusion effects about 4000x below kTofTol and no float32 change.
Optional hygiene (pins the reference flags for the whole tool, not for dnoise): in sync_cluster.sh, refuse the deploy when FL lacks -ffp-contract=off or contains -march=, -mfma, -Ofast, -ffast-math, -funsafe-math-optimizations or -freciprocal-math.

TEST: None required. If the comment's claim is to be pinned, kimi #2's golden recovery test (tuples -> tof/scan/raw), compiled with the tool's own flags, covers it. Build the optional sync_cluster.sh FL assertion as a hard refusal in the existing unit-test step.


## [PARTLY/low] codex #10: CMakeLists applies -ffp-contract=off to the whole spextractor target, which changes contraction everywhere in the tool (including with dnoise off) and broadens the identity claim beyond the validation; it should be scoped or a new baseline defined

EVIDENCE: True part: it changes codegen tool-wide wherever FMA exists. Apple clang 21 on arm64 contracts by default: verify2/fma_probe.cpp (axpy, the forward check, mzToTof) has 4 fused instructions, and 0 with -ffp-contract=off. The same happens on x86-64 built with -march=haswell or later (clang -march=znver3: 4, and 0 with the flag). git diff HEAD shows SPX_NO_FP_CONTRACT is new in this change (CMakeLists.txt:21, :51).
False part: it changes nothing on any platform that produces pins or is validated.
- The cluster in-tree build does not use this CMakeLists. Its spextractor flags.make (mtime 2026-09-06) already has -ffp-contract=off, coming from OpenMS compiler_flags.cmake:104, dated 2026-04-24, so every earlier pin and the stage-2 pins (deploys.log, all 2026-09-10) were built with it. The -mssse3 target has no FMA ISA, and the deployed spextractor and libOpenMS.so contain 0 FMA instructions.
- CI build.yml:79-82 builds the tool on ubuntu-latest x86-64 with the default target, where there is nothing to contract (clang x86_64 -mssse3 -ffp-contract=fast: 0 fused). It compares no outputs.
- No arm64 full-tool build exists: tests.yml:17-28 is TESTS_ONLY, and there is no local build dir. There is no arm64 baseline to diverge from.
Scoping would make things worse. OpenMS itself compiles libOpenMS contraction-free on GNU and Clang (compiler_flags.cmake:104, :134), so the tool-wide flag makes an arm64 or -march build match the cluster reference. Scoping it to the dnoise code would bring back arm64-only contraction in tracing, correlation and scoring. The one dependency built without the flag, opentims_cpp, has a single exposed expression, and that expression is contraction-invariant (see kimi #4).

FIX: Keep the flag tool-wide; do not scope it. Add a CHANGELOG line: builds of the tool for FMA-capable targets (arm64, -march=haswell and later) are now contraction-free like the cluster reference; default x86-64 builds and all pins are unchanged.

TEST: Add `ctest --test-dir spextractor/build -R dnoise_ms1 --output-on-failure` to build.yml. Today only tests.yml:34 runs ctest (TESTS_ONLY), so the full tool build never runs the pinned-box test under its own flags. Optionally, the sync_cluster.sh FL assertion described under kimi #4.


## [CONFIRMED/low] vibe #3: -funsafe-math-optimizations, -freciprocal-math and clang -ffp-model=fast are not caught by DnoiseMs1.h's #error and move D's gate boxes; is a cheap runtime self-test (recompute razor-edge boxes at setup, refuse on mismatch) sound and worth it?

EVIDENCE: Measured on the frozen header (verify2/inc/DnoiseMs1.h), unit test at -O3:
- Apple clang 21 builds past the #error and FAILs on D boxes: -freciprocal-math moves 9 and 13 (scan_hi 604/570 where 605/571 is pinned); -funsafe-math-optimizations and -ffp-model=fast move 9, 13 and 18.
- -ffp-model=aggressive and -ffast-math hit the #error.
- -fassociative-math -fno-signed-zeros -fno-trapping-math passes on clang.
- On g++-16 (aarch64), -funsafe-math-optimizations and -freciprocal-math FAIL on box 9, and -fassociative-math -fno-signed-zeros FAILs `parseF64("-0") keeps the sign` (test line 216).
Macros:
- clang on the x86_64 target defines nothing for these three flags.
- clang on arm64 defines only __ARM_FP_FAST, for -funsafe-math-optimizations and -ffp-model=fast (not for -freciprocal-math).
- GCC defines __RECIPROCAL_MATH__ (for -freciprocal-math and -funsafe-math-optimizations), __ASSOCIATIVE_MATH__ and __NO_SIGNED_ZEROS__, plus __ARM_FP_FAST on arm64. None of these appear under default flags.
So the gap is detectable at compile time for GCC everywhere and for clang on arm64 (except -freciprocal-math alone); it is truly invisible only to clang on x86-64 and to clang's -freciprocal-math on arm64. The header already documents it as 'must not be used' (DnoiseMs1.final.h:40-43).
Soundness of the self-test: verify2/k4/selftest_probe.cpp calls buildMs1WindowGate three ways on D's fixture: (A) constant Params{} inlined, as the unit test does; (B) Params laundered through volatiles with rows copied at run time, as the tool does; (C) through a noinline wrapper. Under every flag above, on both compilers, A, B and C flip exactly the same boxes, so a setup-time recomputation represents the production call. Limits: it is a canary (it only sees rewrites that move D's razor edges) and it covers only the gate; the recoveries do not need it.
Worth it: marginal. The builds that matter already run the pinned-box test under the tool's own flags: sync_cluster.sh:68-76 compiles test_dnoise_ms1.cpp with the in-tree FL and refuses the deploy on failure, and tests.yml runs it on 4 platforms. No OpenMS, CMake or cluster flag adds unsafe math.

FIX: Minimal fail-closed fix at compile time: extend the guard at DnoiseMs1.h:66-67 with `|| defined(__RECIPROCAL_MATH__) || defined(__ASSOCIATIVE_MATH__) || defined(__NO_SIGNED_ZEROS__) || defined(__ARM_FP_FAST)`. Leave __NO_TRAPPING_MATH__ out. Update the error text and the point-6 comment to say that only clang on x86-64 (and clang -freciprocal-math on arm64) still slips past.
To close that residue as well: a noinline canary in DnoiseRun::setup() that runs buildMs1WindowGate on the unit test's D fixture (metaD strings, kRowsD, Params{}) and refuses the run if any of the 24 boxes differ from kBoxesD. It costs microseconds and about 40 lines of constants; worth adopting only if default-on bit identity must survive arbitrary third-party CXXFLAGS.

TEST: In tests.yml, on every GCC and arm64 matrix entry, add a negative compile step asserting refusal, e.g. `! $CXX -std=c++20 -O2 -freciprocal-math -fsyntax-only -I src tests/test_dnoise_ms1.cpp` and the same with -funsafe-math-optimizations. Keep the existing pinned D boxes 9/11/13/15/16/18 as the canary's golden. Add ctest to build.yml so the full tool build exercises the header under its own flags.


# sqlite-metadata

## [PARTLY/medium] codex #2: sqlite errors in loadTdfDnoise (a failed prepare counts as no rows, and any non-ROW code ends a row loop as if complete) can silently build a partial or absent window gate

EVIDENCE: I checked all five queries in src/TdfLoad.h. Only the windows query turns a sqlite error into a silent change in kept points; the other four already fail closed downstream, but with the wrong message.
(1) GlobalMetadata, :165-179. A prepare failure is ignored and the loop stops on any code. A lost row becomes a missing key, and buildMs1WindowGate then refuses it (DnoiseMs1.h:283-292). With no usable window rows the metadata is never read (:274). Result: fail-closed.
(2) MAX(NumScans), :180-184. Prepare and step==ROW are both checked. Result: OK.
(3) DiaFrameMsMsWindows, :185-189. Any prepare failure counts as no rows, and any loop end counts as done. Result: SILENT.
(4) TimsCalibration, :191-201. Prepare is checked, the loop is not. A lost row is refused at :214 as an 'unknown TimsCalibration row'. Id is INTEGER PRIMARY KEY in both D's and TNBC's schema, so there are no duplicate Ids to lose.
(5) Frames, :202-223. Prepare is checked, the loop is not. Frames after the break are missing, and DnoiseRun::frame (spextractor.final.cpp:1898) refuses the first such MS1 frame during the load, as 'not an MS1 frame'. That is late and misleading, and the setup corr check (:1843) never sees those frames.
Probe: verify2/mktdf.py builds synthetic tdfs with D's TimsCalibration row and metadata; verify2/sqlprobe.cpp runs them through the frozen TdfLoad.h.
- ok24: 24 boxes, rc=101 (DONE).
- absent: true, gate NONE, prepare rc=1 'no such table'.
- nocol (IsolationWidth missing): true, gate NONE, rc=1 'no such column'.
- corrupt24 (the real case: 24-28 rows fit on one page): true, gate NONE, loop ended rc=11 SQLITE_CORRUPT after 0 rows.
- corruptmid3000 (1 of 18 leaves corrupted): true, 1554 of 3000 boxes, rc=11.
What dnoise does when the table is missing: according to the port's citation (DnoiseMs1.h:112-115, tdf/mod.rs:246-249; writer.rs:984-986), no table means no rows and no gate, so every halo survivor is kept and GlobalMetadata is never read. I could not re-read the upstream source (github pgarrett-scripts/dnoise returns 404 via gh api and raw).
The loader treats a missing table as legitimate: isDIA and readDIAWindows (BrukerTimsFile.cpp:409-430, 681-689) fall back to DiaFrameMsMsInfo (:720-745). So 'absent' must stay 'no gate'. The loader maps ANY exception on COUNT(*) to 'absent', so on real corruption it also misbehaves, and silent success end to end is unlikely. That is why this is medium, not P1.
Precedent: the loader patch's T1 loop already throws on rc != SQLITE_DONE. The sibling loaders have the same pattern: loadTdfCalibration :93-98 (an error after the first row still passes ncal==1) and :124-131 (a partial T1 read gives tail frames T1_ref through factor(), spextractor.final.cpp:773).

FIX: In loadTdfDnoise (apply the same to loadTdfCalibration and loadTdfAxisBounds):
  auto sqlfail = [&](const std::string& what) { return fail(what + ": " + sqlite3_errmsg(db)); };  // errmsg is read before fail() finalizes
1. Check every prepare: if (sqlite3_prepare_v2(...) != SQLITE_OK) return sqlfail("GlobalMetadata query"); likewise for MAX, TimsCalibration and Frames.
2. Require DONE after every loop: int rc; while ((rc = sqlite3_step(st)) == SQLITE_ROW) {...} if (rc != SQLITE_DONE) return sqlfail("reading <table>");
3. Decide whether the optional table exists from the schema, never from a prepare error:
  SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = 'DiaFrameMsMsWindows' COLLATE NOCASE
  (COLLATE NOCASE because table-name resolution is case-insensitive; that statement also needs its prepare and step checked). If no row: windows stay empty (dnoise: no gate). If present: the windows prepare must succeed (a missing column refuses) and the loop must end in SQLITE_DONE.
4. Optionally refuse NULL ScanNumBegin/ScanNumEnd; the WHERE clause only filters the m/z columns, and column_int64 reads NULL as 0.

TEST: Add a sqlite-gated unit test, tests/test_tdf_load.cpp. test_dnoise_ms1 must stay sqlite-free for Windows CI, so use find_package(SQLite3 QUIET) plus if(SQLite3_FOUND), and a shim ${CMAKE_BINARY_DIR}/shim/OpenMS/FORMAT/TdfMzCalibration.h. Also compile it in the sync_cluster.sh unit-test step.
The test builds tdfs through the sqlite3 C API in a temp dir, using the shapes in verify2/mktdf.py. It corrupts pages at (rootpage-1)*page_size, parsing the 0x05 interior page to find a middle leaf. Assert:
- ok: true, 24 windows
- absent: true, 0 windows, no gate
- nocol: false, why mentions IsolationWidth
- corrupt single windows page: false, 'malformed'
- corrupt mid-table leaf: false (today: true with 1554 of 3000 windows)
- corrupt Frames leaf: false at setup, not during the load


## [PARTLY/low] codex #6 / kimi #11: NumScans and NumPeaks are narrowed to u32 without range checks

EVIDENCE: The narrowing is real: TdfLoad.h:218-219 casts (std::uint32_t)sqlite3_column_int64. The only range check is on MAX (:182), which a negative row passes, and denoiseMs1Frame's guard (DnoiseMs1.final.h:459) admits exactly UINT32_MAX. The TimsCalibration ids (:198, :211) are also narrowed through sqlite3_column_int.
No divergence in kept points is reachable, for two reasons:
(a) num_scans enters the filter only as a bound. It sizes stamp/sum (:379-380) and row (:507), and clamps v_hi (:527). Rows above the highest occupied scan are empty, so once every scan < num_scans the mask does not depend on its exact value. A value wrapped downward is refused per point (spextractor.final.cpp:1917). A value wrapped upward (-1 becomes 4294967295) gives the same mask but allocates about 80 GiB zero-filled on one thread (stamp 16 + sum 32 + row 32). That ends in std::bad_alloc, which is not a DnoiseError and not a BaseException, so it skips the stream catch at :4106, or in an OOM kill on a shared node.
(b) The loader narrows the same way and fails first. opentims TimsFrameFromSql does atol(sql_row[1]) and atol(sql_row[2]) into uint32_t. data_size_ints() = num_scans + num_peaks + num_peaks, in uint32 arithmetic (opentims.h:104), sizes the decompression buffer at handle open. The blob size assert (opentims.cpp:92) is compiled out, since OpenMS flags.make has -DNDEBUG. The decode loop walks num_scans-1 scan headers (:173-200), and frameToSpectrum sizes its buffers by frame.num_peaks while save_to_buffs writes per-scan counts. So a wrapped value corrupts loader memory before any spectrum reaches DnoiseRun. The check n != fr.num_peaks (:1900) compares against the same narrowed value opentims used.
Real data: all 17,448 frames of D and all 71,953 of TNBC have typeof integer, NumScans is uniformly 944 / 918, and max NumPeaks is 1,049,229 / 894,640.

FIX: In the Frames loop, validate the stored integer before casting:
  auto int_in = [&](int col, long long lo, long long hi, long long& v) { if (sqlite3_column_type(st, col) != SQLITE_INTEGER) return false; v = sqlite3_column_int64(st, col); return v >= lo && v <= hi; };
- NumScans in [0, meta.max_num_scans]. That limit is at most 1e6 and comes from the same table; the per-row type check also closes the case where MAX returns a TEXT cell, which sorts above INTEGER.
- NumPeaks in [0, UINT32_MAX].
- MsMsType in [INT_MIN, INT_MAX].
- TimsCalibration (here and in the TimsCalibration.Id read at :198) in [0, UINT32_MAX].
- For an MS1 frame, NumPeaks > 0 requires NumScans >= 1.
- Check that MAX(NumScans) is SQLITE_INTEGER (NULL on an empty table is already handled as 0).
Refuse with the frame id and column name. With these checks the u32 guard in denoiseMs1Frame is unreachable from the tool; keep it in the header.

TEST: In the sqlite unit test above, add Frames rows with NumScans = -1, NumScans = 4294967297, NumPeaks = 4294967301, and NumScans stored as TEXT '944'. Each must make loadTdfDnoise return false and name the column; today they return true with num_scans 4294967295 / 1 and num_peaks 5. A control row shaped like D must still return true.


## [CONFIRMED/low] codex #5 / kimi #5: the scan-table monotonicity and separation check runs every TimsCalibration row over the global MAX(NumScans), including rows no MS1 frame references

EVIDENCE: spextractor.final.cpp:1846-1865 sets n_scans = tdf.meta.max_num_scans and builds and checks a table for every tdf.tims_cal row. Nothing checks whether an MS1 frame references the row, or what its frames' NumScans are.
Impact on the benchmark files is zero. D and TNBC each have exactly one TimsCalibration row (Id 1, ModelType 2), referenced by every frame, with uniform NumScans of 944 / 918, so the global and per-row scopes are the same.
verify2/scan_sep.py replays the setup loop in float32 on the real coefficients:
- D's row separates every scan until n_scans = 1,584,279, above the 1e6 MAX cap.
- TNBC's row first refuses at n_scans = 38,722, the pole of 1/(C6 + C7/V) at V = -C7/C6 (C6 = +0.0226).
So a false refusal needs a row whose pole or flat region lies between its own frames' scan count and the file's global MAX, or an unreferenced or MS2-only row that is degenerate anywhere. With about 700-1000 scans per frame this is theoretical, and I saw no file with more than one row.
The loader constrains the fix: RationalScan2ImConverter.cpp:125-140 falls back to linear 1/K0 when ANY row has ModelType != 2, referenced or not. So the all-rows ModelType refusal at TdfLoad.h:195 is correct and must stay; only the table and separation scope should narrow.

FIX: In DnoiseRun::setup, after the per-row NumScans validation from finding 2, compute need[ci] = max(fr.num_scans over frames with msms_type == 0 && fr.cal == ci).
- Build and check each row's table over need[ci] scans only.
- need[ci] == 0: leave im_asc[ci] empty and skip the check. scanOf returns -1 on an empty table, so any use still refuses.
- Keep tdf.meta.max_num_scans unchanged for buildMs1WindowGate, since dnoise's MAX runs over all frames.
- Keep the per-point check scan < fr.num_scans (:1917).
- Log need[] next to the global max.

TEST: Factor the table build out of spextractor.cpp into an inline function the sqlite-free unit test can include (for example next to DnoiseMs1.h), then pin three cases:
(i) a row with TNBC's coefficients referenced by MS1 frames of 918 scans, in a run whose global MAX is 40,000 because of another row. Refused today, accepted after.
(ii) an unreferenced row with its pole inside [0, 918). Accepted after.
(iii) a referenced row with its pole inside its own frames' range. Still refused.


## [PARTLY/low] vibe #4: the TOF axis model is not checked until the first batch

EVIDENCE: Axis usability is checked before the load: spextractor.final.cpp:3948 refuses if loadTofAxis fails (the same TdfMzCalibration isSupported rules), and dnoise setup (:3964) runs before any read. Only the loader's actual model choice is deferred, and lastMzCalibration() cannot be known earlier: openTimsDataHandle sets it (BrukerTimsFile.cpp:1045-1160) to 'bruker_sdk' when bruker_sdk_path or OPENMS_BRUKER_SDK_PATH is set (:1080-1105), to 'tdf_table_modeltype1' at :1135, or to the chord only with SPEXTRACTOR_ALLOW_CHORD_FALLBACK=1.
Default streaming path (perf:stream_load defaults to true, :2584): the first checkLoader call is in flushMS1_ (:2149), after kBatchMS1_() = kBatch_() = 256 frames (:2248-2258). In dnoise_gate/G1/ledger.tsv the first MS1 batch is charged at t=0.85 s (scratch 1,003 MiB), picked by t=1.78 s, and pass 1 ends at t=31 s. So a refusal costs under 1 s and about 1 GB, not 'the entire tdf'.
Resident path (:4208, perf:stream_load=false or a fallback after a non-dnoise stream failure): checkLoader runs only after the whole-run loadExperiment. That is the expensive case.
openTimsDataHandle is the first call in loadDIAStreaming (:1537), before any consumeSpectrum, so the value is final when the first MS1 frame arrives.

FIX: (1) Call dnoise->checkLoader() once, on the first consumeMS1Spectrum_ call, before buffering. The refusal then comes after one frame instead of 256. Keep the per-batch call as the authority.
(2) For the resident path, predict the loader's choice in the dnoise setup block. The tool never sets tims_calibration_strategy (default AUTO, BrukerTimsFile.h:96), so refuse when cfg.bruker_sdk_path or getenv("OPENMS_BRUKER_SDK_PATH") is non-empty, with the message 'the loader will calibrate m/z through the Bruker SDK'. If the SDK then fails to load, the loader would fall back to the table model, so this can be a false refusal; that is fail-closed, and -dnoise:ms1 false is the escape. Unset or empty means the table model, since loadTofAxis already applied the same isSupported checks.

TEST: Add an e2e check in test/test_spextractor.py. Create a fake .d containing only a synthetic analysis.tdf (a supported MzCalibration row, Frames with T1, D-shaped TimsCalibration and windows) and no tdf_bin. Run it with OPENMS_BRUKER_SDK_PATH=/nonexistent and expect a nonzero exit whose log names dnoise:ms1 and the SDK, before any loader output. Without the variable, the same input must get past setup (it then fails in the loader because tdf_bin is missing, which proves the ordering).


## [REFUTED/none] vibe #1: a TOF bin is accepted up to 2^32-1 instead of the digitizer range, risking out-of-bounds access in DnoiseMs1.h

EVIDENCE: DnoiseMs1.final.h has no storage indexed by TOF:
- Radix digits are masked with & 2047u into a 2049-entry array, with shift <= 22 (:474-481).
- Streak windows saturate (:390) and walk the sorted array with two pointers.
- Halo bounds saturate (:528) and use lower_bound over per-scan arrays.
- Gate intervals merge with a saturated +1 (:156), and contains() only compares (:166-173).
The only arrays indexed by point data are indexed by scan (stamp/sum/row), bounded by the per-point scan < num_scans check (:465). In spextractor.final.cpp:1913-1914, bin = nearbyint(t) with 0 <= bin <= 4294967295, so (uint32_t)bin is defined.
Probe verify2/tof_edge2.cpp, built with -fsanitize=address,undefined,unsigned-integer-overflow,implicit-conversion -fno-sanitize-recover=all. Scenes put TOF in [0,400] and in [2^32-401, 2^32-1], with gate boxes at tof_lo=0 and tof_hi=UINT32_MAX, at 4 densities where the streak filter removes 0-60% of points. Results: no sanitizer report; keep masks identical to the same scene shifted by 2^31 (a wrap would break that); gate membership equal to the box definition at both edges; PASS every time.
The bound is not part of the contract either: dnoise filters the blob's raw u32 TOF, and DigitizerNumSamples only sets the chord's tof_max_index (DnoiseMs1.h:288-298).
vibe's proposed fix would do harm. loadTofAxis still returns true with n_bins = 0 when loadTdfAxisBounds fails (:821-823), for example DigitizerNumSamples > 1e8 or MzAcqRangeUpper > 1e5, values the gate parser accepts. Then every point would be refused.
Real data: max TOF is below 634,073 (D) and 399,967 (TNBC).

FIX: None. Do not adopt bin < ax.n_bins. If a plausibility check is ever wanted, only apply it when the bounds are known: ax.n_bins > 1 && bin >= ax.n_bins -> refuse.

TEST: Optional pin: add the translation-invariance edge case to tests/test_dnoise_ms1.cpp. Scenes at TOF 0 and at 2^32-1 against the same scenes shifted by 2^31, with a gate box whose tof_hi is UINT32_MAX; assert identical masks. This stops a future rewrite indexed by TOF (a histogram or dense window) from bringing in a silent wrap or overrun.


# resident-fallback

## [PARTLY/low] codex #1: on the resident path, 'if (!s.containsIMData()) continue;' runs before dnoise.frame, so a non-empty MS1 spectrum without IM data could skip denoising. Should the run also check that every MS1 frame was filtered exactly once?

EVIDENCE: The ordering is real (spextractor.final.cpp:4217 skips before the dnoise.frame call at 4218), but the bypass cannot happen with the current loader.

1. A skipped spectrum never reaches the output: the dispatch at 4237 applies the same skip, so it never enters ms1_map, and no un-denoised MS1 point can reach the output under the stamp.
2. Emptied frames stay in the map. OpenMS MSSpectrum::select (MSSpectrum.cpp:36-55) swaps only the vector part, so the named IM array survives at size 0. PeakPickerIM::pickIMCluster returns at PeakPickerIM.cpp:994 on an empty spectrum, so containsIMData is still true at 4237.
3. A non-empty MS1 spectrum always carries IM data on a .d input. The call chain is BrukerTimsFile::load (AUTO+DIA -> loadDIA_, BrukerTimsFile.cpp:1819-1827) -> loadMS1Spectrum -> frameToSpectrum (1183-1225). That function returns with no IM array only when num_peaks==0 (1194); otherwise it always pushes an IM array of num_peaks entries (1216-1223). IMDataConverter::getIMUnit recognises that array by name prefix (IMDataConverter.cpp:333-335). The centroiding path also pushes one (1271-1274), and a centroided frame is refused anyway by n != NumPeaks (1900). MS1 aggregation is refused at 3945.
4. Side effect: an MS1 frame with NumPeaks=0 is counted by streaming (frame() at 1903) but skipped by resident, so only the summary frame count can differ.
5. Every MS1 frame arrives exactly once today, but nothing enforces it. Both loaders enumerate each MS1 frame id once (loadDIAStreaming 1548 plus the serial hand-off at 1614; loadDIA_ 2372-2376). The summaries match the tdf exactly: D 1343 frames / 927158066 raw points = Frames MsMsType=0 count 1343 / SUM(NumPeaks) 927158066 with 0 empty; TNBC 4797 / 3169439123 = tdf 4797 / 3169439123 with 0 empty.
6. Resident with dnoise on has only run on the 100-frame g1.d, which has 0 emptied frames (fix_gate/c3 r1d_res, r2d_fb).

FIX: Two changes, both fail-closed.

(1) In the resident loop, call `if (dnoise.on && s.getMSLevel() == 1) dnoise.frame(...)` BEFORE `if (!s.containsIMData()) continue;`. frame() already refuses n>0 without IM and counts n==0, so streaming and resident counts then agree.

(2) Cheapest exact completeness check, a bitmap:
- Add `std::vector<uint8_t> seen` to DnoiseRun, sized tdf.frames.size() (17 KB for D, 72 KB for TNBC).
- frame() writes the frame id into its per-frame Counts slot (`c.fid = fid`).
- The serial add() sets seen[fid] and throws DnoiseError if it was already set.
- At 4271, before summary(), a new complete() throws DnoiseError for any id with msms_type==0 && num_peaks>0 && !seen.
- The fallback reset clears seen together with total, via a reset() method.

A frames-count plus total-raw check is not exact: a duplicated frame and a missing frame with equal NumPeaks cancel out.

TEST: - Move the bookkeeping (mark/complete/reset) into a small header struct and unit-test it in tests/test_dnoise_ms1.cpp: a duplicate is refused, a missing non-empty frame is refused, a missing empty frame is accepted, reset clears the marks.
- Cluster gate: the D/TNBC streaming arms and c3 r1d_res/r2d_fb pass the check with unchanged digests.
- Close the gap in point 6: one full-D -perf:stream_load false run with dnoise on (2 emptied frames) must match the streaming MS1 trace count.


## [PARTLY/low] codex #7: the resident dn_work vectors outlive the pick, stay alive into tracing and assembly (~3.1 GB), and the ledger does not charge them

EVIDENCE: The scope claim is wrong; the retention is real but shorter.

1. Scope: dn_work is declared at spextractor.final.cpp:4209 inside `if (!streamed) {`, which opens at 4188 and closes at 4251 (braces matched by script). It is destroyed at 4251, before exp.clear (4252), MS1 tracing (4406+) and assembly. Its capacity is held only during ms1_prune.batch (4231) and the serial dispatch (4235-4250).
2. Size: resize() never shrinks, so each thread keeps the capacity of the largest frame it processed. Per point that is ~41 B typical and at most ~58 B (Work scan/tof/raw 12, keep 1, idx 8 x kept; Scratch idx/idx2/id 12, tof/scan/inten 12, mark 1, htof/hinten/hpos 12 x streak survivors; DnoiseMs1.final.h:343-354, 471-513).
3. Simulation over the tdf's MS1 NumPeaks at 100 threads (sum of per-thread maxima):
   - D: 101.4 M points = 3.9 GiB (5.5 worst case; bound 100 x 1,049,229 points = 5.7 GiB)
   - TNBC: 85.1 M points = 3.3 GiB (4.6 worst case)
   It is not charged in the ledger.
4. Reach: the path is non-default on a .d (perf:stream_load defaults to true, 2584); it runs only with -perf:stream_load false or after a stream fallback. By then the whole-run raw load peak has passed and the dispatch is freeing picked frames, so the process peak does not rise. The memory stays freed but unreturned in the worker arenas.

FIX: Free the scratch right after `dnoise.add(dn_cnt);` (4229): `std::vector<DnoiseRun::Work>().swap(dn_work); std::vector<DnoiseRun::Counts>().swap(dn_cnt);`. Alternatively, brace the declaration, the parallel loop and add() into their own scope. Optionally charge LC_SCRATCH through a LedCharge sized from the Work capacities while the loop runs.

TEST: No suite check can build a .d. Pin it with the c3 r1d_res arm (resident, dnoise on): MS1 traces digest 18155112766412898203 unchanged. Also record one full-D -perf:stream_load false run with SPEXTRACTOR_LEDGER and check RSS/arena at the 'Split into MS1' line.


## [PARTLY/low] codex #9 / kimi #8: after a stream fallback, the [ms1-hist] counters, phase stats and ledger rows other than LC_MS1MAP/LC_SLAB keep the failed attempt's values

EVIDENCE: Only one stale value exists, and it is instrumentation-only and not caused by the fallback.

1. [ms1-hist] cannot report stale values. The counters are added to only in flushMS1_ (spextractor.final.cpp:2171-2177) and printed only at 4081-4086, inside the try after `streamed = true` (4080). After a fallback streamed stays false, so the line is never printed; the resident path never builds the histogram at all.
2. Phase stats do not mix the attempts (kimi's claim is refuted). The LOAD(stream) row is written only on success (4087-4090), and flush_wall_ is printed only on success (4091). LOAD(full) is a Phase built at 4156 and destroyed at 4164, so it times only loadExperiment. The failed attempt's wall time lands in TOTAL's unattributed remainder, not in any row.
3. Ledger: the streaming load charges three rows:
   - LC_SCRATCH: RAII LedCharge at 2028 and 2144, plus the function-static scratch_charged exchange at 2033-2035
   - LC_SLAB: 2115
   - LC_MS1MAP: 2181
   LC_SLAB and LC_MS1MAP are zeroed at 4155. The static scratch charge is never subtracted: the vectors it tracks are consumer members (2263) that die at 4142. It therefore goes stale after a successful stream as well, and tile pass-2 consumers re-exchange it. On the default .d pass 1 (MS1 only), flush_ returns at 2020 (n==0) before charging, so a fallback there leaves nothing stale; with SPEXTRACTOR_TILE_RESIDENT=1 or an MS2-delivering stream it stays. It only affects SPEXTRACTOR_LEDGER output.
4. Everything that affects output resets correctly. fix_gate/c3 r2d_fb (fallback after all 100 MS1 frames were denoised with SPEXTRACTOR_PICK_BATCH_MS1=1) matches r1d_res (pure resident):
   - the same [dnoise] line: 100 frames, 19851651 raw, kept 51683 (not doubled)
   - MS1 traces digest 18155112766412898203
   - precursors digest 2452216238564024572

FIX: Nothing is needed for output. Optional ledger hygiene: make scratch_charged a PickCompactConsumer member and subtract it in ~PickCompactConsumer (`ledAdd_(LC_SCRATCH, -scratch_charged_)`). Optionally zero ms1Hist_() in the reset block, which matters only if a resident [ms1-hist] print is ever added. Phase rows need no change.

TEST: Existing proof of the reset: c3 r2d_fb vs r1d_res (identical [dnoise] line and digests); keep it in the gate. For the ledger fix, run a SPEXTRACTOR_TILE_RESIDENT=1 fallback on g1.d with SPEXTRACTOR_LEDGER and assert scratch_mib returns to 0 after the load phase.


## [REFUTED/none] kimi #8 (sub-question): LedCharge _raw(LC_SCRATCH, raw_b) in flushMS1_ might leak raw_b when the parallel loop rethrows

EVIDENCE: 1. LedCharge is strict RAII: the constructor adds, the destructor subtracts, and copying is deleted (spextractor.final.cpp:254-262).
2. In flushMS1_, _raw is a function-scope object (2144). Every exception is caught inside the parallel region (2155-2167) and rethrown serially at 2169, so unwinding runs ~LedCharge. A DnoiseError from checkLoader() at 2149 is also thrown after _raw exists.
3. Nothing on the way to the handler blocks unwinding:
   - IMSDataConsumer::consumeSpectrum is not noexcept (IMSDataConsumer.h:62).
   - The loader hands frames over serially at BrukerTimsFile.cpp:1614, after its own omp region (1587-1612) has closed, with no try around consumer calls.
   - consumer.finish() at 4079 is serial.
   - The handler is at 4104-4110.
4. flush_ has the same shape (LedCharge at 2028, pick_err rethrow at 2069).

FIX: None.

TEST: None needed; the c3 fallback arms with SPEXTRACTOR_LEDGER would show scratch_mib back at its pre-batch value if it ever mattered.


## [REFUTED/none] vibe #7: an exception from detectTraces_'s serial preamble escapes the omp single block and terminates the process

EVIDENCE: 1. The try covers the whole call. At spextractor.final.cpp:4406-4416, `#pragma omp parallel` / `#pragma omp single` is followed by `try { ms1_traces = detectTraces_(...); } catch (...) { ms1_err = std::current_exception(); }`, and `std::rethrow_exception(ms1_err)` runs after the region. Any exception from detectTraces_'s own code is caught inside the single and rethrown serially. That covers the MassTraceDetection parameter setup, the band-edge sample and sort, the [ms1-edges]/[tstage] logs, the gather, and the bands==1 `mtd.run` at 2944 (whose 'too few MS1 spectra' throw is MassTraceDetection.cpp:265). The ms1_prune precondition throw sits outside the region (4398-4401).
2. A different gap remains, and the comment at 4404-4405 acknowledges it: exceptions inside the three taskloop bodies (2839 distribution, 2917/2926 per-band m2.run, 2970 valley split) escape explicit tasks and call std::terminate, i.e. SIGABRT. perf:ms1_trace_bands defaults to 48 (2605), so this code path is the default. MassTraceDetection can throw there at MassTraceDetection.cpp:127 (IM array size != spectrum size) and 135 (IM arrays present in some spectra but not all); line 265 is guarded by `sub[b].size() < 3` (2925).
3. That gap fails closed: the process aborts and writes no output, nothing is silent. dnoise-emptied frames keep their IM array, and the D gate runs with 2 emptied frames completed.

FIX: Nothing for vibe's claim. For the task-body gap (low priority, clean exit instead of abort): wrap each taskloop body in `try { ... } catch (...) { #pragma omp critical(ms1_task_err) if (!task_err) task_err = std::current_exception(); }` and rethrow after the taskloop (it has an implicit taskgroup), still inside the single, so the existing 4415 handler takes it.

TEST: Optional: an env-gated fault in band 0 of the MS1 band taskloop; assert the tool exits with the OpenMS error code (not 134/SIGABRT) and logs the message.


# nan-mz

## [PARTLY/low] codex #8 / kimi #9 / vibe #6: Ms1Prune::frame sorts (sortByPosition) before it notices a non-finite m/z and takes its stride-97 sample from that order, so a spectrum it keeps whole has already been reordered and sampled; the reviewers say prune on can then differ from prune off.

EVIDENCE: REFUTED: the stated mechanism. Kimi says that with the prune off the spectrum reaches the band builder in picked order. It does not: the prune-off path calls ms1_map.sortSpectra() at spextractor.final.cpp:4337, and sort_mz defaults to true (MSExperiment.h:1101). MSExperiment.cpp:792-802 then calls the same MSSpectrum::sortByPosition on every spectrum. That function returns early when isSorted() holds and otherwise runs a std::stable_sort (MSSpectrum.cpp:405-419, MSSpectrum.h:361-365).

Probe verify2/omsort.cpp, built against the in-tree libOpenMS.so with g++-13/libstdc++: 200,000 spectra carrying NaN or inf, with and without an Ion Mobility array. After one sortByPosition, isSorted() was false 0 times and a second call changed the spectrum 0 times. A libc++ replica (scratchpad verify2/sortprobe.cpp): 0 of 400,000. So on both platforms frame()'s sort gives the same permutation prune off gets at 4337, and the later sortSpectra is a no-op. The per-spectrum sample (1730 vs 2808) is identical.

CONFIRMED: the concern underneath. Keeping such a spectrum whole guarantees neither identity nor correctness.
(a) Both arms are silently wrong today. The 'sorted' output has its finite m/z out of order in 179,701 of 200,000 probe spectra, yet isSorted() is true, so the band builder takes the lower_bound branch (2849, 2863-2868) and misplaces peaks. A NaN can land on an interior quantile edge (2809-2814), and then both core tests at 2932 (c >= NaN, c < NaN) are false, dropping every trace between edge[b-1] and edge[b+1]. MassTraceDetection::findBestPeak_ with a NaN centroid gets MZBegin = begin and MZEnd = end, and the abs(mz - NaN) comparison is always false, so it takes the first peak that matches in ion mobility (MassTraceDetection.cpp:307-337). None of this logs anything with the prune off.
(b) A residual divergence between the arms. The prune's sample is concatenated in load order (1776, 2805). Prune off samples the map after its RT sort (2807). std::sort of a sample containing NaN depends on input order: 17,249 of 20,000 shuffles moved a 24-band edge. It bites only if load order differs from RT order, or if MS1 RT values tie. Both D (1,343 MS1 frames) and TNBC 009 (4,797) have strictly increasing Time in Id order with no ties.
(c) The formal UB codex cites (NaN breaks strict weak ordering) also happens upstream of both arms: BrukerTimsFile.cpp:1604/1768, MzMLHandler.cpp:146-148, PeakPickerIM.cpp:1236, and the stable_sort in MzPeakStreamLoad.h. The tool cannot avoid those sorts, and the probes show they are deterministic.

REACHABILITY. Default-on dnoise on a Bruker .d refuses a non-finite raw MS1 m/z before the pick: mzToTof(NaN) fails the |t-bin| <= kTofTol test (1913-1915). With dnoise off, TdfMzCalibration::tofToMz returns NaN only for t <= C0, disc < 0 or u*u <= C4 (TdfMzCalibration.h:109-114). D: t at tof 0 = 25655.375 against C0 = 279.33, C4 = 0. TNBC: t at tof 0 = 25030.2 against C0 <= 314.60, C4 <= 0.004678 (NaN only below m/z 0.005). So real bins cannot produce NaN.
Gate logs: every D [ms1-prune] line in dnoise_gate and fix_gate has bad_mz 0, up to 725,116,915 picked peaks, and there is no [compact] DROPPED line. The TNBC gate logs predate the bad_mz field.
It is reachable from:
- mzML: MzMLHandler.cpp has no isfinite/isnan check.
- mzPeak only with SPEXTRACTOR_MZPEAK_EXACT=0, where frameToSpectra_ passes archive m/z through unchanged; the default exact path throws (MzPeakStreamLoad.h:162-169).
- An infinite intensity in mzML: the centroid becomes inf/inf = NaN (PeakPickerIM.cpp:1189-1190).
PeakPickerIM spreads NaN: std::min/std::max ignore a NaN candidate, so it joins a cluster and makes that cluster's centroid NaN.

The tool was not run end to end. The only cluster build is the published dnoise_s2b binary, and it is running the memory benchmark on D on ibminode05 (pgrep; load about 85).

FIX: Fail closed on both paths. Check every MS1 spectrum right after its pick, which is before the prune and independent of it. Both arms then refuse exactly the same inputs, and nothing after the pick ever sees a non-finite m/z.

(1) After shrinkDataArrays (frozen line 1694):

  /// [ms1-finite] Refuses an input with a non-finite MS1 m/z. Nothing after the pick is defined on one, prune on or off:
  /// sortByPosition leaves finite m/z out of order around a NaN while isSorted() stays true, a NaN band edge leaves two
  /// band cores owning nothing, and MassTraceDetection's m/z search matches anything. Rethrown past the stream fallback.
  struct Ms1MzError : Exception::InvalidValue { using Exception::InvalidValue::InvalidValue; };
  inline void requireFiniteMs1Mz(const MSSpectrum& s)
  {
    for (Size i = 0; i < s.size(); ++i)
      if (!std::isfinite(s[i].getMZ()))
        throw Ms1MzError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                         "[ms1] MS1 spectrum has a non-finite m/z (" + std::to_string(s[i].getMZ()) + ") at peak " + std::to_string(i)
                         + " of " + std::to_string(s.size()) + " after peak picking; the input is malformed and the run is refused", s.getNativeID());
  }

(2) flushMS1_, inside the try, after the ensureIMArrayName(s) that follows the pick (2161):
          requireFiniteMs1Mz(s);   // [ms1-finite] before the prune, prune on or off

(3) Resident pick loop, after ensureIMArrayName(s) (4220):
        if (s.getMSLevel() == 1) requireFiniteMs1Mz(s);   // [ms1-finite] exactly the spectra the prune and the MS1 map take

(4) Stream fallback, next to the DnoiseError line (4105):
      catch (const Ms1MzError&) { throw; }        // [ms1-finite] a refusal of the input, not a reader failure
Without this the stream load reads the whole run a second time only to refuse it. Consumer exceptions reach this catch unwrapped: BrukerTimsFile.cpp:1614 calls consumeSpectrum outside any try, and so does MzPeakStreamLoad.h:413.

(5) Ms1Prune::frame: replace line 1759 with
      if (!finite) requireFiniteMs1Mz(s);   // [ms1-finite] unreachable, both load paths refuse first; throws if a future entry point skips them
and change the comment at 1757-1758 to match. At 4278, drop the " (bad_mz: spectra with a non-finite m/z, kept whole)" suffix. Keep the numeric bad_mz field, now always 0, so PRUNE_RE and check 19's bad_mz == 0 stay valid.

Cost: one extra read of the picked MS1 m/z per spectrum, inside the existing parallel pick loops. That is negligible next to the pick.

TEST: Add check 19d to test/test_spextractor.py after 19c, and add 1 to `total`:

    # 19d: a non-finite MS1 m/z is refused after the pick and BEFORE the prune, prune off and on alike.
    def c19d():
        for tag, bad in (("nan", float("nan")), ("inf", float("inf"))):
            inp_n = os.path.join(work, f"prune_{tag}.mzML")
            synth(inp_n, n_cycles=21, ms1_extra=lambda c: prune_extra(c) + ([(bad, 5000.0, 0.95)] if c == 10 else []))
            for bands in (1, 48):
                for prune in ("false", "true"):
                    r = run(binary, inp_n, os.path.join(work, f"{tag}_b{bands}_{prune}.mzML"),
                            extra=("-perf:ms1_trace_bands", str(bands), "-perf:ms1_prune", prune), expect_fail=True)
                    log = r.stdout + r.stderr
                    assert "non-finite m/z" in log, f"{tag} bands {bands} prune {prune}: not refused for its m/z:\n" + log[-800:]
                    assert "[ms1-prune]" not in log, f"{tag} bands {bands} prune {prune}: refused only after the load summary, not at the pick"
    check("a non-finite MS1 m/z is refused before the prune, prune off and on", c19d)

Why it pins the fix: synth packs m/z as float64 (19c decodes '<d'), so NaN and inf survive the mzML round trip. Today all 8 arms exit 0, so the check fails. With the fix all 8 refuse. The [ms1-prune] line is logged at 4272, after the resident prune, so its absence shows the refusal happens in the pick loop. The stream-fallback passthrough (4) runs only on streamed .d/mzPeak input and stays covered by the cluster gates, as flushMS1_ already is.


# tests-and-claims

## [CONFIRMED/medium] kimi #2 / codex #11: no automated test covers DnoiseRun point recovery (TOF from m/z, scan from float32 1/K0, raw from corrected intensity, frame/NumPeaks checks)

EVIDENCE: Code and tests:
- tests/test_dnoise_ms1.cpp:8 includes only DnoiseMs1.h.
- Searching tests/ and test/ for mzToTof, scanOf, AccumulationTime, TimsCalibration, NumPeaks or DnoiseRun finds nothing.
- The recovery exists only in spextractor.final.cpp: 1843-1845 (corr check), 1846-1865 (scan table), 1879-1888 (scanOf), 1898-1904 (frame checks), 1911-1927 (per-point loop). The correction itself is TdfLoad.h:220.
- Check 20 (test_spextractor.py:689-705) runs only an mzML.
- synth_tdf (test_spextractor.py:147-180) writes no TimsCalibration, AccumulationTime or NumPeaks.
- The node unit test (sync_cluster.sh:73) compiles only test_dnoise_ms1.cpp.

Feasibility, measured from D/TNBC metadata only. Probe: verify2/recover_probe.cpp, frozen inverse against the loader's forward code (TdfMzCalibration::tofToMz, RationalScan2ImConverter.cpp:47-55 plus frameToSpectrum's float cast, opentims.cpp:74/225).
- TOF: every bin recovers (634,073 on D, 399,967 on TNBC). Max |t-bin| is 2.33e-10 / 1.16e-10; half-bin m/z are refused.
- Scan: both tables fall with the scan, minimum step 8.78e-4 / 1.10e-3. Every scan recovers, also at +-1 ulp, and every half-scan is refused. TNBC scan 917 gives 0.602016032, which equals OneOverK0AcqRangeLower, so scans are 0-based.
- Intensity: every raw count whose corrected value is below 2^24 (16.77 M per file) recovers uniquely at corr('99.958') and corr('99.953'). 7,046 / 7,885 values have no preimage (the first are 1190 / 1064) and are refused.
- On both files, (raw*100)/at and fma(raw,corr,0.5) agree with opentims at every raw count.
- tie_probe.cpp, over 1,001 AccumulationTime texts from 99.500 to 100.500: (raw*100)/at differs for 3 texts, fma for none. Example: '99.968', raw 1562 gives 1562 in opentims but 1563 in the other order, and recovering 1563 finds 0 hits (refused).
- Any corr below 1 is refused almost at once ('120' at raw 3, '100.001' at raw 50000).

Mitigation today: every check runs per point, fails closed, and runs during pass 1, where MS1 comes first. A regression mostly refuses early; only a forward and inverse that drift together would pass silently.

The Apple default-contraction build moved TNBC tofToMz(100000) by 2 ulps, so m/z must not be compared as hex literals.

FIX: Move the maths out of spextractor.cpp: 57 lines from the ranges above, plus TdfLoad.h:220. It becomes a dependency-free section of src/DnoiseMs1.h, namespace spx::dnoise::recover, about 75 lines with comments, placed inside the existing push_options / fp contract(off) region so the guard travels with it:
- `inline double opentimsCorrection(const char* acc_text)`: 100.0/atof, as opentims.cpp:74. TdfLoad.h calls it.
- `inline bool corrInvertible(double corr)`
- `inline std::string buildScanTable(const std::array<double,10>& C, std::size_t n_scans, std::vector<float>& asc, bool& falls)`: empty string or the reason.
- `inline long scanOf(const std::vector<float>& asc, bool falls, float v)`: verbatim.
- `enum class Refusal { none, frame, peaks, im, tof, scan, intensity };`
- `inline Refusal frameCheck(std::uint32_t fid, std::size_t n_frames, int msms_type, std::uint32_t num_peaks, std::size_t n, std::size_t im_n)`
- `template <class Cal> inline Refusal recoverPoint(const Cal& cal, double b, double mz, float im, float inten, double corr, const std::vector<float>& asc, bool falls, std::uint32_t num_scans, std::uint32_t& tof, std::uint32_t& scan, std::uint32_t& raw, int& hits)`

The template keeps DnoiseMs1.h free of the calibration header. The tool instantiates it with <OpenMS/FORMAT/TdfMzCalibration.h>, the test with src/TdfMzCalibration.h; sync_cluster.sh:30 ships the same file to both.

DnoiseRun::setup and frame become adaptors that map a Refusal to today's messages, about 40 lines shorter overall.

No CMake change: test_dnoise_ms1 already builds with src and -ffp-contract=off in both modes. One change in sync_cluster.sh:73: add -I/scratch/kohlbach/OpenMS/src/openms/include/OpenMS/FORMAT so the node test finds the deployed TdfMzCalibration.h.

TEST: Add testRecover() to tests/test_dnoise_ms1.cpp, about 120 lines. The exhaustive loops take about 1 s at -O2; use stride 7 above 2^20 if CI runs -O0.

Inputs are metadata constants only:
- D MzCalibration: timebase 0.125, delay 25655.375, C0 279.3262846272992, C1 155279.13067653627, C2 0.001260061434461731, T1_ref 25.693668980735552, dC1 20; frame-1 T1 25.727120813485598.
- TNBC MzCalibration row 1: 0.2, 25030.2, 314.59993079240667, 155508.97802581752, 0, 25.41837029204028, 20; frame-1 T1 25.393315017452863.
- TimsCalibration C0..C9, D: {1, 943, 234.09826168388614, 95.59372590131042, 33.9622641509434, 1, -0.0031464178402676644, 167.9496150068565, 16.646316600032645, 2241.865411900982}, 944 scans.
- TimsCalibration C0..C9, TNBC: {1, 917, 217.9811466010841, 74.83820441307512, 33.0, 1, 0.02256006096271849, 131.32054866963384, 12.961442137235451, 2637.0446006790567}, 918 scans.

The forward model lives in the test, separate from the inverse: tofToMz; loaderIm = float(applyFormula) copied from RationalScan2ImConverter.cpp:47-55; opentims = uint32(double(raw)*corr + 0.5), then float.

1. TOF
- Every bin of both files goes tofToMz, then recoverPoint, and returns the bin.
- tofToMz(tof+0.5) and mz*(1+1e-6) give Refusal::tof.

2. Scan
- falls == true for both files.
- Hex goldens, D scans 0/1/472/943: 0x1.6e4c14p+0, 0x1.6e124p+0, 0x1.03cfc8p+0, 0x1.33a7e6p-1.
- Hex goldens, TNBC scans 0/1/459/917: 0x1.a33458p+0, 0x1.a2ec16p+0, 0x1.201aa4p+0, 0x1.343b72p-1.
- Every scan recovers, also at +-1 ulp; applyFormula(s+0.5) gives -1 for every s.
- Scan 943 in a frame with num_scans 943 gives Refusal::scan.
- A row with C3 == C2 is refused by buildScanTable.

3. Intensity
- opentimsCorrection('99.958') == 0x1.001b896437031p+0 and ('99.953') == 0x1.001ed0ffd561bp+0.
- Every raw count below 2^24 after correction recovers uniquely on both files.
- v 1190 (D) and v 1064 (TNBC) give 0 hits.
- Tie golden, text '99.968': raw 1562 gives v 1562, which recovers to 1562 with 1 hit; v 1563 gives 0 hits.
- v 0 gives raw 0; v 12.5, -1 and 16777216 are refused.
- '125' (corr 0.8): v 2 gives 2 hits. '50': raw 2^23 gives v 16777216, refused.
- corrInvertible(0.5) is false.

4. frameCheck
- fid 0, fid past the table, msms_type 9, n != NumPeaks and IM size != n are each refused; n == 0 passes.

Confirm the scan hex goldens once against the linked OpenMS::RationalScan2ImConverter::applyFormula after the benchmark. The probe used a verbatim copy; OpenMS.dir and spextractor.dir both build -O3 -ffp-contract=off with no -march.


## [REFUTED/low] kimi #6: emptied-frame identity with the preprocessor pipeline asserted, not demonstrated; loader handling of zero-peak MS1 frames

EVIDENCE: D did empty frames:
- '[dnoise] ... 1343 frames (2 emptied)' appears in dnoise_gate G2 (100 threads) and G3 (8 threads), and in fix_gate F3, F4 and F5.
- TNBC T2 reports 0 emptied.

dnoise's den.d keeps those frames as rows:
- dnoise_eval/D/default/den.d/analysis.tdf has 1,343 MS1 frames, 2 of them with NumPeaks=0 (Ids 17330 and 17356).
- SUM(NumPeaks) is 118,053,254, the in-tool kept count.

The reference run did not skip them:
- prune_gate/DN_off/e.log shows 'frame-by-frame load done: 1343 frames, MS1 1343'.
- It also shows 'MS1 1343 frames / 43546607 peaks', the same pick count as G2/F3.
- Digest e43672a0 in DN_off, DN_on, G2, G3, F3 and F4.

Mechanism:
- BrukerTimsFile.cpp:1194: frameToSpectrum returns an empty spectrum with no IM array when num_peaks is 0.
- The MS1 streaming loop consumes every slot (1614), and flushMS1_ adds every buffered spectrum (spextractor.final.cpp:2182).
- A frame emptied in-tool keeps its IM array: MSSpectrum::select swaps only the float vector, and containsIMData tests the array's unit, not its size (MSSpectrum.cpp:769-786).

Residual (the finding's premise is still refuted):
- The brief's 'resident .d path' was F4 (SPEXTRACTOR_TILE_RESIDENT=1), which still streams ('33553 frames').
- The loadExperiment path (-perf:stream_load false, or a stream fallback) never ran with an emptied frame: c3 r1d_res reports '100 frames (0 emptied)'.
- On that path the in-tool frames stay (IM array kept; dispatch at 4217/4237).
- A zero-peak frame without an IM array, as in den.d or any raw .d with such MS1 frames, is dropped by `if (!s.containsIMData()) continue;`, although the loader added it (2664-2666). The two loader paths therefore disagree for such input.
- Whether 1341 against 1343 scans changes the output is unmeasured. The in-tool default is unaffected.

FIX: No change to the in-tool path.

Correct the record: D emptied 2 MS1 frames (17330, 17356); den.d delivered all 1,343 through the streaming loader; the 'resident' arm was the TILE_RESIDENT streaming consumer.

Optional consistency fix: keep a zero-peak MS1 spectrum as a scan on the loadExperiment path too. At spextractor.cpp:4217 and 4237: `if (!s.containsIMData() && !(s.getMSLevel() == 1 && s.empty())) continue;`. pickIMCluster already handles such spectra on the streaming path (DN_off completed). No pin moves: raw D and TNBC have no zero-peak MS1 frames.

TEST: Cluster, after the benchmark:
- D defaults with -perf:stream_load false: must give e43672a0, with 2 emptied. This is the untested in-tool loadExperiment path.
- den.d with -perf:stream_load false -dnoise:ms1 false against e43672a0: this measures the preprocessor path's own drop.

e2e, with the dispatch fix: a synth fixture with one MS1 spectrum that has zero peaks and no IM array. Assert that the 'Split into MS1 ... MS1 <n> frames' count includes it, and that the digest and the [det] MS1 lines equal the twin fixture where that spectrum holds one below-noise peak.


## [REFUTED/low] kimi #7: help-text memory and wall figures were measured with dnoise as a preprocessor, not in-tool

EVIDENCE: The figures are the in-tool gate runs, byte for byte:
- dnoise_gate/driver.log (ibminode05, binary fd30bf0e, 100 threads, -tile:cells_per_tile 1, prune at default): G1 -dnoise:ms1 false, 26,455,236 kB, 4:23.33; G2 defaults, 22,413,952 kB, 3:44.04.
- dnoise_gate_tnbc/driver.log (spock, dnoise_s2a = fd30bf0e): T1 34,665,972 kB, 9:47.46; T2 25,406,164 kB, 8:18.01.
- That is 26.46 to 22.41 GB (-15.3%) and 34.67 to 25.41 GB (-26.7%), wall -14.8% and -15.2%; also BASELINE.md:3119-3123.

The preprocessor numbers differ: BASELINE.md:3089 gives MS1-only peaks of D 21.41 and TNBC 25.08 GB. The per-thread Work scratch is therefore already inside the quoted peaks.

The preprocessor parenthetical at spextractor.final.cpp:2682-2683 ends before 'Against the default perf:ms1_prune true...'.

Caveat: these were measured before the fix pass. The fix-pass build 2d9aa6c4 in the same configuration (fix_gate F2/F3) gives 25,976,156 to 22,647,520 kB (-12.8%) and 4:17.80 to 3:49.39 (-11.0%). The same-config spread between builds is 26.46/25.98 and 22.41/22.65 GB, at node load 55-95.

FIX: None required. Optionally add '(in-tool, 100 threads)' after the figures, or replace them with the dnoise_s2b final benchmark when it lands, keeping -15%/-27% only if that run reproduces them.

TEST: None: this is benchmark provenance, not code.


## [REFUTED/none] kimi smaller item: check 20's `assert "[dnoise]" not in log_off` is brittle

EVIDENCE: No `[dnoise]` line can be emitted with -dnoise:ms1 false:
- Lines 3940 and 3966 require dnoise_req.
- Line 4271 requires dnoise.on.
- Lines 1874 and 1897 are DnoiseError texts, thrown only from checkLoader() and frame(). Those are called only when dnoise is on (2148-2159, 4208-4218).

run() asserts exit 0 (test_spextractor.py:192), so an error text cannot reach log_off on a passing run.

The assertion breaks only if someone deliberately adds a [dnoise] line to the off path. That would contradict what the check pins: off is silent and stamped 'off'.

FIX: None. Scoping it to named lines would only weaken the check.

TEST: n/a


## [CONFIRMED/low] codex #12: dnoise:iterations help says '0 keeps every point', but the halo and the window gate still run

EVIDENCE: - DnoiseMs1.final.h:495: iterations gates only the streak loop (`pass < p.iterations`). The halo (505, `if (p.halo && m > 0)`) and the gate (544-549) run regardless.
- The Rust transliteration does the same (test_dnoise_ms1.cpp:546-577), so these are dnoise's semantics.
- testHalo (test_dnoise_ms1.cpp:364-379) already runs with iterations = 0 and expects the halo to drop 9 of 24 points.
- The wrong text is in the help (spextractor.final.cpp:2690) and in the Params comment (DnoiseMs1.final.h:86).
- The default is 2, so only a user trying to switch filtering off is misled.

FIX: Help text for dnoise:iterations: "Streak filter passes, each over the previous pass's survivors; 0 skips the streak filter, and the halo filter and the window gate still run unless dnoise:halo / dnoise:dia_ms1_window are false (dnoise --iterations)."

DnoiseMs1.h:86 comment: `///< streak passes, each over the previous survivors; 0 = no streak pass (halo and gate still apply)`.

Rename the check at test_dnoise_ms1.cpp:305 to "iterations 0: the streak filter keeps every point".

TEST: The halo side is already pinned by testHalo:364. Add the gate side to testGateAnd, which uses the fixture at lines 406-409 (10 points; the halo keeps all 10, the gate keeps 3):
`dn::Params p0; p0.iterations = 0; const Run r0 = run(f, 100, p0, gate ? &*gate : nullptr); CHECK(r0.counts.after_halo == 10 && r0.counts.kept == 3, "iterations 0 still runs the halo and the gate");`


# deploy-script

## [CONFIRMED/medium] codex #3 / kimi #3: scripts/sync_cluster.sh uploads the source, headers and unit test before taking the remote lock, and a unit-test or build failure restores only the .cpp, so new headers stay in the tree.

EVIDENCE: Script (repo scripts/sync_cluster.sh, sha b8740df0):
- Every shared write happens before the patch check at :57 and the lock at :63. Line :27 uploads to a fixed `${REMOTE_SRC}.new`, :30 puts TdfMzCalibration.h straight into the OpenMS include dir, :33 puts TdfLoad.h, MzPeakStreamLoad.h and DnoiseMs1.h into src/topp, and :36-54 ship the suite, golden file, unit test, bench tools, launcher and chmod. So a deploy refused for the lock or for a missing patch has already rewritten the tree.
- Provenance hashes are computed locally (:22-25), not from the files the node builds.
- Both failure branches (:74, :80) restore only the .cpp, from a `cp -p` backup that keeps the old mtime. They then print 'binary and provenance unchanged'.

Cluster, read-only:
- 90 deploys in deploys.log, 25 of them between 09-09 14:32 and 09-10 18:53.
- 16 of 107 build_sync logs failed. 15 of those relinked libOpenMS.so and compiled BrukerTimsFile.cpp.o before the tool failed, with no tool link (e.g. build_sync_20260909-122626/122736/122834).
- BrukerTimsFile.cpp.o.d lists TdfMzCalibration.h. So a failed deploy that changes the calibration header leaves libOpenMS.so built with the new header, while the provenance still states the old libopenms_sha256 and calibration hash.
- verify_publish.sh:24-25 copies build/bin, the provenance and build/lib with no lock and no hash cross-check.
- The calibration hash (21ad90c3) is the same in the last 30 deploys, so no calibration mix has actually landed recently. The risk is latent.

Probes:
- make: a header restored with its old mtime leaves 'a.o is up to date' (stale object kept). After `touch` it recompiles.
- scp overwrites in place: inode 264767968 before and after.
- A remote non-pty command survives a killed ssh client but dies on its first write to the dead channel (marker line 1 written, line 2 not). bash 5.2 runs the EXIT trap on HUP, TERM and PIPE.
- Sandbox harness running the ORIGINAL script reproduces 5 violations:
  - R1, build failure: new TdfLoad.h and calibration header left in the tree, provenance no longer matches libOpenMS.so, new suite and tools shipped.
  - R2: a deploy REFUSED because the lock was held changed 13 node entries.
  - R3, unit-test failure: the new DnoiseMs1.h stays.

Kimi's parenthetical is wrong: a failed deploy exits before the printf, so the old provenance stays and it is libopenms_sha256 that becomes false, not tool_headers_sha256. Neither reviewer's fix covers the libOpenMS relink, the mtime problem or refusals that still write.

FIX: Replace the script with /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify2/sync_cluster.proposed.sh. The exact change as a unified diff is verify2/sync_cluster.patch. Real cluster paths now appear only in three root assignments (R, TOOLS, TESTS); shellcheck is clean.

(1) Local side: keep the same dirty check. Create `STAGE=$(ssh node mktemp -d $R/.deploy.stage.XXXXXX)`. Write SHA256SUMS for every input and shipped file. Upload everything plus a node-side txn.sh into $STAGE with one scp. Nothing shared is written.

(2) Run `ssh node "bash $STAGE/txn.sh $STAGE $GITREV $R $TOOLS $TESTS > $STAGE.log 2>&1; rc=\$?; cat $STAGE.log; exit \$rc"`. The transaction writes only to its log, so a dropped channel cannot kill it with SIGPIPE.

(3) txn.sh does, in order:
- `mkdir $LOCK`, or REFUSE (removing only the stage).
- `trap finish EXIT`, then write an owner file.
- `sha256sum -c` on the staged files, then the calibration patch check.
- Compile and run the unit test from the stage, before anything is promoted. It includes the staged DnoiseMs1.h, which is the same file later renamed into src/topp.
- `cp -p` backups of all 5 build inputs; move the provenance aside to $S/prov.prev.
- Promote each input with `mv` plus `touch`. Every tree dir is on the /scratch nvme device, so the rename is atomic.
- `make spextractor -j32`.
- Re-check the promoted hashes. This catches writers outside the lock; apply_openms_patches.sh:21 installs the header without taking it.
- Compute the provenance on the node from the promoted files, then `COMMITTED=1; mv provenance.tmp provenance`.
- Only after that: append deploys.log, keep the old .cpp as .bak, copy the suite, golden file, bench tools, launcher and unit-test source and log, `chmod 771` the launcher.

(4) finish(), if not committed:
`for f in $PROMOTED; do d=$(dest $f); if [ -e $S/bak/$f ]; then mv -f $S/bak/$f $d && touch $d; else rm -f $d; fi; done`
Put prov.prev back only if `binary_sha256` AND `libopenms_sha256` match the current bin/spextractor and lib/libOpenMS.so. Otherwise move it to `$PROV.stale` and print FAIL-CLOSED, leaving no provenance. In every case: `rm -rf $S; rm -f $LOCK/owner; rmdir $LOCK`.

TEST: Harness: /private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/verify2/txn_harness.sh. It uses a fake node where libOpenMS relinks before the tool compiles (real make and mtime rules) and ssh/scp shims. It aborts unless the shims are first on PATH and no real path survives substitution.

The proposed script passes 18/18 checks across scenarios S0-S8:
- S0-S1: first deploy and a normal deploy commit.
- S2, unit-test failure: node byte- and mtime-identical.
- S3, build failure with a calibration change: all inputs restored; provenance absent (parked as .stale); `! make -q lib/libOpenMS.so`; make on the restored tree reproduces the parked hashes.
- S3b, build failure without a calibration change: provenance restored and matches the files.
- S4, lock held: node identical.
- S5, concurrent deploy: B refused; tree, tools and provenance are exactly A's, with no byte of B anywhere.
- S6, missing patch: refused, node identical.
- S7, torn upload: refused, node identical.
- S8, a write outside the lock during the build: refused, no provenance.

The original script fails R1-R3 (5 violations). Four mutants (no touch, unconditional provenance restore, .cpp-only restore, no post-build recheck) each fail 3-6 assertions. To pin this, commit the harness as tests/test_sync_cluster_txn.sh aimed at scripts/sync_cluster.sh and run it in CI on Linux (on macOS it needs the date shim).


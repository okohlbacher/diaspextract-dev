The negative-C2 root is correct, and the supplied PXD029836 evidence supports accepting those files. I found no demonstrated mass error on those real runs. However, the implementation does **not** establish the claimed domain guarantee across every loader and caller, and the four digest pins remain unverified.

I inspected the branch read-only and ran the Python golden test: **270 cases passed; maximum error 0.0000314 ppm**. I did not rebuild C++, run the SDK, or run the spectrum digest gate. No files were changed.

**1. Root choice**

Write \(a=|C2|>0\), \(x=t-C0>0\), and assume finite \(b>0\). Then

\[
a u^2-bu+x=0,\qquad
u_\pm=\frac{b\pm\sqrt{b^2-4ax}}{2a}.
\]

For \(0<x<b^2/(4a)\), both roots are positive. Rationalizing the smaller root gives

\[
u_-=\frac{2x}{b+\sqrt{b^2-4ax}}.
\]

Its slope is \(b-2au_-=\sqrt{\mathrm{disc}}>0\); the other root has negative slope. The shipped expression therefore always selects the rising branch under these assumptions.

As \(C2\to0\), it tends to \(x/b\). Stored `-0.0` takes the zero-C2 acceptance path and produces the same positive finite results as `+0.0`. There is no branch-flip bug.

For negative finite `b`, the denominator guard rejects the negative-C2 solution; it does not silently select the descending root. Non-finite arithmetic is a separate problem discussed below. Also, passing a descending-branch **mass** into `mzToTof` and converting back necessarily returns the smaller mass: that is a caller-domain error, not a root-selection error.

**2. Domain-check correctness**

The algebra is right:

\[
t_{\rm zero}=C0+\frac{b^2}{4a},\quad
t_{\rm half}=C0+\frac{3b^2}{16a},\quad
u_{\rm half}=\frac{b}{4a}.
\]

The largest TOF is the deciding TOF corner because the timebase is positive. The largest temperature multiplier gives the smallest `b`; `fabs(dC1)` correctly handles both signs. The m/z upper condition is correct **where \(m+C4\ge0\)**.

There are two concrete limitations:

- **LOW — theoretical extreme-input failure:** `src/TdfMzCalibration.h:155–159` can accept a finite row with a negative discriminant inside the promised domain. Use `ModelType=1`, `C1=1000000`, `C2=-0.25`, `C0=2^72`, `DigitizerDelay=2^72+1048576`, `DigitizerTimebase=1e-9`, and all drift/offset fields zero. Here `b=1000`. Adding `750000` to `C0` rounds upward by `1048576`, making `t_half == t_max`. The row passes, but at **TOF 0**, `disc = 1000000−1048576 = −48576`. This also makes the refusal-index arithmetic unreliable at extreme offsets. It cannot describe a plausible instrument calibration.

  Overflow provides another all-finite counterexample: `C1=100000`, `C2=-1e-310`, `C0=delay=C4=dC1=0`, `timebase=1e308`. Both checked time limits become infinity, so the row passes; **TOF 2** produces `disc=-inf`.

- **LOW — theoretical invalid inverse input:** `src/TdfMzCalibration.h:132–133,159` checks no lower bound on `mz+C4`. Use `C1=1000000`, `C2=-0.001`, `C4=-200000`, `C0=0`, `delay=100`, `timebase=0.001`, `dC1=0`. The row passes. `mzToTof(100,1000)` returns **99900**, although `sqrt(100−200000)` has no real value; converting back gives approximately **200000.03996**, not 100. This is inherited clamping behavior newly reachable with accepted negative C2. The large offset is synthetic; the realistic `C4=-0.0905` also requires care for search bounds below 0.0905.

The NaN-only screen does not establish finiteness. For example, the PXD1418 row with `C0=+inf`, or separately `digitizer_delay=-inf` or `C4=-inf`, passes `unsupportedReason()`. Its resulting conversions are unusable. The `C2=-inf` test proves rejection only for its particular otherwise-normal row.

Thus the check is sound in ordinary finite arithmetic on the physical m/z interval, but not universally conservative over arbitrary accepted floating-point rows.

**3. Is the domain the right one?**

**MEDIUM — theoretical/corrupt-input exposure, not demonstrated on PXD029836:** `src/diaspextract.cpp:675–677`, `src/MzPeakStreamLoad.h:132,154–155`, and `patches/openms-brukertims-mz-calibration.patch:183–188` leave the declared domain unenforced.

Crucially, `loadTdfAxisBounds` rejects invalid **metadata**, while `loadTofAxis` still returns success when that read fails. Even valid metadata does not validate the decoded peak indices.

Concrete example: take PXD1418’s row but set **`C2=-0.05`**, which the new check accepts. At reference temperature, raw **TOF 150000000** gives `disc/b²≈0.0740`, below the required 0.25; at **TOF 200000000** the discriminant is negative. The OpenMS converter accepts these uint32 arguments without a domain check.

The relevant paths are:

| Path | Actual argument range and consequence |
|---|---|
| OpenMS `convert`, patch lines 183–185 | Raw uint32 indices can exceed `1e8`; the double overload has no bound either. Neither checks `DigitizerNumSamples`. |
| `MzPeakExactMz::exact`, lines 154–155 | Reconstructed TOF has no `[0,N)` or `1e8` check. For example, transform parameters `c0=0,c1=1e-6` and archive m/z `22500` reconstruct TOF `150000000`. Temperature is checked upstream, TOF is not. |
| `toTof`, `diaspextract.cpp:906` | Input mass is actually capped at **42000**, by line 730, tighter than uint32 capacity. However, the inverse can return a TOF above `1e8` for an accepted calibration with a sufficiently fine timebase. |
| `best`, lines 1080–1082 | `cmz±3sd` is not bounded by acquisition metadata or `1e5`. Ordinary 15-ppm windows are safe on PXD029836. |
| Acquisition upper edge, line 4113 | `acq_hi≤1e5` when bounds loaded successfully, so its **mass argument** is covered. Its resulting TOF need not be ≤`1e8`. |
| Last-bin padding, line 4116 | `mzOf(last)+1e-5` can exceed `1e5`: PXD1418 at TOF `1e8` gives roughly **6.35e7 m/z** at the worst temperature corner. The forward TOF proof still places that mass on the rising branch; exceeding `1e5` here alone does not demonstrate a wrong result. The padding needs its own boundary reasoning. |
| Apex inversion, line 1263 | Normally inverts a mass reconstructed from an actual compacted peak. It does not independently introduce a large mass; inherited invalid axes or temperatures are the concern. |
| `recoverPoint`, `DnoiseMs1.h:453–455` | Accepts an integer inverse through `UINT32_MAX`; checks neither acquisition bounds nor branch identity. |
| OpenMS `inverse_convert`, patch line 188 | No mass/branch check, and no upper check before conversion to uint32. |

Two concrete inverse counterexamples clarify the last rows:

- With `C1=1000000`, `C2=-0.5`, `C0=C4=dC1=0`, `timebase=0.001`, `delay=11927`, the row passes. Both masses **144** and **3952144** map exactly to **TOF 1000**. `recoverPoint`’s TOF check accepts the descending-branch mass; its forward inverse is 144.
- With the actual PXD1418 row at reference temperature, `inverse_convert(mz=1e12)` computes approximately **7521487689**, outside uint32 range. The unchecked cast is undefined behavior. This is an unrealistic mass, and the shown patch does not establish that an ordinary tool execution calls this overload with such arguments.

For `best`, a real PXD row plus an absurd but unbounded setting `trace:mass_error_ppm=1e16`, `cmz=1700`, gives `hi_mz≈5.1e13`; its inverse is negative and `tofOf` returns zero, losing candidates. That is a theoretical configuration failure, not a normal-data failure.

For the supplied runs, genuine TOFs stop at 397656, masses are around 100–1700, and the nearest vertex remains above \(10^{12}\) m/z. **None of these branch failures is supported as occurring on those acquisitions under ordinary settings.**

**4. Temperature**

**MEDIUM — theoretical corrupt-temperature failure:** `patches/openms-brukertims-mz-calibration.patch:166–181` bypasses `frameReason`, while `src/diaspextract.cpp:4010–4018` can fall back to the OpenMS detector after the tool’s reader refuses the frame.

A direct witness is PXD1418’s otherwise-accepted calibration with **`C4=-500`**, frame **`T1=T1_ref+50000≈50025.618823611316`**, and **TOF 2000**. The temperature multiplier becomes exactly zero, so `b=inf`. `tofToMz` then computes `u=0` and returns the plausible finite mass **500**. Every finite TOF does likewise. This violates fail-closed behavior when denoising is disabled and the unchecked loader path runs. Such a temperature is not physically real.

The other paths are better:

- `setTofAxis` receives temperatures from `loadTdfCalibration` or the checked mzPeak reader. For accepted, ordinary finite negative-C2 rows, every resulting factor is positive and finite; `f > 0 ? f : bref` does not activate.
- `factor()`’s out-of-range fallback uses the reference temperature, which is inside the domain. It can conceal an unknown frame’s actual temperature, but does not mathematically leave the checked span.
- `factor(0)` returns the zero sentinel when the table exists. The tool has an explicit unmapped-frame fallback; this is not evidence that normal Bruker frames use an unchecked temperature.
- mzPeak `exact()` uses the checked temperature vector. Sparse missing IDs are filled with the reference temperature, so its range check proves addressability, not actual row membership—an existing integrity limitation.

For finite values, `frameReason`’s subtraction and the multiplier calculation are consistent with `cf_hi`: the same magnitude of temperature difference is bounded by 1000. I found no independent sign or floating-point corner mistake there.

The 1000-K span comfortably contains functioning hardware temperatures. It is meaningful as a numerical envelope, not an empirically validated temperature range. Rejecting `|dC1|≥1000` over that artificial span may reject a calibration safe over its actual frames; no evidence establishes whether such coefficients occur in plausible future files.

**5. Bit identity for C2 ≥ 0**

The changed numerical paths are fine by inspection:

- Moving the positive-timebase check does not change acceptance or refusal for C2 ≥ 0.
- `frameReason` immediately returns empty for those rows, including their unusual frame temperatures.
- The replacement bound constants have identical double values.
- `<cstdio>`, private member **functions**, and static constexpr members do not change instance layout or aggregate status.
- C++17 supports inline constexpr static members and the `if` initializer; the repository requests C++20.
- The extra empty `std::string` does not alter calibration arithmetic.

Therefore spectrum identity is well supported **by construction**, but not established experimentally. Whole-file byte identity is not expected: the software version changes from 1.3.0 to 1.3.1.

A mixed deployment is unsafe. An entirely old installed header causes compilation failures on the new members, which is useful. A new installed header/tool with an old `libOpenMS` can build yet retain the old negative-C2 refusal; differing inline definitions also invalidate assumptions about which implementation executes. A real **PXD1418 file, C2=-0.0010422663259118895**, is sufficient to expose that deployment mismatch.

The transaction script promotes/touches the shared header and builds the linked target, which is the right mechanism. Verify the rebuilt library and executable together; the unit test’s direct include alone cannot prove the installed library matches.

**6. Golden cases**

The generator is independent where it matters: JSON `"mz"` comes directly from `vendor()`, which invokes `tims_index_to_mz`. `model()` only produces diagnostics and ablations. I found no formula-generated expected masses.

The 210 added cases meaningfully cover four calibration vectors, six acquisitions, temperature extrema, and the last bin. They strongly support this compatibility fix. They do not establish arbitrary temperature, C4, coefficient, or caller-domain behavior.

Specific observations:

- Missing JSON `C4` is harmless for these files because all have zero C4. Preserve C4 or assert it is zero in a retained generator before reusing it.
- The `1e-4 ppm` tolerance is tight relative to the 19–80 ppm wrong variants. It is not vacuous.
- `g6` duplicating number formatting is reasonable: it checks an independently calculated threshold is present in the message.
- `c2_edge` uses a separately rearranged equation, but obtains `b` and domain constants from the header. It is not independent of those components. The vendor fixtures provide the stronger independent check.
- The global temperature-ablation threshold is acceptable here: every ordinary golden comparison would still detect dropping the negative-C2 temperature correction.
- The supplied mutation results substantiate several guards; stale `why` text in failed loader-test diagnostics does not invalidate their Boolean failures.

**LOW — theoretical test blind spot:** `tests/test_calibration_cpp.cpp:220` accumulates round-trip error using `std::fmax`, which ignores a NaN operand. A mutation returning NaN from `mzToTof` only for **m/z >100000** can evade this sweep’s round-trip assertion. For example, the checked PXD corner **TOF 100000000 → m/z 63491141.09524 → NaN** would not increase `worst_rt`. Assert each inverse result is finite before accumulating the maximum.

**7. Other assumptions and documentation**

I found no additional arithmetic branch that fundamentally requires C2 ≥ 0 beyond the callers’ monotonicity assumptions already discussed.

Several comments overstate the guarantees:

- `src/TdfMzCalibration.h:63–65` treats “every stored TOF index is below `DigitizerNumSamples`” as enforced; it is an acquisition-format assumption.
- Lines 29–37 claim coverage over everything the tool asks and imply bad conversions become counted NaNs. The unchecked-temperature example above instead returns finite 500.
- `tests/test_calibration.py:26` groups “taking the other root” with the **38–80 ppm** sign-flip error. The other root gives enormously larger masses; those numbers describe sign flipping only.
- Header line 24’s signed `−11..−40 ppm` description does not apply unchanged to negative C2: dropping negative C2 underestimates the quadratic correction in the opposite direction from dropping positive C2.

The provenance name `tdf_table_modeltype1` remains appropriate for either sign; the law has not changed. Its “exact” claim depends on closing the enforcement gaps.

**8. CHANGELOG accuracy**

**MEDIUM — real release-evidence issue:** `CHANGELOG.md:13–15` states that the four pins reproduce before the gate has run. The concrete cases are dataset D and run 009, each with **`dnoise:ms1=true/false`**, expecting `e43672a0`, `3aafd0b5`, `8c1b047f`, and `bff54a1f`. There is no demonstrated digest failure, but there is also no evidence for the present-tense success claim.

The numerical SDK claims otherwise largely agree with the evidence:

- 23 runs, four vectors, six checked runs, 30 selected frames, 210 added/270 total JSON cases: correct.
- 2017 submitted probe positions per selected frame: correct; the list includes a repeated last-bin position.
- Worst SDK discrepancy `7.0e-6 ppm`, ablations 19–40/38–80 ppm, margins ≥0.984 and ≥0.99992: supported.
- Worst-span root disappearance above `6.4e9`: supported; run 1431 gives approximately `6.4699e9`.
- `0.0595301` is the run-1418 edge. “57 times theirs” applies to that vector; across the four vectors the ratio is approximately **48–102**. It does not prove future plausible calibrations cannot be refused.
- “1e-6 inside/outside” is a **relative** perturbation: approximately `5.95e-8` in C2.
- The reported domain round trip below `5e-8` matches the supplied measured `3e-8`; the assertion permits `1e-6`.
- The dnoise `2e-10` result and loader boundary/temperature cases match the supplied evidence.
- The fallback description applies to the `.d` detector path; mzPeak exact calibration throws when its reader rejects.
- “Over everything the tool can ask” is false for the paths in answer 3.
- “Beyond the peak” should explicitly mean **flight time beyond the maximum**, not mass beyond the vertex. Descending-branch masses still produce real earlier flight times.

**9. Before shipping, ranked**

1. **Enforce the negative-C2 temperature/domain contract at the actual conversion boundaries**, especially the OpenMS loader. Detector fallback must not bypass a calibration refusal. Validate decoded/reconstructed TOFs; handle inverse branch limits and uint32 range explicitly.
2. **Rebuild and verify the executable plus libOpenMS, then run all four digest pins.** Keep the changelog claim pending until that succeeds.
3. **Harden negative-C2 acceptance against non-finite values and unstable threshold arithmetic.** Preserve the requested C2 ≥ 0 behavior. Address invalid `mz+C4` inputs explicitly.
4. **Add focused regression cases for the gaps**, including the unchecked loader frame, out-of-domain raw TOF, negative `dC1`, inverse branch ambiguity, and NaN round-trip masking.
5. **Correct the documentation and retain the SDK generator with explicit C4 provenance.**

I would keep the conversion root unchanged. The work needed is chiefly enforcing its preconditions and completing the release evidence.
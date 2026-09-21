# Review brief: the twin fold (DIAspeXtract 1.4.0)

Review only -- do not modify, create or delete any file. HEAD is 2cfc8e1 on main; the change under review is
`git show 2cfc8e1` (src/diaspextract.cpp, test/test_diaspextract.py, README.md, CHANGELOG.md, CMakeLists.txt).
If something is fine, say so in one line rather than padding.

## What it does

`mergeTwins_` (src/diaspextract.cpp, after `canonicalSort_`) folds pseudo-MS/MS spectra that claim one precursor
twice. It runs once per RT tile on the tile's canonically sorted block, just before the block is written
(`[tile]` write path; search `MERGE(twins)`). Relation: same RT (bit-equal), same charge > 0, precursor m/z within
20 ppm of the EARLIER member (the probe's own tolerance), |1/K0 difference| <= im_tol; clusters = connected
components (union-find). Survivor = most `spx_n_isotopes`, then most peaks, then the earliest position. Its peaks
become the union of all members' peaks sorted by (m/z, intensity) and fused greedily: a peak joins the running
group while its m/z minus the group's intensity-weighted mean m/z is <= mean * 10e-6; a group emits
(weighted mean m/z, max intensity). All non-survivor members are deleted; survivors keep their positions.
Option `assembly:twin_im_tolerance` (default 0.005, any negative = off). Measured offline with an equivalent
Python tool (bench/twin_merge.py) on a 2-hour run: -23.8% spectra, -0.2% peptides on both search engines.

## Invariants this code must keep (attack these)

1. **Determinism.** The whole output must be digest-identical for any thread count and any grouping of RT
   cells into tiles (`tile:cells_per_tile`). The argument is: every precursor RT is exactly an MS1 frame time,
   so same RT => same owning RT cell => same tile under every grouping. Is that argument sound given how
   precursor ownership across tiles is decided (search `an earlier tile owns it` and `tile.lo - pc.rt`)? Can two
   spectra with bit-equal RT ever land in different tiles? Is anything in mergeTwins_ order- or thread-dependent
   (the omp loop, union-find root choice, the survivor tie-break, float summation order)?
2. **Off is unchanged.** With a negative tolerance, output must be byte-identical to 1.3.x. Check every new line
   on that path (header stamp `spx:twin_merge`, counters, logs) -- the header is part of the file.
3. **Survivor fields.** The survivor keeps its own precursor m/z, charge, 1/K0, isolation-window offsets,
   RT and userParams; only its peaks change. `MSSpectrum::clear(false)` is used to drop the peaks -- verify in
   OpenMS that clear(false) keeps precursors, RT and meta values and clears only the peak container.
4. **Equivalence with bench/twin_merge.py** (the priced transformation), except that the Python tool linked
   pairs up to 1.5 s apart in RT and this links only bit-equal RT (on the measured file every linked pair had
   identical RT). Differences in the probe tolerance, the inclusive/exclusive bounds, the survivor key, or the
   fusion arithmetic would silently change what was measured -- compare line by line.
5. **Scale.** A 2-hour file emits ~1.05 M spectra with up to 500 peaks each; ~160 k clusters carry ~137 M raw
   peaks. Memory and time of the fold per tile? Any quadratic path (a frame with many same-charge spectra in a
   narrow m/z range)?

## Numbered questions

1. Any input for which the output depends on thread count or tile grouping? Give the input.
2. Any input for which mergeTwins_ crashes, deletes a survivor, keeps a non-survivor, or links spectra that
   should not be linked (e.g. across charges, across RTs, charge 0)?
3. Is the fused peak list always sorted by m/z? Is an empty or zero-intensity peak list handled? Can a fused
   spectrum lose all peaks?
4. The e2e check 12b: does it test what it claims? Can it pass vacuously (fixture with zero twins)?
5. Does the selftest cover each side of each clause of the relation, and is any expectation wrong?
6. README/CHANGELOG/help text: any claim that is not what the code does?

For every finding: file:line, a concrete failing input, severity, and "would this bite on real data or is it
theoretical?"

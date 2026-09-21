# Review of the twin fold (1.4.0, commit 2cfc8e1) — findings and dispositions

**Incomplete three-CLI review.** Codex could not run: `ERROR: You've hit your usage limit ... try again at Sep 27th,
2026` on the smoke test (codex-cli 0.155.1). Reviewed by **Kimi** (kimi-code 2.0.2, `kimi.md`), **Vibe** (2.25.5,
`vibe.md`; the dispatcher's `vibe -p` line lacks `--auto-approve --max-turns 200` and returned nothing, so Vibe was run
by hand with those flags in a throwaway worktree, which it left clean) and an internal six-lens review with two
verifiers per finding. Brief: `brief.md`. The working tree was frozen at 2cfc8e1 for the whole review.

**Verdict, all three: no defect in the fold.** Independently confirmed: tile-grouping and thread invariance (tile
ownership is a pure function of the precursor RT the spectrum carries, `src:4716-4717`, `:3132`; the omp loop touches
disjoint clusters), `MSSpectrum::clear(false)` keeps RT, precursors and meta values (read in OpenMS bd4b895 and in the
local OpenMS source), line-by-line equivalence with `bench/twin_merge.py` apart from the documented RT clause, no
quadratic path on real data, no crash on empty or degenerate input.

| # | found by | finding | disposition |
|---|---|---|---|
| 1 | Vibe (as blocker), Kimi, internal | "−1 = the output before 1.4.0" is false byte-for-byte: `spx:twin_merge` is written in both modes | Wording fixed to "the spectra of 1.3". The header was never byte-identical (TOPPBase writes version, parameters and a completion time); the gates pin the spectrumList digest. The explicit `off` stamp stays as provenance. |
| 2 | all three | e2e 12b passes vacuously: the default fixture has no same-charge pair, so 0 == 0 | Rewritten: inert (0 folded, digest unchanged) on the default fixture, and must fire (folded > 0, count reconciles) on `synth(groups=(1, 9))`, where each precursor is assembled in two window groups. |
| 3 | internal | no thread or tiling check runs a real cluster through the fold | Added e2e 15b: the groups fixture at 1 vs 4 threads and one tile vs one cell per tile, the fold firing in each, digests equal. |
| 4 | internal, Kimi | selftest does not pin the 10-ppm fusion tolerance or its running-mean anchor | Added 10.5 ppm (two peaks), 14.25 ppm from the equal-weight running mean (two), and a heavy middle peak pulling the mean to 9.6 ppm of the third (one — a first-peak anchor splits). |
| 5 | internal | nothing pins "singletons untouched" | Added a lone spectrum with peaks 7.5 ppm apart that must keep both, bit for bit. |
| 6 | internal | survivor-key order unpinned (peaks-first passes) | Added 3 isotopes / 2 peaks against 2 isotopes / 3 peaks. |
| 7 | internal | any TWIN_PPM in [15, 25) passes | Added 19.5 ppm (folds) and 20.5 ppm (does not). |
| 8 | Kimi | inclusive bounds, the backward scan and survivor-field retention untested | Added an exact |d1/K0| == tolerance pair (folds), the higher m/z first in the input (folds), and a survivor that must keep its RT, precursor, 1/K0, isolation offsets and userParams. The ppm boundary itself is not asserted (it only differs within ~2e-7 m/z). |
| 9 | internal | README/help say "entrapment unchanged" at 0.005, but entrapment was only scored at 0.01 | Claim removed until measured; the 1418 oracle and both K562 plans score entrapment at the shipped 0.005. |
| 10 | internal | README still described 1.3 ("merging or deduplicating ... loses peptides") and the max_fragments cap as absolute | README step 4 and the emission paragraph name the fold; the cap row and help say it applies before the fold. |
| 11 | internal | CHANGELOG's 45.9 % used the wider relation, and its random cut matched the 0.01 drop arm | Relation stated; costs given like for like per 1,000 spectra removed (0.4 fold, 2.7 drop, 9.5 random). |
| 12 | internal (B1) | the claim that every priced pair shared its frame lived only in the brief | Measured and recorded in docs/SAME-POSITION-DUPLICATION-2026-09-20.md §1 with `bench/twin_rt_exact.py` (563,634 / 354,462 pairs, all identical RT). The 1418 oracle checks the in-tool fold against the priced offline fold spectrum by spectrum. |
| 13 | Kimi (nit) | was the priced run at `--im=0.005`? | Yes: the `merge_tight` arm (docs §4). |

Not acted on: Vibe's "downstream pipelines that parse headers will see a new field" — a new userParam is additive and
every 1.x release has added `spx:` stamps; the dataset D gate's stamp count moves 16 → 17 in the 1.4.0 driver.

# Pre-tag documentation review, 1.4.0 (2026-09-23), at 50a3b41

Reviewers: an internal three-lens workflow (defaults, CHANGELOG, public read; every finding re-verified: 23 of 23
confirmed), **Kimi** (`kimi.md`) and **Vibe** (`vibe.md`, run by hand with `--auto-approve --max-turns 200` in a worktree
it left clean). **Codex unavailable** (usage limit until 2026-09-27): an incomplete three-CLI review.

Fixed in the release commit:
- `trace:mz_estimator` help said integer-detector fragment traces keep their centroid; they report the apex bin's
  calibrated m/z (src:1168, :3108, :3302-3306), as the README says. Predates 1.4.0. (workflow, Kimi)
- README "sixteen `spx:` userParams" → seventeen, `spx:twin_merge` listed. (workflow, Kimi)
- CHANGELOG: `dedup_precursors` was removed in 1.2.0, not 1.3.0 (v1.2.0 Removed list; commit 9a6c2d4); and it was a
  precursor-level drop of the same kind, not "the drop form of this". (workflow, Kimi)
- CHANGELOG: only e2e 12b runs the selftest; 15b is the invariance check. (workflow, Kimi)
- One form for the entrapment result in README, help, CHANGELOG and the study doc. (workflow, Kimi)
- `assembly:corr_power`: README "+4–8 %" and help "+5–8% on three files" MSFragger; the record has +4.4 % on the one
  file measured with MSFragger (BASELINE 'CONTENT CANDIDATE 1 FALSIFIED'). Predates 1.4.0. (Kimi)
- README: `-perf:ms1_trace_bands` and `-perf:trace_bands` carry the **changes output** marker; the twin row says
  "the cluster's fragments, peaks within 10 ppm fused", names PXD029836, and says 0 still folds identical-1/K0 twins
  (also in the help). `-out` / `-out_type` help: mzPeak is the default only in a build with mzPeak support.
- CHANGELOG: the overlap is 1.00 m/z on that run; the called charge (no charge, no fold); per-1,000 costs are Sage's
  and the random cut matches size and charge mix; the log and `MERGE(twins)` phase are named.
- Study doc (exported): a reader-terms question instead of the chat prompt; line numbers declared as v1.3.2; "arm"
  defined; the search configuration named (`bench/sage_closed.json`, identical to the harness's config apart from a
  comment and the FASTA path) and the counting rule stated; no `tools/`, harness, roadmap or dev-history path; the
  98.4 % stated as of the reference implementation's 51,347 Sage peptides; section 8 marked superseded.

Not acted on, with reason:
- Vibe: "`bench/` is in .export-private (line 46)" — line 46 is `harness/`; `bench/` is exported (22 scripts public
  today) and every new tool was checked against the list.
- Vibe: README option rows should carry **changes output** for assembly options — the README scopes that marker to
  the memory and concurrency table; assembly options shape the spectra by definition (README:153-155).
- Vibe: "dataset D", "TNBC 009" as private labels — "dataset D" is the scrubbed public label; run 009 is PXD047793.
- Vibe: the CHANGELOG fold description omits the fusion and the cap — it states both.
- Kimi: `-perf:trace_bands` 0 = auto missing from the README row — the auto setting is refused at the default
  `tile:rt_sec`; naming it in the row would invite an error.

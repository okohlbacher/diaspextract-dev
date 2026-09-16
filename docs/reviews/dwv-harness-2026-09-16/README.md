# Adversarial review of the diaWeaver harness change (corpus.py extended plans), 2026-09-16/17

**Status: COMPLETE minus codex.** Codex is out of credit until 2026-09-17 17:41, so this review ran with kimi and
vibe only (both on one self-contained brief) plus the synthesising session's own review and node tests. Every
finding below was checked against the tree, and where it could be, on the node with real OpenMS-written files,
before it was accepted. Disagreements between the reviewers are recorded, not merged. If codex returns before the
dataset D run, run it on the fix commit and append its findings here.

| what | value |
|---|---|
| reviewed | `harness/corpus.py` (+ CORPUS.md, README.md), `0a1bb0d..a716b5c` (commits ba91ac0, a716b5c), corpus.py sha256 `bc6a3a8f` |
| brief | `brief.md`, self-contained (context, invariants, 12 questions, the full diff, the unchanged helpers it calls, bench/entrapment.py, bench/semantic_digest.py); no specimen paths |
| kimi-code 0.42.0 | `kimi -p <brief> --output-format text`, throwaway worktree at a716b5c, 23:25-23:36, worktree clean, 18,197 B (`kimi.md`; reasoning stream `kimi.err`) |
| vibe 2.25.3 | `vibe -p <brief> --output text --trust --auto-approve --workdir <worktree>`, 23:25-23:30, worktree clean, 9,035 B (`vibe.md`; stderr `vibe.err`, empty) |
| codex | NOT RUN (credit) |
| CLI versions | check-versions.sh: kimi 0.42.0 -> 0.43.1 and vibe 2.25.3 -> 2.25.4 available; not upgraded |
| node tests | `scripts/` (run on data, private 0700 scratch dir, deleted afterwards; public HeLa PXD017703 run 2731 only, no patient data): `mkfix.py` builds diaWeaver-shaped fixtures from the first 240 spectra of its diaTracer mzML with the fork's own FileConverter; `gtest.py` drives corpus.py's own functions (G-V03, G-V16, G-V17, G-V18) against those files, the published `diaweaver-7ed1169` arm and wrapper tools; `dwv_smoke.sh` is a 45-min functional smoke of the real diaWeaver on a tdf-only copy of the same public `.d` (not a benchmark); `realtest.py` puts 2,000 real diaWeaver spectra from that smoke through diaWeaver's own final step (reload + numpress store) and the harness re-encode |
| fix commit | see the commit that adds this file; corpus.py sha256 `3c373449` |

## Findings, most severe first

Source: K = kimi, V = vibe, O = own (review or node test). Verdict = what the synthesising session established.

| # | sev | source | where | finding | verdict | disposition |
|---|---|---|---|---|---|---|
| 1 | HIGH | O (node test) | `mzml_scan` content digest | OpenMS writes `dataProcessingRef="dp_sp_0"` on the FIRST spectrum of a file only, and which spectrum is first after the re-encode depends on diaWeaver's unstable RT order. The digest kept that attribute, so two re-encoded files with the same spectra in another order got different content digests: G-V18 would never flag a real no-op arm (dwv_pickim), which is the check's whole purpose. The selftest fake wrote no such attribute | CONFIRMED on real FileFilter output: `node/gt1b.out` (a716b5c) fails the same-content case, `node/gt3.out` passes; seen on the real diaWeaver intermediate too | FIXED: the attribute is stripped like id/index/spectrumRef; fake FileFilter now writes it; selftest orders the two no-op cells differently |
| 2 | HIGH (introduced and fixed in this pass, never committed) | O (preflight) | selftest fakes | The first fix pasted `numpress_linear`'s source into the fakes with `inspect.getsource` at import; nodes run corpus.py from stdin (`python3 -`), where that raises, so every remote command (preflight, status, launch) crashed | CONFIRMED (preflight traceback) | FIXED: pasted at selftest time only; new COMPAT case imports the module from stdin and serves `node-status`, as `remote()` does |
| 3 | MEDIUM | K5, V4, O | `run_group` cell loop | Only `Abort` was caught per cell: any other exception (a `ValueError`/`zlib.error` in `mzml_scan`, an `OSError`) failed the whole group, discarded the finished reference arms and skipped the next cell, contrary to "a failed cell does not stop the next one" | CONFIRMED (code; selftest with an injected crash) | FIXED: a non-guard exception fails that cell as `CRASH`; queue-level aborts still propagate |
| 4 | MEDIUM | K5, O | `sage_by_charge`, `msf_by_charge`, `entrap_strata`, `add_split` | A charge that is not an integer raised `ValueError`: in `add_split` it escaped phase 2, in `run_entrap` it was recorded and then re-raised (as `run_search` does for crashes), so it ended the queue | CONFIRMED (the fix pass's own selftest reproduced the queue abort) | FIXED: `tsv_charge` refuses such a TSV as G-V19; `add_split` records any other exception as `CRASH` for that search only |
| 5 | MEDIUM | K7.1, V3, O | `cells_identity`, `build_identity`, `cell_env`, `cell_provenance` | The cell identity pinned binary, FileFilter, lib/** and ceph libraries, but not `share/OpenMS` (OPENMS_DATA_PATH: the 258 data files the tool reads at run time) nor env.sh; the PROVENANCE line `share_OpenMS_tree_sha256=` was never compared with anything | CONFIRMED | FIXED: `data_tree_sha256` reproduces the publish step's `find\|sort -z\|sha256sum` (verified on the real arm: `c14bc64b`); G-V03 requires OPENMS_DATA_PATH = the arm's share/OpenMS and the provenance hash = the tree in use; data tree and env.sh sha256 are in the build identity (G-V04/G-V11/G-V13) |
| 6 | MEDIUM | O | `reencode`, `mzml_scan`, CORPUS.md | The raw diaWeaver file's peak order (finding IO-W8, one of the findings stage 1 must test) was not measured, and the raw file is deleted after the re-encode; the harness gave "the stdlib cannot decode numpress" as the reason, which is wrong (the build slice had a stdlib decoder) | CONFIRMED | FIXED: `numpress_linear` (stdlib port of MSNumpress decodeLinear), bit-identical to the fork's own decode on 240 real spectra and a FileConverter vector, about 1 µs per peak (0.7 on the laptop); the raw scan decodes and records unsorted peak lists (table column) |
| 7 | MEDIUM | K3.1 | `reencode` (G-V17) | Peak data was never compared across the re-encode: only counts and precursor values. A rewrite that moved or changed peaks passed | CONFIRMED (code) | FIXED: `peak_digest` (per-spectrum precursor values + sorted m/z values, order-independent) must be equal before and after; equal on the 240-spectrum fixture and on 2,000 real diaWeaver spectra (`node/rt2.out`) |
| 8 | MEDIUM | K10.1 | `cell_env` / `run_cell` | Cells ran with TMPDIR = jnatmp, which is mode 0755 on data: anything a tool spills there is patient-derived and world-readable | CONFIRMED (mode on data). The fork's changed code has no temp-file use (grep), so this is defence in depth | FIXED: each cell gets `<cell dir>/tmp` (0700) as TMPDIR for the tool and the re-encode, removed afterwards, `tmp_files` recorded. The pair arms keep jnatmp (unchanged code) |
| 9 | MEDIUM | K4.1 | `run_capped` (G-V16) | The memory floor killed the cell on ONE node-wide sample under 5%: a neighbour's dip on a shared node would kill a healthy 12-h cell and the group would re-run whole | DESIGN, accepted as a defect for this run | FIXED: the floor must hold for `MEM_FLOOR_SAMPLES` = 3 consecutive 10-s samples |
| 10 | LOW | K9.1, V10 | `render_cells_table` | An ok Sage/MSFragger record without its charge split (runner stopped between search and split) made the per-arm summary raise KeyError | CONFIRMED (code path) | FIXED: such a record renders as `pending` (it re-runs on the next launch) |
| 11 | LOW | K3.2 | `reencode` | A spectrum without an m/z array passed G-V17 | CONFIRMED | FIXED: `missing_mz` refuses it |
| 12 | LOW | O | `mzml_scan` | A precursor value that is not a number, or an m/z array that does not decode (bad base64, zlib, length), raised inside the scan | CONFIRMED | FIXED: counted (`bad_values`, `undecoded`) and refused by G-V17, never raised; a raw m/z array the harness cannot decode (numpress pic/slof) refuses the cell |
| 13 | LOW | K11 | `render_cells_table` | `nan` printed as a ratio when diaTracer has no z>=2 peptides | CONFIRMED | FIXED: `-` |
| 14 | LOW | V2 | `stage_tdf` | Copied tdf files had the umask mode (0644). Not reachable: the directories are 0700 | theoretical | hardened: 0600 |
| 15 | NIT | K6 | G-V18 | The no-op flag is one-sided: "differs" also results from run-to-run variation | CONFIRMED | documented (docstring, table text, CORPUS.md) |
| 16 | INFO | O (smoke) | diaWeaver itself | Functional smoke on the public HeLa `.d` (11.5 min, tdf-only copy, 32 threads): the tool accepts the two-file `.d`, processes all 24 windows at once ("no nested parallelism"), and had finished 5 of 24 windows after 45 min (bounded; killed with its process group, nothing left behind). Its wall time is set by the densest window; threads beyond the window count do not help. Dataset D is 31 min | observation, not a benchmark | reported to the parent: the 12-h cap may be reached on D; a cell that always hits its cap re-runs the whole group on every relaunch (documented in CORPUS.md) |
| 17 | INFO | O (real spectra) | diaWeaver output | On 101,362 real intermediate spectra: 93.6% of peak lists unsorted, 1/K0 = 0 in all, charges 2/3/4 only, 30 to 500 peaks; the intermediate declares `count="0"`; trace/window ids are 64-bit INTEGER arrays (zlib in the final file, not numpress); diaWeaver's final reload sorts the peaks. Sage 0.14.6/0.14.7 skip such arrays (parser resets the array kind per `<binary>`; MS:1000786 maps to none) | observation (public file, partial run) | documented; MSFragger's handling of the extra arrays is not verified (its Scans check stays) |
| 18 | INFO | O | tools | `/ceph/.../tools/sage/sage --version` prints 0.14.6 while corpus.py comments say 0.14.7. Pinned by sha256 (G-V12) either way | pre-existing | not changed; noted |
| 19 | INFO | O | staging | That diaTracer and DIAspeXtract read a tdf-only `.d` exactly as a full one is taken from their readers, not tested | open | documented: compare D's diaTracer count with corpus v3 (700,434) and the DIAspeXtract digest with its pin before using the pair |

### Refuted or kept as designed

| source | claim | verdict |
|---|---|---|
| V1 (BLOCKER) | `ready_arms` inverts the file check, so plain plans adopt deleted mzMLs | REFUTED: the check runs only when some search is still pending, exactly as the old `pair_done`; kimi reached the same conclusion; the pair hashes are unchanged and plain dry-runs are byte-identical |
| V5 (BLOCKER) | `msf_by_charge` breaks ties differently from `msf_peptides` | REFUTED: `sorted(values, reverse=True)` on `(hs, dec)` tuples is the same key; kimi agrees; `add_split` enforces equal counts |
| V6/V7 (BLOCKER) | zlib (MS:1000574) arrays are not decoded | REFUTED: they are (and exercised on real files) |
| V9 | entrapment searches are never rescored | DESIGN: they carry the score hash; a rule change re-runs them (fail-safe) |
| K1.1 | `entrapment: false` now loads on a plain plan | DESIGN: an explicit boolean; the plan runs plain |
| K2.1 | first occurrence of MS:1002815 | kept: the re-encode writes the same value at scan and selectedIon level (seen on real output); both scans read it the same way |
| K2.2 | self-closing `<spectrum/>`, missing defaultArrayLength | theoretical; now refused by `missing_mz` / `length_mismatch` on the searched file |
| K8 | a peptide with a qualifying target and decoy row | not reachable (Sage labels per peptide); the split's equality check fails closed |
| K12 | the busy gate proceeds after 20 min beside an orphan | pre-existing, flagged; busy detection verified live (the smoke's diaWeaver was reported busy by `preflight --plan dwv_stage1`) |
| V11-V15 | nits | no change |

Where kimi and vibe disagreed (items V1, V5, V6), vibe was wrong on all three; its model is the medium tier
(memory: adversarial-review-clis). Its two correct points (share/OpenMS, the crash in a cell) were also kimi's.

## Verification of the fix commit

- `python3 harness/corpus.py selftest`: **258/258** (a716b5c: 232). New cases: stdin import; data tree and env.sh
  identity (G-V03/G-V04/G-V11); private TMPDIR; raw peak order measured and m/z equal across the re-encode; the
  dataProcessingRef no-op case; a crash in one cell; a memory blip that must not kill; four new re-encode faults
  (m/z array lost, one m/z moved, a non-numeric charge, an undecodable raw array); a non-integer Sage charge; a crash
  in the split; a table with split-less searches; the numpress decoder against a real FileConverter vector, the
  fake encoder, corrupt input, and a 30-byte m/z array.
- Mutation proof (`scripts/mutate.py`): each fix reverted alone in a scratch copy makes that copy's selftest fail,
  **22/22** on corpus.py `3c373449` (`node/mutate_3c373449.txt`; the same 22 on `8804501d`, before the dry-run wording
  change, in `node/mutate_8804501d.txt`).
- Node tests on data: `gtest.py` **38/38** with the fixed corpus.py (`node/gt3.out`), 35/36 with a716b5c
  (`node/gt1b.out`, the G-V18 case); `realtest.py` on 2,000 real diaWeaver spectra: re-encode PASS, peak and
  precursor digests equal, trace ids still attached in 2,000/2,000 (`node/rt2.out`).
- Plain plans: pair/search/score hashes still `3215b73e` / `064af71b` / `4fe0a1ce`; `dry-run --local` of `corpus_v3`
  (spock, data, ibminode05) and `corpus_v3_selftest_v130` byte-identical to the 1.3.0 harness; `preflight --plan
  corpus_v3_selftest_v130` PREFLIGHT_OK on ibminode05.
- `preflight --plan dwv_stage1`: PREFLIGHT_OK on data (load 1.4, lock free, nothing running), both cells pass the new
  data-tree check against the real PROVENANCE; while the smoke ran, the same preflight reported data busy
  (`diaWeave[r] -in`), as it must.

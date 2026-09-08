# Benchmarks

## `sage_closed.json` — the closed metric (what every README number came from)

Byte-for-byte the configuration behind every `peptide_q` figure in the repo. It previously
existed **only** at `/scratch/kohlbach/bench/sage_deiso.json`, untracked — a reproducibility
hole in the single file that *defines* the project's metric.

What it structurally cannot see: `precursor_tol` is ±25 ppm. A charge error fabricates
ΔM = (z′−z)(m/z − 1.00728) — hundreds of Da — so those PSMs are never reported. **Closed search
cannot score the failure mode this tool exists to avoid.**

## `open_bench.py` — entrapment-controlled open search

Built because the closed benchmark rewards the opposite of the goal: we emit 4.6 PSMs/peptide
against the reference implementation's 1.46, so redundancy is free score under `peptide_q`. That one fact predicts
in advance every result observed — each redundancy-reducing lever losing, and `ms1split` winning
while simultaneously raising co-isolation 52% and dropping charge below baseline. *Six
falsifications sharing one biased instrument are one falsification.*

Three measurements, ordered by how much they assume:

1. **Delta-mass geometry** — no ground truth, no decoy, no entrapment. Charge errors are
   *linear in m/z* and form **rays** through (1.00728, 0) with integer slopes; real
   modifications are constant shifts and form **horizontal bands**. Separable by construction.
   Validated on synthetic data: 300/300 slope −2 rays recovered, 125× over the chance floor,
   pure-noise control at 0.0000 vs a 0.0123 floor. **Reports its own chance floor** — the
   omission that got the MS1 funnel retracted.
2. **Entrapment FDR** — 16,343 *A. thaliana* proteins vs 20,416 human (ratio 0.800). Independent
   of the decoy model, which degrades as open search grows the candidate space ~10³×
   (Kong 2017; Chick 2015; Wen et al., *Nat Methods* 2025).
3. **Modified peptides at ≤1% entrapment FDR** — the primary metric.

### Two windows, deliberately

`sage_open.json` is −150/+500 Da (primary). `sage_open_wide.json` is −3000/+1000 Da and exists
**only** as the positive control: a 4→2 error at m/z 500–1400 lands at −1000 to −2800 Da and is
**not reported at all** inside ±500. A benchmark run only at ±500 would be blind to the very
failure it was built to detect.

### Pre-registered falsification — written before the first run

Closed ratio `split_count/base` on dataset B = 8,411/5,817 = **1.446**.

| modified-peptide ratio | conclusion |
|---|---|
| **≥ 1.446** | "closed benchmark rewards shotgunning" is **falsified**; defaults vindicated for both purposes; the six falsified levers stand; stop reducing redundancy |
| **1.0 – 1.446** | real, but overstated by the closed metric |
| **< 1.0** | shipped defaults are **actively harmful** for the stated purpose |

Replicate spread is 0.17% (8,411 / 8,408 / 8,406 / 8,397), so differences under ~0.2% are noise.

**Positive control, non-negotiable.** The `envelope` arm has 10,199 known 4→2 confusions. They
must appear as slope −2 ray mass in the wide window and be markedly weaker in `count`. **If the
control does not fire, no other number from this script may be quoted.**

### Run

```bash
python3 open_bench.py fasta --target human.fasta --foreign arabidopsis.fasta --out human_entrap.fasta
./run_open.sh
python3 open_bench.py analyse RESULTS.tsv --label arm --ratio 0.800
```

All three arms are extracted on **one node with one binary** — comparing across nodes or builds
is the error class this benchmark exists to eliminate.


## `joint_bench.py` — the success metric across the three datasets

**3 samples × {the reference implementation, SpeXtractor} × {Sage, MSFragger}**, reporting the two numbers the
project is scored on:

* **PSMs** at ≤1% PSM-level FDR
* **unique peptides** at ≤1% peptide-level FDR

### The design decision that matters

Both engines are scored by **one identical target-decoy procedure** implemented in
`joint_bench.py`, *not* by each engine's own FDR machinery (Sage's internal linear discriminant;
MSFragger via PeptideProphet/Philosopher or Percolator). Those pipelines differ in rescoring, in
PSM→peptide aggregation, and in decoy handling — comparing their outputs would confound *"which
engine identifies more"* with *"whose FDR is more permissive"*.

For the same reason both engines search **one pre-built target+decoy FASTA** with a shared
`rev_` prefix, and Sage's internal decoy generation is turned **off**, so the two see
byte-identical search spaces.

Peptide-level FDR is "picked": best-scoring PSM per distinct sequence, then target-decoy over
that reduced list. That axis is the point — SpeXtractor emits ~4.6 PSMs/peptide against
the reference implementation's 1.46, so PSM counts reward redundancy and peptide counts do not. **Both are
reported so the gap is visible rather than hidden.**

Validated before use: null control (targets and decoys from one distribution) collapses to 1
accepted; peptide-level correctly reduces 5 PSMs over 2 sequences to 2.

### Known asymmetry — read before quoting an engine comparison

**No rescoring is applied.** Sage's reported score is already discriminant-rescored; MSFragger's
hyperscore is not, which favours Sage on absolute counts. Adding Percolator to MSFragger alone
would reintroduce the confound this design removes; adding it to *both* is the correct fix and
is not done here.

**The tool comparison is unaffected** — the reference implementation vs SpeXtractor is made *within* an engine, and
that is the comparison this harness exists for. The engine axis is a secondary readout.

### Run

```bash
python3 joint_bench.py decoydb --target human.fasta --out human_decoy.fasta
./run_joint.sh
python3 joint_bench.py collate joint_results.json
```

## Cluster launch discipline (2026-09-07)

Launching a long job as `ssh HOST 'cd DIR && setsid CMD > log 2>&1 </dev/null & ...'` blocks ssh for
the **entire job**. The `&` binds to the whole AND-list, so bash forks a subshell to run it; the
redirections apply only to the inner simple command, so the subshell keeps sshd's stdout/stderr pipes
and waits, and sshd cannot close a non-PTY channel until the last writer of those pipes closes them.
Measured on spock with a 6 s payload: **7.0-7.3 s held vs 0.8-1.0 s released.**

The invariant is **not** "avoid `cd &&`" -- `true && setsid ... &` also holds, and so do `( ... ) &`
and `{ ...; } &`. It is: *no process that outlives the foreground command may still hold the
session's stdout/stderr*, and bash only avoids leaving one when the backgrounded unit reduces to a
single redirected simple command it can `exec` in place. So `[ -e "$D" ] && setsid ... &` is unsafe
too. The obvious alternatives are worse: `cd DIR; setsid ... &` runs the job in quota-limited `$HOME`
if the `cd` fails, and `{ cd DIR && setsid ...; } &` buries a failed `cd` in a remote log.

Use `bench/launch.sh` (shipped to the cluster by `sync_cluster.sh`):

```
ssh -n HOST 'bash /ceph/ibmi/abi/oliver/spextract/tools/launch.sh TAG WORKDIR CMD [ARGS...]'
```

One ssh per Bash call; never `2>/dev/null` on a launch. Confirmation is a pid the payload stamps
itself -- `pgrep -f ... | wc -l` reported 3 for one job and 1 for a job that had already exited.

Separately: `exit 255` on a long-lived ssh was the laptop clamshell-sleeping, not the job failing.
Three incidents separate perfectly on "was the connection open across a lid-close"; a 24-second sleep
sufficed, while a 28-minute connection with no sleep exited 0. macOS reports it only after
`net.inet.tcp.keepidle` (2 h) unless `ServerAliveInterval` is set, which is now 15 s for the cluster
hosts. **Not** ControlMaster: one shared connection means one lid-close kills every concurrent
session instead of one.

`baseline_run.sh` now refuses a pre-existing arm directory, as `gate_bands.sh`/`gateA.sh` already
did -- a launch that merely *looked* failed was relaunched by hand once, and nothing would have
flagged an overwrite. `gateA.sh` also had a stale `bin/spextract` path, broken since the rename to
`spextractor`.

An adversarial review of that first pass found four defects in it, all reproduced and since fixed:

- **`verify_publish.sh`'s guard was on the wrong object.** It protected the node-local scratch e2e
  directory; the thing that must be immutable is the *published* install `$SPX/$1` on shared `/ceph`,
  which the script rewrites **in place on the same inode** -- the SIGBUS hazard. v22-v28 were all
  published with no scratch directory present, so the guard would have passed straight through and
  overwritten a live install. It now guards `$V`, validates the version name, leaves the scratch
  workdir unguarded so a failed e2e can be retried, and **refuses to publish when e2e fails** (the
  exit status used to be printed and then ignored).
- **`launch.sh`'s duplicate-tag check was a TOCTOU race.** The stamp is written by the payload only
  after fork+exec, so simultaneous launches all passed the `[ -e ]` test: measured, three concurrent
  same-tag launches started **two** payloads and printed the *same* pid twice, leaving one untracked.
  The tag is now reserved atomically (`set -C`) before the fork -- 1 payload from 3.
- **A short-lived payload was reported as a launch failure and poisoned its tag.** `baseline_run.sh`'s
  own REFUSED guard exits in milliseconds, so *every refused arm* would have become unlaunchable.
  Now `LAUNCH_EXITED` (rc 8), tag reusable; a genuine never-started payload is rc 7.
- **Three drivers silently lost their execute bit.** The tools directory carries a default ACL
  (`default:group::rwx`, `other:---`), so a file written by a redirect lands 0660 with no `x`
  regardless of umask. Deploys now `chmod 771` explicitly.

Known and accepted: `LAUNCH_OK` means *started*, not *healthy* -- a payload that dies after the
~0.5 s confirmation window still reports OK. Check the log once at ~60 s. `LAUNCH_DIR` is node-local,
so the same tag can be launched on two different hosts; the damage is a wasted job, not corruption,
since arm directories are node-local and publishing only works on ibminode05.

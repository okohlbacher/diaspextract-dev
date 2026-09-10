Analysis of whether to reimplement the dnoise denoising method in SpeXtractor, 2026-09-10, at the
user's request.

The paper: Garrett, Diedrich and Yates III, *dnoise: Fast Native Data Reduction for Bruker
timsTOF*, bioRxiv 2026.08.27.747603 (Rust, MIT, github.com/pgarrett-scripps/dnoise). Three stages:
an ion-mobility streak filter (runs of >= `min_feature_length` = 5 occupied scans at near-constant
m/z, internal gaps <= 2 bridged, no intensity floor), a halo filter against detector saturation
(drop points below 0.15x the local off-column maximum), and geometric gates dropping MS1 signal
outside anything the method could fragment. Reported on diaPASEF: 91-94% of MS1 points removed,
precursor and protein-group counts within +/-0-2%.

Method: four grounding agents established what the codebase already does and what its numbers
really are; three independent integration designs (in the picker, in the loader, or as a detector
seeding criterion rather than a filter); each attacked; one judged.

* `verdict.md` -- the judgment, with the design, the arithmetic and the parameter sweep.
* The detector-stage design was REFUTED: it costs more than it saves (an occupancy byte per peak
  is +1.2 GB on dataset D) and the shared picker object would add 527 MB at the exact process
  peak.
* The headline: **ship the predicate as instrumentation before shipping any filter.** A count-only
  pass changes no byte of output and prices the entire proposal, including the two numbers nobody
  has ever logged (TNBC's picked MS1 count, and the fraction of picked MS1 peaks above the
  detector's own noise floor -- which decides whether the CPU win exists at all).

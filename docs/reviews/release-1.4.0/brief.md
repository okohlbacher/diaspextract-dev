# Pre-release review brief: DIAspeXtract 1.4.0 documentation

Review only -- do not modify, create or delete any file. HEAD is 50a3b41 on main; the last release is tag v1.3.2.
The documents under review are what users read: README.md, CHANGELOG.md (the v1.4.0 section), CITATION.cff and
docs/SAME-POSITION-DUPLICATION-2026-09-20.md; the code they describe is src/diaspextract.cpp at HEAD
(`git diff v1.3.2..HEAD -- src/` shows the change: the twin fold, option assembly:twin_im_tolerance). These files are
exported to a PUBLIC repository; docs/reviews, docs/benchmarks, harness/ and the files listed in .export-private are not.
If something is fine, say so in one line.

Attack, with file:line for every finding:
1. Every default and meaning in README.md's option tables against the registerXxxOption_/registerFlag_ calls in
   src/diaspextract.cpp (value, unit, the "-1 = off" style sentinels, what the help text says it does).
2. Every factual claim in the v1.4.0 CHANGELOG section against the code and against `git log v1.3.2..HEAD` -- a claim
   that is true of one path and stated for all, a number with no source, a change in the log that the CHANGELOG omits
   (only changes visible in exported files count).
3. README, the option's help text and the CHANGELOG describing the fold differently (relation, survivor, fusion,
   what -1 reproduces, the max_fragments interaction, determinism).
4. Anything that must not be public: the reference tool's name, cohort labels S08/S23/S26/S30/S33/S36, specimen IDs,
   /Users paths, references to private files or to results on data that is not public (the K562 set must NOT appear).
5. Version truth: CMakeLists.txt project(VERSION), the DIASPEXTRACT_VERSION fallback, CITATION.cff version and date,
   the CHANGELOG heading -- all 1.4.0 / 2026-09-23?

Rank by severity; say whether a reader would be misled or it is cosmetic.

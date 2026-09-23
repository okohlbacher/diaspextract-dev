# Pre-tag review brief: DIAspeXtract 1.4.1

Review only -- do not modify, create or delete any file. HEAD is the release commit; the last release is tag v1.4.0.
Under review: the v1.4.1 section of CHANGELOG.md, CITATION.cff, and the README.md changes since v1.4.0
(`git diff v1.4.0..HEAD -- README.md CHANGELOG.md CITATION.cff CMakeLists.txt`). The code they describe is
`git diff v1.4.0..HEAD -- src/ patches/ test/`. These files are exported to a PUBLIC repository; harness/, docs/reviews,
docs/BACKLOG*.md and the paths in .export-private are not, so the CHANGELOG must not describe them. If something is fine,
say so in one line.

1. Every factual claim in the v1.4.1 CHANGELOG section against the code: the fifth patch (what it changes in TOPPBase,
   both call sites), -write_ctd and -write_cwl behaviour, the PerfLoad guard, the six contained task loops (count them),
   DIASPEXTRACT_TASK_THROW (which sites), e2e 12d/12e, "the spectra are unchanged".
2. Any exported change since v1.4.0 the entry omits, and any claim about a non-exported file.
3. README: the patch table and "five patches" statements against patches/; the build instructions still correct.
4. Version truth: CMakeLists.txt project(VERSION), the DIASPEXTRACT_VERSION fallback, CITATION.cff version and date,
   the CHANGELOG heading -- all 1.4.1 / 2026-09-23.
5. Anything that must not be public: the reference tool's name, cohort labels, specimen IDs, /Users paths, K562.

For each finding: file:line, severity, whether a reader would be misled.

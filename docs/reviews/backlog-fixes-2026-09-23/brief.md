# Review brief: backlog fixes at 963ef21

Review only -- do not modify, create or delete any file. The change is `git show 963ef21` in this repository. If
something is fine, say so in one line.

1. **patches/openms-topp-docurl.patch** makes OpenMS `TOPPBase::getDocumentationURL()` virtual; src/diaspextract.cpp
   overrides it. Is the override correct C++ (signature, const, access), does making a non-virtual member virtual in
   a class other TOPP tools derive from break anything (ABI of libOpenMS for OTHER binaries built against the same
   library, vtable of TOPPBase), and does the patch apply to OpenMS bd4b895 (patches/openms.lock) with -p1?
2. **The PerfLoad guard** in patches/openms-brukertims-mz-calibration.patch: the hunk header was changed from +14 to
   +15 lines by hand. Is the hunk now consistent? Is "all five counters zero" the right "nothing loaded" test?
3. **Exception containment** (`taskErr_`, six taskloops in src/diaspextract.cpp): for each loop, does the try block
   cover the whole task body, is every `continue`/`break` still correct, is the rethrow placed after the taskloop's
   implicit taskgroup (so all tasks joined), and does the rethrown exception land in a handler (the MS1 call's
   ms1_err block, the window task's worker_err block) rather than escaping an OpenMP region? Is `taskFault_`
   (DIASPEXTRACT_TASK_THROW) safe to ship: thread-safe static init, zero effect when unset?
4. **harness/corpus.py kill_session**: kills every session member except the leader, waits (<= 30 s) for the leader
   (GNU time) to become a zombie, then killpg. Races: a member forking during the kill, the leader not being `time`,
   PID reuse, a session that is already gone, the 30-s wait blocking the runner. The leader must NOT be reaped here
   (Popen.wait would report exit 0) -- confirm it is not. The selftest case: is it deterministic, and does it really
   fail with the old one-signal kill?
5. The e2e checks 12d/12e and the README/build.yml/openms.lock wording.

For every finding: file:line, a concrete failing input, severity, and whether it bites in practice.

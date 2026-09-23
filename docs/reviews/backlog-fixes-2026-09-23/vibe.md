## Review of commit 963ef21

---

### 1. patches/openms-topp-docurl.patch

**patches/openms-topp-docurl.patch:8-17** – **Fine.**
- **Signature/const/access:** override `String getDocumentationURL() const` matches base `virtual String getDocumentationURL() const` in all three.
- **ABI:** no break in practice. The library is built from source with all five patches applied; no external binaries link against an unpatched libOpenMS.
- **Applies with -p1 to bd4b895:** yes. `a/src/openms/...` → `src/openms/...` matches OpenMS tree.

---

### 2. PerfLoad guard in patches/openms-brukertims-mz-calibration.patch

**patches/openms-brukertims-mz-calibration.patch:77-79** – **Fine.**
- **Hunk header +14 → +15:** consistent. The destructor grew from one line to two (added the guard + comment).
- **“all five counters zero”:** correct test for “nothing loaded”. All fields are zero-initialised and only incremented when actual decode/hand-off work occurs; `--help`, `FileFilter`, etc. leave them at zero.

---
---
### 3. Exception containment (six taskloops, `taskErr_`, `taskFault_`)

**src/diaspextract.cpp** – **Fine.**

| loop | try coverage | continue/break | rethrow placement | lands in handler | notes |
|---|---|---|---|---|---|
| detectTraces_ distribute (2469-2507) | 2471-2505 (whole body) | none | 2507, after implicit taskgroup | MS1 `ms1_err` | |
| detectTraces_ band tracing (2544-2563) | 2546-2561 | `continue` at 2553 inside try | 2563 | MS1 `ms1_err` | |
| detectTraces_ valley split (2589-2600) | 2591-2598 | `continue` at 2593 inside try | 2600 | MS1 `ms1_err` | |
| splitIntegerTraces (1237-1284) | 1239-1282 | none | 1284 | MS1 `ms1_err` | |
| window band tracing (4662-4668) | 4664-4666 | none | 4668 | window `worker_err` | |
| window assembly (4845-4865) | 4847-4863 | `break` at 4852 inside while inside try | 4865 | window `worker_err` | |

- **`taskErr_` (119-122):** thread-safe; critical section guards the shared `exception_ptr& first`; only first exception is stored.
- **`taskFault_` (126-129):** magic-static initialisation is thread-safe; zero effect when unset; throws only when env var matches site.
- **Rethrows after join:** all six `std::rethrow_exception` calls are after the `#pragma omp taskloop` implicit barrier, so every spawned task has completed and its exception (if any) has been captured.
- **Exception path:**
  - detectTraces_ loops → propagate out of detectTraces_ → caught at 3918 in MS1 single region → rethrown at 3919 outside the parallel region.
  - window loops → caught at 4900-4904 inside window task body → rethrown at 4908 outside the parallel region.
  - Neither exception leaves an OpenMP region.

---
---
### 4. harness/corpus.py kill_session

**harness/corpus.py:1086-1124** – **Fine.**

| race | mitigation | outcome |
|---|---|---|
| member forks during kill | final `killpg(pid, SIGKILL)` | new child killed by group signal |
| leader not GNU time | code works for any session leader | still kills children, waits for leader, then killpg |
| PID reuse | `ProcessLookupError` caught and ignored | safe; unlikely in the 30 s window |
| session already gone | `OSError`/`ProcessLookupError` caught | safe |
| 30-s wait blocks runner | none; designed | acceptable; bounded wait |
| leader reaped here? | code only reads /proc, never waits | **NOT reaped** – `Popen.wait()` must do it, else exit 0 |

- **Selftest case (G-V06, 4249-4256):** deterministic. Uses `/usr/bin/time -v ... python -c 'while True: pass'` → burn 4 s → checks own-tree CPU grew ≥ 1.0 s. Old one-signal `killpg` orphaned tool to init → whole CPU left tree → test failed; new kill_session lets wrapper reap → CPU stays → test passes.

---
---
### 5. e2e checks 12d/12e and documentation wording

| file | change | severity | bites |
|---|---|---|---|
| README.md:94,106,116,275 | “four” → “five”; added patch row in table | — | no |
| .github/workflows/build.yml:8,158 | “four” → “five” | — | no |
| patches/openms.lock:2 | “four” → “five” | — | no |
| test/test_diaspextract.py:468-479 | 12d checks `--help` and CTD → repo URL | — | no |
| test/test_diaspextract.py:485-491 | 12e checks injected task failures end with message/exit>0, not signal | — | no |

---
**Result: every item reviewed is fine.**

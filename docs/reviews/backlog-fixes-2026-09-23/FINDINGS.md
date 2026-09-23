# Review of the backlog fixes (963ef21, then de84164), 2026-09-23

Reviewers: **Kimi** (`kimi.md`) and **Vibe** (`vibe.md`, 2.25.5 with `--auto-approve --max-turns 200`, worktree left
clean). **Codex unavailable** (usage limit until 2026-09-27): an incomplete three-CLI review. Kimi's dispatcher run
ended in a bash syntax error after Kimi had finished: the dispatcher script was edited in place while it ran (the
dispatcher fix of the same day). The review file was complete (11 KB) and the worktree clean.

**Verdict, both: no finding that bites.** Kimi verified the patch context against OpenMS bd4b895, every OpenMP region
boundary, that a caught task exception cannot stall the window admission loop (the RAII release), and the kill_session
accounting chain (the leader is not reaped there, so a killed cell keeps its non-zero status).

**Found by running, not by review:** e2e 12d's CTD half failed on the first build: `-write_ctd` had never worked for this
tool (an unguarded ToolHandler::getTypes lookup). Fixed in de84164 by the same patch, renamed
openms-topp-external.patch; e2e then 30/30. `-write_cwl` now reaches OpenMS's TDL check and aborts on the cluster build
(no ENABLE_TDL) -- recorded in the backlog, not fixed.

Acted on:
- the patch header now states the ABI consequence (a new virtual before others shifts TOPPBase's vtable) (Kimi)
- the selftest case fails instead of raising when /proc sampling returns nothing (Kimi)

Recorded, not acted on: four of the six contained taskloops have no fault-injection site (the wrapping is mechanically
identical); after a window fails the admission loop still starts the remaining windows (pre-existing); a session member
stuck in uninterruptible sleep past the 30-s wait is still reaped by init (the old misaccounting, for that member only).

**Output unchanged.** Dev arm `v1.4.0fix1` (de84164, binary `4bb37b01…`, libOpenMS `1b9d8be5…`) published with e2e 30/30;
gate_D_140.sh on it: every arm PASS with 1.4.0's digests -- R1 `8c1b047f`, R2 `e43672a0` (fold off), R3 `9e2b075f` at 3
tiles, one tile, two cells per tile and 8 threads; env refusals and mzPeak output PASS (2026-09-23 17:20).

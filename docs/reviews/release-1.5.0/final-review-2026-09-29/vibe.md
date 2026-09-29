## Answer

**Q1 toTof() merge:** FINE. The regrouping is deterministic (sorted by imq then slab index, groups written at first member's position then sorted by that position), span cap boundary at exactly 2x is inclusive (<=). Frame-local, no order dependency. Theoretical and real-data: passes.

**Q2 Assembly guard:** FINE. Sort key is deterministic tuple, strongest member by intensity (first max wins, deterministic), RT overlap check deterministic. When no same-bin fragments exist, no merge occurs. Theoretical and real-data: passes.

**Q3 Same-bin fragments:** FINE. They survive only when both merges disabled; documented in CHANGELOG recipe. Acceptable as documented. Real-data: yes, this was 1.4.1 behavior.

**Q4 Ledger:** FINE. Negative delta correctly accounted for; `ledAdd_` receives final `sl.bytes() - led_b0` after all resizes. Thread-safe ledger function. Theoretical and real-data: passes.

**Q5 CHANGELOG/README:** FINE. All defaults match code and are stated correctly; recipe turns off every output-changing default added since v1.4.1. No unsupported claims. Theoretical: verified against code.

**Q6 Blockers:** NONE. All invariants preserved, documentation accurate, implementation correct.

---
**No findings. Release is ready to tag.**

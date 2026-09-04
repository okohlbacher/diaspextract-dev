• Reading the remaining pieces — the rest of `toTrace`, the OpenMS-path EPD call site, the banded merge, and the git history of these changes.

• Now let me look at the git history for these changes and find the OpenMS source locally.

• The old code is now cl• Now I need the actual OpenMS source. Let me check what OpenMS version this repo builds against, then fetch the EPD and MassTrace sources.


• The OpenMS source confirms the key structure. Let me verify the bins/inten invariant in `detectTracesInteger_` (change 1 hinges on it) and read `findLocalExtrema` plus `getAverageMS1CycleTime` to close out change 2.

• Two last cross-checks: whether anything references the removed memory-ledger category, and whether the window loop around `splitIntegerTraces` is parallel (ordering equivalence).


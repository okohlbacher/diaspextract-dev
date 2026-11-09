# Baseline faims192

Generated 2026-11-09T09:33:41-0600. Exclusive Slurm nodes, thread pinning: none. T(p) = median wall over 1 repeat(s); S(p) = T(p0)/T(p); E(p) = T(p0)*p0/(T(p)*p), p0 = smallest thread count of the cell; E_phys(p) uses min(p, physical cores) instead of p; SMT = p above the physical cores. CPU util = (user+sys)/(wall*p). `*` = contended (G-V06). DIA-NN wall is end to end (in-silico library prediction + search); extractor wall excludes the search.

| cell | kind | tool | sha256 | threads | search at |
|---|---|---|---|---|---|
| spx192 | cmd | diaspextract | 28d38f5aaece | 16 | 16 |
| dia_umpire | diaumpire | DIA-Umpire SE (DIA_Umpire_SE-2.2.8.jar) | 143cda2c5907 | 16 | 16 |

## Identifications (1% q)

| sample | cell | nodes | spectra | Sage peptides | MSFragger peptides | DIA-NN precursors | DIA-NN peptides | DIA-NN protein groups |
|---|---|---|---:|---:|---:|---:|---:|---:|
| PXD029902 | spx192 | node2-015 | 121,193 | 24,645 | 21,757 | - | - | - |
| PXD029902 | dia_umpire | node2-015 | 45,089 | 18,092 | 17,089 | - | - | - |
| PXD029902 | spx192 | node2-017 | 124,107 | 23,572 | 19,891 | - | - | - |
| PXD029902 | dia_umpire | node2-017 | 30,381 | 12,108 | 11,202 | - | - | - |
| PXD029902 | spx192 | node2-021 | 129,654 | 20,491 | 21,351 | - | - | - |
| PXD029902 | dia_umpire | node2-021 | 36,880 | 14,571 | 13,760 | - | - | - |
| PXD029902 | spx192 | node2-024 | 122,453 | 24,968 | 21,726 | - | - | - |
| PXD029902 | dia_umpire | node2-024 | 42,252 | 17,332 | 16,185 | - | - | - |
| PXD029902 | spx192 | node2-042 | 122,002 | 19,737 | 20,339 | - | - | - |
| PXD029902 | dia_umpire | node2-042 | 34,317 | 14,050 | 12,918 | - | - | - |
| PXD029902 | spx192 | node2-044 | 124,097 | 22,818 | 19,162 | - | - | - |
| PXD029902 | dia_umpire | node2-044 | 32,349 | 12,979 | 11,945 | - | - | - |
| PXD029902 | spx192 | node2-058 | 117,368 | 21,270 | 16,513 | - | - | - |
| PXD029902 | dia_umpire | node2-058 | 37,311 | 14,756 | 13,372 | - | - | - |
| PXD029902 | spx192 | node2-075 | 126,839 | 19,887 | 15,085 | - | - | - |
| PXD029902 | dia_umpire | node2-075 | 39,521 | 14,470 | 12,824 | - | - | - |
| PXD029902 | spx192 | node2-078 | 121,571 | 20,304 | 15,765 | - | - | - |
| PXD029902 | dia_umpire | node2-078 | 37,656 | 14,505 | 13,109 | - | - | - |
| PXD029902 | spx192 | node2-080 | 120,563 | 20,659 | 17,037 | - | - | - |
| PXD029902 | dia_umpire | node2-080 | 41,537 | 15,573 | 13,954 | - | - | - |
| PXD029902 | spx192 | node2-081 | 120,578 | 21,197 | 16,557 | - | - | - |
| PXD029902 | dia_umpire | node2-081 | 39,637 | 15,541 | 13,889 | - | - | - |
| PXD029902 | spx192 | node2-017 | 116,137 | 19,788 | 14,802 | - | - | - |
| PXD029902 | dia_umpire | node2-017 | 37,256 | 14,267 | 12,606 | - | - | - |
| PXD029902 | spx192 | node2-021 | 89,198 | 16,752 | 14,357 | - | - | - |
| PXD029902 | dia_umpire | node2-021 | 41,607 | 14,113 | 13,435 | - | - | - |
| PXD029902 | spx192 | node2-042 | 111,067 | 17,840 | 15,057 | - | - | - |
| PXD029902 | dia_umpire | node2-042 | 53,289 | 17,634 | 16,208 | - | - | - |

## Scaling

| sample | cell | p | SMT | wall | RSS GB | CPU util | S(p) | E(p) | E_phys(p) | n | spread |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PXD029902 | spx192 | 16 | no | 0:17 | 4.5 | 0.54 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:34 | 10.6 | 0.52 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:16 | 3.6 | 0.47 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:03 | 7.9 | 0.41 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:17 | 4.1 | 0.49 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 1:59 | 7.5 | 0.46 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:17 | 4.2 | 0.52 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:24 | 9.2 | 0.48 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:16 | 3.9 | 0.49 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:02 | 8.4 | 0.45 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:15 | 3.7 | 0.50 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:01 | 10.4 | 0.44 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:17 | 4.4 | 0.60 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:25 | 11.0 | 0.63 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:18 | 4.6 | 0.62 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:41 | 19.6 | 0.66 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:18 | 4.4 | 0.61 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:31 | 17.5 | 0.65 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:18 | 4.9 | 0.63 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:44 | 14.8 | 0.69 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:18 | 4.6 | 0.62 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:30 | 15.5 | 0.65 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:16* | 4.5 | 0.69 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 2:32* | 16.3 | 0.64 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:10* | 3.1 | 0.52 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 3:00* | 8.9 | 0.58 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | spx192 | 16 | no | 0:11* | 3.3 | 0.59 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD029902 | dia_umpire | 16 | no | 3:12* | 11.3 | 0.68 | 1.00 | 1.00 | 1.00 | 1 | - |

## Per tool (sum of T(p) over samples with every p)

| cell | samples | p | sum wall | S(p) | E(p) | E_phys(p) |
|---|---:|---:|---:|---:|---:|---:|
| spx192 | 14 | 16 | 3:44 | 1.00 | 1.00 | 1.00 |
| dia_umpire | 14 | 16 | 34:40 | 1.00 | 1.00 | 1.00 |

## Rules

- Peptides: `corpus2-count-1: target-only peptides keyed by modified sequence; Sage rank 1, peptide_q <= 0.01, label 1; MSFragger best hyperscore per (peptide, mods), TDC cut after complete equal-score groups`
- Entrapment: `corpus2-entrap-1: Wen et al. 2025 lower N_E/(N_T+N_E) and combined N_E(1+1/r)/(N_T+N_E) per charge stratum, bootstrap 95 % CI over accepted peptides (B=1000, seed 1); entrapment iff every protein is ENTRAP_; r per stratum`


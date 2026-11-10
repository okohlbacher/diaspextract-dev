# Baseline swath192pne

Generated 2026-11-10T11:16:00-0600. Exclusive Slurm nodes, thread pinning: none. T(p) = median wall over 1 repeat(s); S(p) = T(p0)/T(p); E(p) = T(p0)*p0/(T(p)*p), p0 = smallest thread count of the cell; E_phys(p) uses min(p, physical cores) instead of p; SMT = p above the physical cores. CPU util = (user+sys)/(wall*p). `*` = contended (G-V06). DIA-NN wall is end to end (in-silico library prediction + search); extractor wall excludes the search.

| cell | kind | tool | sha256 | threads | search at |
|---|---|---|---|---|---|
| spx192 | cmd | diaspextract | 28d38f5aaece | 16 | 16 |
| dia_umpire | diaumpire | DIA-Umpire SE (DIA_Umpire_SE-2.2.8.jar) | 143cda2c5907 | 16 | 16 |

## Identifications (1% q)

| sample | cell | nodes | spectra | Sage peptides | MSFragger peptides | DIA-NN precursors | DIA-NN peptides | DIA-NN protein groups |
|---|---|---|---:|---:|---:|---:|---:|---:|
| PXD002952 | spx192 | node2-045 | 1,283,893 | 10,194 | 6,355 | - | - | - |
| PXD002952 | dia_umpire | node2-045 | 366,993 | 24,885 | 23,849 | - | - | - |
| PXD002952 | spx192 | node2-044 | 1,292,608 | 10,587 | 6,315 | - | - | - |
| PXD002952 | dia_umpire | node2-044 | 369,517 | 24,711 | 23,880 | - | - | - |
| PXD002952 | spx192 | node2-044 | 1,270,806 | 10,223 | 6,501 | - | - | - |
| PXD002952 | dia_umpire | node2-044 | 360,434 | 24,551 | 23,502 | - | - | - |
| PXD002952 | spx192 | node2-045 | 1,289,315 | 10,207 | 6,303 | - | - | - |
| PXD002952 | dia_umpire | node2-045 | 362,597 | 24,760 | 23,712 | - | - | - |
| PXD002952 | spx192 | node2-044 | 1,282,748 | 9,930 | 6,666 | - | - | - |
| PXD002952 | dia_umpire | node2-044 | 359,480 | 24,268 | 23,219 | - | - | - |
| PXD002952 | spx192 | node2-045 | 1,296,163 | 10,085 | 6,351 | - | - | - |
| PXD002952 | dia_umpire | node2-045 | 358,010 | 24,063 | 23,458 | - | - | - |

## Scaling

| sample | cell | p | SMT | wall | RSS GB | CPU util | S(p) | E(p) | E_phys(p) | n | spread |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PXD002952 | spx192 | 16 | no | 7:43 | 27.4 | 0.49 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 13:02 | 69.3 | 0.61 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | spx192 | 16 | no | 6:20 | 26.6 | 0.59 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 12:38 | 67.9 | 0.58 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | spx192 | 16 | no | 6:34* | 26.0 | 0.55 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 12:14 | 68.7 | 0.56 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | spx192 | 16 | no | 6:14* | 26.3 | 0.56 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 12:11 | 58.2 | 0.57 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | spx192 | 16 | no | 6:05* | 25.5 | 0.57 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 11:55 | 69.1 | 0.55 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | spx192 | 16 | no | 7:36* | 26.1 | 0.48 | 1.00 | 1.00 | 1.00 | 1 | - |
| PXD002952 | dia_umpire | 16 | no | 11:43 | 66.4 | 0.57 | 1.00 | 1.00 | 1.00 | 1 | - |

## Per tool (sum of T(p) over samples with every p)

| cell | samples | p | sum wall | S(p) | E(p) | E_phys(p) |
|---|---:|---:|---:|---:|---:|---:|
| spx192 | 6 | 16 | 40:31 | 1.00 | 1.00 | 1.00 |
| dia_umpire | 6 | 16 | 1:13:42 | 1.00 | 1.00 | 1.00 |

## Rules

- Peptides: `corpus2-count-1: target-only peptides keyed by modified sequence; Sage rank 1, peptide_q <= 0.01, label 1; MSFragger best hyperscore per (peptide, mods), TDC cut after complete equal-score groups`
- Entrapment: `corpus2-entrap-1: Wen et al. 2025 lower N_E/(N_T+N_E) and combined N_E(1+1/r)/(N_T+N_E) per charge stratum, bootstrap 95 % CI over accepted peptides (B=1000, seed 1); entrapment iff every protein is ENTRAP_; r per stratum`

## Entrapment (1 % FDR by each engine's own rule)

| sample | cell | search | stratum | accepted | target | entrapment | r | lower % | lower 95% CI | upper % | upper 95% CI |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PXD002952 | spx192 | entrap | all | 9357 | 9313 | 44 | 0.4884 | 0.47 | 0.33-0.61 | 1.43 | 1.01-1.86 |
| PXD002952 | spx192 | entrap | z1 | 414 | 404 | 10 | 0.4884 | 2.42 | 0.97-4.11 | 7.36 | 2.94-12.51 |
| PXD002952 | spx192 | entrap | z2p | 8943 | 8909 | 34 | 0.4884 | 0.38 | 0.25-0.51 | 1.16 | 0.75-1.57 |
| PXD002952 | spx192 | entrap_msf | all | 5822 | 5803 | 19 | 0.4884 | 0.33 | 0.17-0.48 | 0.99 | 0.52-1.47 |
| PXD002952 | spx192 | entrap_msf | z1 | 263 | 261 | 2 | 0.4884 | 0.76 | 0.00-1.90 | 2.32 | 0.00-5.79 |
| PXD002952 | spx192 | entrap_msf | z2p | 5559 | 5542 | 17 | 0.4884 | 0.31 | 0.16-0.47 | 0.93 | 0.49-1.43 |
| PXD002952 | dia_umpire | entrap | all | 24092 | 23947 | 145 | 0.4884 | 0.60 | 0.50-0.70 | 1.83 | 1.52-2.12 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 24092 | 23947 | 145 | 0.4884 | 0.60 | 0.50-0.70 | 1.83 | 1.52-2.12 |
| PXD002952 | dia_umpire | entrap_msf | all | 23521 | 23431 | 90 | 0.4884 | 0.38 | 0.30-0.46 | 1.17 | 0.92-1.40 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 23521 | 23431 | 90 | 0.4884 | 0.38 | 0.30-0.46 | 1.17 | 0.92-1.40 |
| PXD002952 | spx192 | entrap | all | 9848 | 9797 | 51 | 0.4884 | 0.52 | 0.38-0.66 | 1.58 | 1.14-2.01 |
| PXD002952 | spx192 | entrap | z1 | 492 | 480 | 12 | 0.4884 | 2.44 | 1.22-3.86 | 7.43 | 3.72-11.77 |
| PXD002952 | spx192 | entrap | z2p | 9356 | 9317 | 39 | 0.4884 | 0.42 | 0.29-0.56 | 1.27 | 0.88-1.69 |
| PXD002952 | spx192 | entrap_msf | all | 5952 | 5936 | 16 | 0.4884 | 0.27 | 0.13-0.40 | 0.82 | 0.41-1.23 |
| PXD002952 | spx192 | entrap_msf | z1 | 303 | 297 | 6 | 0.4884 | 1.98 | 0.66-3.63 | 6.03 | 2.01-11.06 |
| PXD002952 | spx192 | entrap_msf | z2p | 5649 | 5639 | 10 | 0.4884 | 0.18 | 0.07-0.30 | 0.54 | 0.22-0.92 |
| PXD002952 | dia_umpire | entrap | all | 24081 | 23937 | 144 | 0.4884 | 0.60 | 0.50-0.69 | 1.82 | 1.52-2.11 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 24081 | 23937 | 144 | 0.4884 | 0.60 | 0.50-0.69 | 1.82 | 1.52-2.11 |
| PXD002952 | dia_umpire | entrap_msf | all | 23587 | 23481 | 106 | 0.4884 | 0.45 | 0.36-0.53 | 1.37 | 1.10-1.63 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 23587 | 23481 | 106 | 0.4884 | 0.45 | 0.36-0.53 | 1.37 | 1.10-1.63 |
| PXD002952 | spx192 | entrap | all | 9641 | 9581 | 60 | 0.4884 | 0.62 | 0.46-0.79 | 1.90 | 1.39-2.40 |
| PXD002952 | spx192 | entrap | z1 | 394 | 383 | 11 | 0.4884 | 2.79 | 1.27-4.57 | 8.51 | 3.87-13.92 |
| PXD002952 | spx192 | entrap | z2p | 9247 | 9198 | 49 | 0.4884 | 0.53 | 0.38-0.68 | 1.61 | 1.15-2.08 |
| PXD002952 | spx192 | entrap_msf | all | 5861 | 5830 | 31 | 0.4884 | 0.53 | 0.34-0.72 | 1.61 | 1.04-2.18 |
| PXD002952 | spx192 | entrap_msf | z1 | 323 | 314 | 9 | 0.4884 | 2.79 | 0.93-4.64 | 8.49 | 2.83-14.15 |
| PXD002952 | spx192 | entrap_msf | z2p | 5538 | 5516 | 22 | 0.4884 | 0.40 | 0.23-0.58 | 1.21 | 0.72-1.76 |
| PXD002952 | dia_umpire | entrap | all | 23918 | 23779 | 139 | 0.4884 | 0.58 | 0.48-0.68 | 1.77 | 1.47-2.06 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 23918 | 23779 | 139 | 0.4884 | 0.58 | 0.48-0.68 | 1.77 | 1.47-2.06 |
| PXD002952 | dia_umpire | entrap_msf | all | 22903 | 22819 | 84 | 0.4884 | 0.37 | 0.28-0.45 | 1.12 | 0.86-1.36 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 22903 | 22819 | 84 | 0.4884 | 0.37 | 0.28-0.45 | 1.12 | 0.86-1.36 |
| PXD002952 | spx192 | entrap | all | 9788 | 9721 | 67 | 0.4884 | 0.68 | 0.52-0.86 | 2.09 | 1.59-2.62 |
| PXD002952 | spx192 | entrap | z1 | 455 | 436 | 19 | 0.4884 | 4.18 | 2.42-6.15 | 12.73 | 7.37-18.75 |
| PXD002952 | spx192 | entrap | z2p | 9333 | 9285 | 48 | 0.4884 | 0.51 | 0.36-0.66 | 1.57 | 1.11-2.02 |
| PXD002952 | spx192 | entrap_msf | all | 5859 | 5845 | 14 | 0.4884 | 0.24 | 0.12-0.38 | 0.73 | 0.36-1.14 |
| PXD002952 | spx192 | entrap_msf | z1 | 318 | 314 | 4 | 0.4884 | 1.26 | 0.31-2.52 | 3.83 | 0.96-7.67 |
| PXD002952 | spx192 | entrap_msf | z2p | 5541 | 5531 | 10 | 0.4884 | 0.18 | 0.07-0.31 | 0.55 | 0.22-0.93 |
| PXD002952 | dia_umpire | entrap | all | 24155 | 23997 | 158 | 0.4884 | 0.65 | 0.55-0.75 | 1.99 | 1.67-2.30 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 24155 | 23997 | 158 | 0.4884 | 0.65 | 0.55-0.75 | 1.99 | 1.67-2.30 |
| PXD002952 | dia_umpire | entrap_msf | all | 23060 | 22973 | 87 | 0.4884 | 0.38 | 0.29-0.46 | 1.15 | 0.90-1.40 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 23060 | 22973 | 87 | 0.4884 | 0.38 | 0.29-0.46 | 1.15 | 0.90-1.40 |
| PXD002952 | spx192 | entrap | all | 9318 | 9270 | 48 | 0.4884 | 0.52 | 0.36-0.67 | 1.57 | 1.11-2.03 |
| PXD002952 | spx192 | entrap | z1 | 417 | 403 | 14 | 0.4884 | 3.36 | 1.68-5.28 | 10.23 | 5.12-16.08 |
| PXD002952 | spx192 | entrap | z2p | 8901 | 8867 | 34 | 0.4884 | 0.38 | 0.25-0.52 | 1.16 | 0.75-1.57 |
| PXD002952 | spx192 | entrap_msf | all | 6161 | 6128 | 33 | 0.4884 | 0.54 | 0.36-0.73 | 1.63 | 1.09-2.23 |
| PXD002952 | spx192 | entrap_msf | z1 | 314 | 306 | 8 | 0.4884 | 2.55 | 0.96-4.46 | 7.76 | 2.91-13.59 |
| PXD002952 | spx192 | entrap_msf | z2p | 5847 | 5822 | 25 | 0.4884 | 0.43 | 0.26-0.60 | 1.30 | 0.78-1.82 |
| PXD002952 | dia_umpire | entrap | all | 23533 | 23378 | 155 | 0.4884 | 0.66 | 0.55-0.76 | 2.01 | 1.67-2.32 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 23533 | 23378 | 155 | 0.4884 | 0.66 | 0.55-0.76 | 2.01 | 1.67-2.32 |
| PXD002952 | dia_umpire | entrap_msf | all | 22032 | 21959 | 73 | 0.4884 | 0.33 | 0.25-0.41 | 1.01 | 0.77-1.26 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 22032 | 21959 | 73 | 0.4884 | 0.33 | 0.25-0.41 | 1.01 | 0.77-1.26 |
| PXD002952 | spx192 | entrap | all | 9517 | 9466 | 51 | 0.4884 | 0.54 | 0.39-0.68 | 1.63 | 1.18-2.08 |
| PXD002952 | spx192 | entrap | z1 | 399 | 386 | 13 | 0.4884 | 3.26 | 1.50-5.26 | 9.93 | 4.58-16.04 |
| PXD002952 | spx192 | entrap | z2p | 9118 | 9080 | 38 | 0.4884 | 0.42 | 0.29-0.55 | 1.27 | 0.87-1.67 |
| PXD002952 | spx192 | entrap_msf | all | 5816 | 5797 | 19 | 0.4884 | 0.33 | 0.17-0.48 | 1.00 | 0.52-1.47 |
| PXD002952 | spx192 | entrap_msf | z1 | 277 | 270 | 7 | 0.4884 | 2.53 | 0.72-4.33 | 7.70 | 2.20-13.20 |
| PXD002952 | spx192 | entrap_msf | z2p | 5539 | 5527 | 12 | 0.4884 | 0.22 | 0.11-0.34 | 0.66 | 0.33-1.05 |
| PXD002952 | dia_umpire | entrap | all | 23286 | 23151 | 135 | 0.4884 | 0.58 | 0.48-0.68 | 1.77 | 1.45-2.07 |
| PXD002952 | dia_umpire | entrap | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap | z2p | 23286 | 23151 | 135 | 0.4884 | 0.58 | 0.48-0.68 | 1.77 | 1.45-2.07 |
| PXD002952 | dia_umpire | entrap_msf | all | 22806 | 22718 | 88 | 0.4884 | 0.39 | 0.30-0.47 | 1.18 | 0.92-1.43 |
| PXD002952 | dia_umpire | entrap_msf | z1 | 0 | 0 | 0 | 0.4884 | - | --- | - | --- |
| PXD002952 | dia_umpire | entrap_msf | z2p | 22806 | 22718 | 88 | 0.4884 | 0.39 | 0.30-0.47 | 1.18 | 0.92-1.43 |

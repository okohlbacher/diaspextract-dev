#!/usr/bin/env python3
"""M0 block statistics of the v2 design (output/DIA_extraction_design.md, Sec. 4) from a -diag:dump_blocks dump.

  python3 bench/blocks.py <prefix> [--sigma-im 0.005] [--collapse] [--json out.json]

Per isolation window: RT segments of L = 3 FWHM, stride 1.5 FWHM (FWHM = the run's median MS1 FWHM). A hypothesis is a
column of every segment its template support (apex +- FWHM, clipped to its MS1 span) overlaps; T = MS2 frames in the
segment, F = fragment traces whose span overlaps it. Per fragment, the active columns after the masks: IM
(|dIM| <= 3 sigma_IM; --collapse: off) and mass (fragment at z=1 lighter than the precursor's neutral mass - 56 Da).
Prints the K, K_eff, T, F distributions; the M0 go criterion is block K <= 32 in >= 95 % of blocks."""
import argparse, csv, json, sys
import numpy as np

MH = 1.007276


def load(path, cols):
    with open(path) as fh:
        r = csv.reader(fh, delimiter='\t')
        hdr = next(r)
        idx = [hdr.index(c) for c in cols]
        rows = [[float(x[i]) for i in idx] for x in r]
    return np.array(rows, dtype=float).reshape(-1, len(cols))


def pct(a, qs=(50, 90, 95, 99, 100)):
    a = np.asarray(a)
    return {f"p{q}": (float(np.percentile(a, q)) if a.size else 0.0) for q in qs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('prefix')
    ap.add_argument('--sigma-im', type=float, default=0.005)
    ap.add_argument('--collapse', action='store_true', help='IM axis projected out (g == 1, no IM mask)')
    ap.add_argument('--kcap', type=int, default=32)
    ap.add_argument('--drt-fwhm', type=float, default=0.5, help='K_local: |apex_k - apex_f| <= this x FWHM')
    ap.add_argument('--nms', action='store_true', help='Sec. 5.3 NMS first: by MS1 intensity, same charge, 10 ppm, 0.5 FWHM, sigma_IM')
    ap.add_argument('--json')
    a = ap.parse_args()
    P = load(a.prefix + '.prec.tsv', ['win_lo', 'win_hi', 'mono_mz', 'charge', 'rt', 'im', 'rt_lo', 'rt_hi', 'fwhm', 'intensity'])
    n_raw = len(P)
    F = load(a.prefix + '.frag.tsv', ['win_lo', 'win_hi', 'mz', 'im', 'rt', 'rt_lo', 'rt_hi'])
    fw = P[:, 8][P[:, 8] > 0]
    fwhm = float(np.median(fw)) if fw.size else 6.0
    L, stride = 3 * fwhm, 1.5 * fwhm
    if a.nms:
        keep = np.zeros(len(P), bool)
        for key in {tuple(r) for r in P[:, [0, 1, 3]].tolist()}:
            ix = np.nonzero((P[:, 0] == key[0]) & (P[:, 1] == key[1]) & (P[:, 3] == key[2]))[0]
            ix = ix[np.argsort(-P[ix, 9], kind='stable')]
            alive = np.ones(len(ix), bool)
            for j in range(len(ix)):
                if not alive[j]:
                    continue
                keep[ix[j]] = True
                q = P[ix[j]]
                d = ((np.abs(P[ix, 2] - q[2]) <= 10e-6 * q[2]) & (np.abs(P[ix, 4] - q[4]) <= 0.5 * fwhm)
                     & (a.collapse | (np.abs(P[ix, 5] - q[5]) <= a.sigma_im)))
                alive &= ~d
        P = P[keep]
    K_blocks, Keff_blocks, Keff_frag, T_blocks, F_blocks, K_local = [], [], [], [], [], []
    wins = sorted({(r[0], r[1]) for r in P[:, :2]})
    for wl, wh in wins:
        p = P[(P[:, 0] == wl) & (P[:, 1] == wh)]
        f = F[(F[:, 0] == wl) & (F[:, 1] == wh)]
        if len(p) == 0:
            continue
        frt = np.unique(f[:, 4]) if len(f) else np.array([0.0])
        cyc = float(np.median(np.diff(frt))) if frt.size > 2 else 1.0
        s_lo = np.maximum(p[:, 6], p[:, 4] - fwhm)
        s_hi = np.minimum(p[:, 7], p[:, 4] + fwhm)
        s_lo = np.minimum(s_lo, p[:, 4]); s_hi = np.maximum(s_hi, p[:, 4])
        z = np.where(p[:, 3] > 0, p[:, 3], 2)
        pmass = z * (p[:, 2] - MH)                         # neutral precursor mass
        # K_local: per fragment, the hypotheses co-eluting within drt (apex to apex) that pass the masks -- the columns its
        # own regression cannot separate by RT shape at T ~ L / cycle frames
        o = np.argsort(p[:, 4]); prt = p[o, 4]
        lo = np.searchsorted(prt, f[:, 4] - a.drt_fwhm * fwhm); hi = np.searchsorted(prt, f[:, 4] + a.drt_fwhm * fwhm)
        for i in range(len(f)):
            c = o[lo[i]:hi[i]]
            m = (f[i, 2] - MH) <= pmass[c] - 56.0
            if not a.collapse:
                m &= np.abs(f[i, 3] - p[c, 5]) <= 3 * a.sigma_im
            K_local.append(int(m.sum()))
        t0, t1 = p[:, 4].min() - fwhm, p[:, 4].max() + fwhm
        for a0 in np.arange(t0, t1, stride):
            a1 = a0 + L
            cols = np.nonzero((s_hi >= a0) & (s_lo <= a1))[0]
            if cols.size == 0:
                continue
            sel = (f[:, 6] >= a0) & (f[:, 5] <= a1)
            ff = f[sel]
            K_blocks.append(int(cols.size))
            T_blocks.append(int(round(L / cyc)))
            F_blocks.append(int(len(ff)))
            if len(ff) == 0:
                Keff_blocks.append(0)
                continue
            act = (ff[:, 2:3] - MH) <= (pmass[cols][None, :] - 56.0)      # mass mask, z_f = 1
            if not a.collapse:
                act &= np.abs(ff[:, 3:4] - p[cols, 5][None, :]) <= 3 * a.sigma_im
            ke = act.sum(1)
            Keff_frag.append(ke)
            Keff_blocks.append(int(act.any(0).sum()))   # columns some fragment can use
    Keff_frag = np.concatenate(Keff_frag) if Keff_frag else np.array([0])
    K_blocks = np.array(K_blocks); Kb = np.array(Keff_blocks)
    out = {
        'prefix': a.prefix, 'collapse': a.collapse, 'sigma_im': a.sigma_im, 'fwhm_s': fwhm, 'n_windows': len(wins),
        'n_hyp_raw': n_raw, 'n_hyp': int(len(P)), 'nms': a.nms, 'n_frag': int(len(F)), 'n_blocks': int(K_blocks.size),
        'K_block': pct(K_blocks), 'K_block_after_masks': pct(Kb), 'K_eff_per_fragment': pct(Keff_frag),
        'K_local_per_fragment': pct(K_local), 'share_fragments_K_local_le_1': float((np.array(K_local) <= 1).mean()),
        'share_fragments_K_local_le_3': float((np.array(K_local) <= 3).mean()), 'drt_fwhm': a.drt_fwhm,
        'T': pct(T_blocks), 'F': pct(F_blocks),
        'share_blocks_K_le_cap_after_masks': float((Kb <= a.kcap).mean()) if Kb.size else 1.0,
        'share_fragments_Keff_le_3': float((Keff_frag <= 3).mean()),
    }
    out['go_M0'] = out['share_blocks_K_le_cap_after_masks'] >= 0.95
    json.dump(out, sys.stdout, indent=1); print()
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()

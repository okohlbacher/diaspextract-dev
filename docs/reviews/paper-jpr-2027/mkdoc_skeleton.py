import json
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
S="/private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/e4677b2f-9916-478b-9db2-706d8e88d289/scratchpad"
d=Document()
st=d.styles['Normal']; st.font.name='Arial'; st.font.size=Pt(10.5)
for s in ('Heading 1','Heading 2','Heading 3','Title'): d.styles[s].font.name='Arial'
sec=d.sections[0]; sec.left_margin=sec.right_margin=Cm(2.2); sec.top_margin=sec.bottom_margin=Cm(2)
GREY=RGBColor(0x59,0x59,0x59); RED=RGBColor(0xA3,0x2D,0x2D)
def H(t,l=1): d.add_heading(t,level=l)
def P(t,italic=False,color=None,size=None):
    p=d.add_paragraph(); r=p.add_run(t); r.italic=italic
    if color: r.font.color.rgb=color
    if size: r.font.size=Pt(size)
    return p
def note(t): return P(t,italic=True,color=GREY,size=9.5)
def B(items,level=1):
    for it in items:
        if isinstance(it,list): B(it,level+1); continue
        p=d.add_paragraph(style='List Bullet' if level==1 else 'List Bullet %d'%level)
        # mark decisions / todos in red
        for tag in ('[DECISION]','[TODO]','[PENDING]','[VERIFY]'):
            if it.startswith(tag):
                r=p.add_run(tag+' '); r.bold=True; r.font.color.rgb=RED; it=it[len(tag):].lstrip(); break
        p.add_run(it)
def table(head,rows,widths=None):
    t=d.add_table(rows=1,cols=len(head)); t.style='Light Grid Accent 1'
    for i,h in enumerate(head):
        c=t.rows[0].cells[i]; c.text=''; r=c.paragraphs[0].add_run(h); r.bold=True; r.font.size=Pt(8.5)
    for row in rows:
        cells=t.add_row().cells
        for i,v in enumerate(row):
            cells[i].text=''; r=cells[i].paragraphs[0].add_run(str(v)); r.font.size=Pt(8.5)
    if widths:
        for row in t.rows:
            for i,w in enumerate(widths): row.cells[i].width=Cm(w)
    d.add_paragraph()

d.add_heading('DIAspeXtract — manuscript skeleton (J. Proteome Res., Article)',0)
note('Working draft, 2026-09-26 (rev. 2: public data only, single author). Bullets per section; numbers are from the benchmark harness on the 43 public runs '
     '(DIAspeXtract 1.5.0 release candidate vs diaTracer 2.2.1). Red tags mark open decisions and pending work.')

H('Submission plan')
B(['Target: J. Proteome Res., Special Issue "Software Tools and Resources 2027" (5th biennial). Submission deadline 2 November 2026; select the special issue at submission.',
   'Article type: Article (a new tool goes in as an Article; Technical Notes are for substantial updates of published tools). Limit 8,000 words, excluding Experimental Section, Acknowledgments, SI statement and references. Aim: ~5,000 words of main text, 5 figures, 2 tables.',
   'Reviewers install and test the tool: it must be free to reviewers at submission, with open license, public repository, documentation, installation guide, test data, and a citable release with a persistent identifier (Zenodo DOI).',
   'Raw data: MS raw files and metadata must be in ProteomeXchange (reviewer access in the manuscript). Reprocessed public data: cite the original PXDs; our search results need a deposit (PXD requires raw + identification results).',
   'TOC graphic required (≤ 3.25 × 1.75 in, sans-serif ≥ 6 pt, no specific results).',
   'Fallback venue: Bioinformatics Application Note (4 pages, ~2,000 words + 1 figure; Zenodo archive and state-of-the-art comparison on real data mandatory).',
   'Data scope (decided 2026-09-26): public data only — PXD017703 (27 HeLa runs) and PXD047793 (16 TNBC runs); optionally PXD029836 (3 runs). No unpublished or in-house data sets.',
   'Author (decided 2026-09-26): Oliver Kohlbacher, sole and corresponding author.',
   '[DECISION] Naming the reference tool: the paper must compare against diaTracer by name (the public-repository scrub rule covers the repo, not the paper — confirm).',
   '[TODO] Reviewer-ready distribution: container image (Docker/Apptainer) or static Linux binaries + a small test bundle; current releases ship source only.',
   '[TODO] Release 1.5.0 (pending codex review 27 Sep) and archive it on Zenodo; the paper describes exactly that version.'])
H('Timeline',2)
table(['Week','Work'],[
 ['28 Sep – 4 Oct','Ship 1.5.0 + Zenodo DOI; start container; naming decision'],
 ['5 – 11 Oct','Container + test bundle; PRIDE deposit of search results; Figures 2–4 from harness tables'],
 ['12 – 18 Oct','Figure 5 (engine-agnostic / open search); Figure 1 schematic; complete first draft'],
 ['19 – 25 Oct','Internal and adversarial review of the draft; colleague read-through'],
 ['26 Oct – 1 Nov','Revisions, TOC graphic, SI assembly, cover letter; submit by 2 Nov']],[3.5,12.5])

H('Title')
B(['Option A: DIAspeXtract: Fast, Memory-Efficient and Deterministic Pseudo-MS/MS Spectrum Extraction from diaPASEF Data for Any DDA Search Engine',
   'Option B: Spectrum-Centric Analysis of diaPASEF Data on a Workstation with DIAspeXtract',
   'Option C: DIAspeXtract: Open-Source Pseudo-Spectrum Extraction for diaPASEF Enables Closed, Open and Variant Searches with DDA Engines'])
H('Author and affiliation')
B(['Oliver Kohlbacher — sole and corresponding author.',
   '[TODO] Affiliation(s), e-mail, ORCID.'])

H('Abstract')
note('ACS style: one paragraph, no references; check the current JPR abstract word limit. ~200 words.')
B(['Context: diaPASEF combines ion-mobility separation with DIA; spectrum-centric analysis via pseudo-MS/MS spectra lets any DDA search engine (and open/variant search) analyze DIA data without spectral libraries.',
   'Gap: the current extractor for diaPASEF (diaTracer) needs 43–398 GB of memory per run; low-input spectra are the hard case; outputs are tied to one ecosystem.',
   'What we present: DIAspeXtract, an open-source OpenMS/TOPP tool (C++) with streaming input, RT tiling, deterministic output and an adaptive co-elution gate for faint precursors.',
   'Benchmark: 43 public runs (HeLa load, method and gradient series, PXD017703; tumor tissue, PXD047793), two search engines, entrapment-controlled FDR.',
   'Key results: extraction median 2.5× faster (up to 4.3×) at 6–35× lower peak memory (≤ 24 GB); peptides at 1% FDR 1.26× diaTracer with Sage, 0.92× with MSFragger; pipeline-to-pipeline (DIAspeXtract+Sage vs diaTracer+MSFragger) 1.01× the peptides at 2.3× lower total runtime; +87% peptides at 10 ng from the adaptive gate.',
   'Availability: GitHub URL, license, Zenodo DOI, container.'])
H('Keywords',2)
B(['data-independent acquisition; diaPASEF; timsTOF; ion mobility; pseudo-MS/MS spectra; spectrum-centric analysis; OpenMS; database search; open search; entrapment; false discovery rate'])
H('TOC graphic',2)
B(['Concept: .d file → DIAspeXtract (streaming, tiled) → pseudo-MS/MS mzML → any DDA engine (Sage, MSFragger, OpenMS ProSE, open search); small icons for memory (workstation) and determinism. No numbers.'])

H('Introduction')
note('~700 words.')
B(['DIA on timsTOF instruments (diaPASEF): sensitivity and throughput from trapped ion-mobility separation; data complexity (RT × 1/K0 × m/z).',
   'Two analysis paradigms: peptide-centric (library-based and library-free: DIA-NN, Spectronaut, AlphaDIA, …) vs spectrum-centric (deconvolute DIA into pseudo-MS/MS spectra, then DDA search).',
   'Why spectrum-centric still matters: reuse of mature DDA engines and their FDR machinery; open / mass-tolerant searches for PTMs; variant and SNP-aware searches; non-canonical peptides; no library bias; one workflow for DDA and DIA.',
   'Prior work: DIA-Umpire (Orbitrap DIA, feature co-elution); diaTracer (FragPipe, diaPASEF — the current state of the art for timsTOF). Limitations we address: memory footprint (hundreds of GB, JVM), runtime, reproducibility across hardware, sparse spectra from low-input samples, ecosystem lock-in.',
   'Contributions (bullet list in the paper):',
   ['an OpenMS-native C++ implementation usable from TOPP pipelines, KNIME/Nextflow, pyOpenMS',
    'streaming input and cell-atomic RT tiling with bounded memory (≤ 24 GB on 130-min tissue runs)',
    'deterministic output (identical across thread counts and tile grids)',
    'an adaptive co-elution gate for faint precursors plus evidence-ranked fragment assembly',
    'an engine-agnostic benchmark on public data with entrapment-based FDR validation on two engines']])

H('Experimental Section')
note('Not counted towards the 8,000 words; details go to SI where possible.')
H('Algorithm overview (Figure 1)',2)
B(['Input: native Bruker TDF reader; exact TOF m/z calibration from the MzCalibration table (validated against the vendor SDK: agreement to 5e-6 ppm); frame-by-frame streaming; optional mzPeak input.',
   'MS1 denoising: port of the dnoise v0.1.0 MS1 path (streak filter, halo filter, DIA window gate); identical to the reference implementation up to 100 ms accumulation time, approximated above.',
   'Mass-trace detection: integer-grid detector in m/z bands, ion-mobility aware, parallel.',
   'Precursor inference: isotope-pattern and charge assignment (incl. 1+ with a mobility veto), apex m/z estimator.',
   'Fragment tracing per isolation window with an RT/1/K0 index for candidate lookup.',
   'Co-elution gate: 1/K0 window (0.01), apex RT window (3 s), zero-padded Pearson correlation ≥ 0.3 over ≥ 3 shared points.',
   'Adaptive faint-precursor gate: precursors with signal in ≤ 4 window frames get a 6 s window, Fisher-z shrinkage of the correlation toward r0 = 0.6 (from ≥ 1 shared point), span co-location, a concentric test for traces too short to correlate, and correlation power 1 for intensity weighting.',
   'Assembly: up to 500 fragments ranked by evidence = max(r,0) · ln(1+I) · (1 + shared points); intensities weighted by r²; folding of duplicate claims on one precursor (same frame, charge, 20 ppm, 1/K0 ≤ 0.005).',
   'Output: mzML (or mzPeak) with header stamps recording every setting that shaped the output.'])
H('Scalability and determinism',2)
B(['RT tiling into fixed 600-s cells; ownership and carry of boundary fragments sized by the widest gate window; memory bounded by tile size.',
   'OpenMP parallelism over windows/tiles; deterministic tie-breaking; semantic output digest identical for 8 vs 100 threads and for 1, 2 or 3 tiles (regression-gated on every release; [TODO] show it on a public run for the paper).'])
H('Data sets (Table 1)',2)
B(['PXD017703 (HeLa, timsTOF Pro): py3 method 10/50/100 ng (120 min); 25pc method 10/50/100 ng (120 min); Evosep 60/100/200 samples per day (21/11.5/5.6 min). 27 runs, triplicates.',
   'PXD047793 (triple-negative breast cancer tissue, 130 min): 16 runs.',
   'Optional: PXD029836 (HeLa 200 ng, 166 ms accumulation; exercises the >100 ms dnoise path): 3 runs.',
   'Only public data sets are evaluated (decided 2026-09-26).'])
H('Extraction settings',2)
B(['DIAspeXtract 1.5.0 at defaults, 100 threads.',
   'diaTracer 2.2.1 with the parameters used in FragPipe DIA workflows (-mC 0.3 -dI 0.01 -dR 3 -rM 500 -mF 1 -mO 0.1 -r 0), -Xmx400G, 100 threads; precursor-annotation fix for Sage (describe in SI).'])
H('Database searches',2)
B(['Human UniProt reference proteome [TODO: release, entries] + reversed decoys.',
   'Closed search, both engines identical: precursor and fragment ±25 ppm, isotope error −1…+2, charge 2–4, trypsin/P, ≤ 2 missed cleavages, 7–35 aa, 500–5,000 Da; carbamidomethyl-C fixed; Met oxidation and protein N-terminal acetylation variable (≤ 2).',
   'Sage [TODO: version] with deisotoping; MSFragger 4.4.1 (top 150 peaks); OpenMS ProSE (closed only).',
   'Open search: ±130 Da precursor window, CAM fixed; MSFragger with delta-mass localisation.'])
H('FDR estimation and entrapment',2)
B(['Peptide-level 1% FDR: Sage peptide q-value (rank 1); MSFragger and ProSE target–decoy on the best score per peptide.',
   'Entrapment: searches against the target database plus an entrapment proteome; estimated FDR with confidence interval per run and per charge stratum (1+ vs ≥ 2+). [VERIFY] cite the entrapment estimator used.'])
H('Benchmark protocol',2)
B(['Paired runs on the same node back to back, identical staged copy, pre-warmed file cache; wall time, peak RSS and CPU from GNU time -v; runs with foreign CPU load flagged.',
   'Hardware: [TODO] nodes (cores, RAM).',
   'All runs driven by a versioned harness that refuses mismatched binaries, databases or inputs; per-run records in SI.'])
H('Implementation and availability',2)
B(['C++17 on OpenMS 3.x (five small upstream patches), OpenMP; TOPP tool diaspextract.',
   'License [TODO]; GitHub URL; Zenodo DOI for 1.5.0; container image; documentation; test data.'])

H('Results and Discussion')
note('~3,500 words.')
H('Benchmark design (short)',2)
B(['43 public runs: 27 HeLa runs at 10–100 ng (three acquisition methods, 5.6–120 min gradients) and 16 tumor-tissue runs (130 min); both extractors on identical inputs, both engines on both spectra sets.'])
H('Peptide identifications (Figure 2, Table 2)',2)
B(['Same engine, Sage: DIAspeXtract spectra give 1.26× the peptides of diaTracer spectra over the 43 runs (840,427 vs 668,193); per method: TNBC 1.38×, HeLa 25pc 1.30×, HeLa py3 1.20×, Evosep 1.00×.',
   'Same engine, MSFragger: 0.92× overall (769,712 vs 832,629); parity on TNBC (1.00×); HeLa 25pc 0.93×, py3 0.90×, Evosep 0.75×.',
   'Pipeline to pipeline (DIAspeXtract+Sage vs diaTracer+MSFragger): 840,427 vs 832,629 peptides (1.01×).',
   'Engine disagreement: on the same diaTracer spectra MSFragger finds 1.33× the peptides Sage finds (TNBC); winners flip by engine. Discuss spectrum properties that engines reward differently (peak density, intensity model, top-N peak picking).'])
H('Runtime and memory (Figure 3)',2)
B(['Extraction: median 2.5× faster per run (range 0.63–4.3×; TNBC median 8.5 vs 20.7 min); slower than diaTracer on all nine HeLa 25pc runs (0.63–1.0×) — explain (window count / method).',
   'Peak memory: 4.4–23.6 GB vs 43–398 GB (6–35×, median 17×; TNBC 23.6 vs 398 GB): runs on a workstation.',
   'Whole pipeline incl. search: 5 h 16 min vs 12 h 00 min for the 43 runs (2.3×).',
   'Scaling of memory with gradient length and load; effect of tiling (one tile vs 600-s cells) — SI.'])
H('Low-input samples and the adaptive co-elution gate (Figure 4)',2)
B(['Failure analysis at 10 ng: faint ions are the 1–3-point tip of their elution peak; a strict gate rejected most of their true fragments (3-point minimum 43%, 3-s window 21%, 1/K0 11% of true fragments).',
   'Peaks per spectrum: median 21 → 396 (diaTracer 298); spectra below the engines’ 6-peak minimum 10.9% → 1.1%.',
   'Effect: +87% (Sage) / +131% (MSFragger) peptides at 10 ng, +39%/+66% at 50 ng, +28%/+45% at 100 ng vs the non-adaptive gate; dense tissue unharmed (TNBC +2.9%/+3.3%) because the relaxed rules apply only to faint precursors; 41 of 43 runs gain on both engines, two lose ≈1% on one engine (one Evosep 200 SPD run, Sage −1.2%; one TNBC run, MSFragger −0.9%).',
   'Ablations (SI): each component (window, shrinkage, co-location, concentric test, evidence ranking) and the faint-frame threshold.'])
H('Engine-agnostic analysis and error-tolerant search (Figure 5)',2)
B(['[PENDING] Same spectra searched with Sage, MSFragger and OpenMS ProSE (closed) on the HeLa py3 10/50/100 ng series, both extractors: IDs, runtime, memory — report due 26/27 Sep.',
   'First number (HeLa 10 ng, DIAspeXtract spectra): ProSE 5,758 peptides (40 s, 5.1 GB) vs Sage 8,755 and MSFragger 7,149.',
   'Open search ±130 Da: modification spectrum (pyro-Glu, deamidation, oxidation, …) and single amino-acid-substitution candidates, compared between extractors.',
   'Caveat to discuss: DIA pseudo-spectra create co-isolation artefacts in open search (shared fragments match a peptide at the mass difference of co-eluting precursors); count only known-mass shifts, once per peptide and shift.'])
H('FDR control',2)
B(['Entrapment-estimated FDR at nominal 1%: DIAspeXtract 1.17% mean (0.84–1.65%) vs diaTracer 0.95% (0.62–1.40%) over the 43 runs.',
   'Highest on Evosep 200 SPD (1.60% vs 1.31%) and HeLa 25pc 10 ng (1.39% vs 0.80%); discuss mechanism (more low-evidence spectra) and mitigation.'])
H('Reproducibility',2)
B(['Output identical across thread counts and tile grids (digests); versioned harness and records; container.'])
H('Limitations',2)
B(['Short gradients (Evosep 60/100/200 SPD): 1.00× (Sage) and 0.75× (MSFragger) overall; the adaptive gate adds only +2% there.',
   'HeLa 25pc method: extraction slower than diaTracer (0.63–1.0×).',
   'MSFragger prefers diaTracer spectra on most sets.',
   'timsTOF/diaPASEF only (Orbitrap DIA not supported).',
   'Scope of comparison: peptide-centric tools (DIA-NN, Spectronaut) answer a different question; we compare spectrum-centric extractors; optionally one end-to-end FragPipe DIA reference.'])

H('Conclusions')
note('~250 words.')
B(['DIAspeXtract makes spectrum-centric diaPASEF analysis practical on standard hardware and in open pipelines.',
   'Matches the state of the art in identifications pipeline-to-pipeline, exceeds it with Sage, and is much faster and leaner.',
   'Enables closed, open and variant searches with any DDA engine; deterministic output for reproducible pipelines.',
   'Outlook: Orbitrap DIA, integration into OpenMS releases and quantification workflows.'])

H('Associated Content')
H('Supporting Information',2)
B(['S1 Per-run results for the 43 public runs (spectra, peptides both engines, entrapment FDR with CI, wall, RSS, CPU, load flags).',
   'S2 All tool and search parameters; database versions and checksums.',
   'S3 Entrapment procedure and per-stratum FDR (1+ vs ≥ 2+).',
   '[TODO] S4 Determinism evidence (digests across threads and tile grids) — repeat the tile/thread invariance gate on a public run (the release gate uses an in-house file).',
   'S5 Calibration validation against the vendor SDK.',
   'S6 MS1 denoising port validation.',
   'S7 Gate ablations and parameter selection (incl. the tuning record).',
   'S8 Benchmark harness description.',
   'S9 Open-search shift tables per data set.'])
H('Data and Software Availability',2)
B(['Raw data: PXD017703, PXD047793 [, PXD029836].',
   '[TODO] Search results: PRIDE deposit referencing the original PXDs (reviewer login in the manuscript).',
   '[TODO] Software: GitHub URL, license, Zenodo DOI (version 1.5.0), container image, test bundle, documentation.'])
H('Author Information')
B(['Corresponding author: Oliver Kohlbacher [TODO: e-mail, ORCID].',
   'Author contributions: sole author (conceptualization, software, validation, writing).',
   '[TODO] Competing interests statement.'])
H('Acknowledgments')
B(['[TODO] Funding; compute resources; the authors of the public data sets (PXD017703, PXD047793).'])
H('Abbreviations')
B(['DIA, DDA, diaPASEF, TIMS, 1/K0, FDR, RSS, SPD, PTM, TOPP.'])
H('References (to collect)')
note('Verify every reference before use.')
B(['diaPASEF method and the PXD017703 data (Meier et al.). [VERIFY]',
   'diaTracer (FragPipe spectrum-centric diaPASEF). [VERIFY]',
   'DIA-Umpire (Tsou et al.). [VERIFY]',
   'MSFragger; MSFragger open search / delta-mass localisation. [VERIFY]',
   'Sage (Lazear). [VERIFY]',
   'OpenMS 3 (Pfeuffer et al.). [VERIFY]',
   'dnoise (Garrett, Diedrich, Yates). [VERIFY]',
   'Entrapment-based FDR assessment. [VERIFY]',
   'DIA-NN, Spectronaut, AlphaDIA (context). [VERIFY]',
   'TNBC data set (PXD047793) and PXD029836 publications. [VERIFY]',
   'ProteomeXchange / PRIDE. [VERIFY]'])

H('Tables')
H('Table 1. Data sets',2)
table(['Data set','Accession','Sample / load','Gradient','Runs','Status'],[
 ['HeLa py3','PXD017703','HeLa 10 / 50 / 100 ng','120 min','9','public'],
 ['HeLa 25pc','PXD017703','HeLa 10 / 50 / 100 ng','120 min','9','public'],
 ['HeLa Evosep','PXD017703','HeLa, 60 / 100 / 200 SPD','21 / 11.5 / 5.6 min','9','public'],
 ['TNBC tissue','PXD047793','tumor tissue','130 min','16','public'],
 ['HeLa 200 ng','PXD029836','HeLa 200 ng, 166 ms accumulation','120 min','3','public (optional)']],[2.6,2.3,3.9,2.6,1.1,3.3])
H('Table 2. Per-set summary (current numbers)',2)
note('Public runs only. Peptides at 1% FDR summed over replicates (DIAspeXtract / diaTracer, same engine); entrapment FDR mean; median extraction wall; maximum peak RSS.')
rows=[]
for r in [x for x in json.load(open(S+'/table2.json')) if 'PXD' in x['set']]:
    rows.append([r['set'],r['n'],'%s / %s (%.2f×)'%(format(r['sage_o'],','),format(r['sage_d'],','),r['sage_o']/r['sage_d']),
                 '%s / %s (%.2f×)'%(format(r['msf_o'],','),format(r['msf_d'],','),r['msf_o']/r['msf_d']),
                 '%.2f / %.2f'%(r['fdr_o'],r['fdr_d']),'%d / %d'%(round(r['wall_o']),round(r['wall_d'])),'%.1f / %.0f'%(r['rss_o'],r['rss_d'])])
table(['Set','n','Sage peptides','MSFragger peptides','Entrap. FDR %','Wall s','RSS GB'],rows,[4.2,0.8,3.4,3.4,1.8,1.6,1.6])

H('Figures (legends to write)')
B(['Figure 1. Algorithm and data flow: .d → streaming load and calibration → MS1 denoising → trace detection → precursor inference → per-window fragment tracing → adaptive co-elution gate → evidence-ranked assembly and twin fold → tiled mzML output; inset: faint vs regular precursor gate.',
   'Figure 2. Identifications: peptides at 1% FDR per data set for both extractors × both engines (bars with replicate points), entrapment FDR per run below.',
   'Figure 3. Resources: extraction wall time and peak RSS per run (log scale), and whole-pipeline wall time per data set.',
   'Figure 4. Low input: peaks-per-spectrum distributions (diaTracer, non-adaptive gate, adaptive gate) at 10/50/100 ng, and peptide gains per load and engine.',
   'Figure 5. Engine-agnostic use: Sage, MSFragger and ProSE on identical spectra (IDs, runtime, memory); open-search mass-shift spectrum and substitution candidates for both extractors. [PENDING]'])
d.save(S+'/DIAspeXtract_JPR_manuscript_skeleton.docx'); print('saved')

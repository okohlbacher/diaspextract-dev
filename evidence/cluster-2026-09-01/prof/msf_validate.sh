#!/bin/bash
# Cross-engine gate validation: run MSFragger on baseline (det4, 1.53M) vs gated (924k) mzMLs,
# same DB+params, and compare peptides at 1% peptide-FDR. Confirms the -0.47% Sage cost holds on
# MSFragger (Sage-specific gains have misled before). Two OpenMS->MSFragger blockers handled:
# valueless cvParams (fix_mzml_cvparams.py) + labile_fragment_ion_series set to b,y.
set -u
B=/scratch/kohlbach/bench
MSF=/scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar
DB=$B/human_decoy.fasta
W=/scratch/kohlbach/prof/msf_gate; mkdir -p $W

echo "[db] ensure shared target+decoy ..."
[ -s "$DB" ] || python3 $B/joint_bench.py decoydb --target $B/human.fasta --out "$DB" 2>&1 | tail -2
echo "  decoys: $(grep -c '^>rev_' $DB)"

cat > $W/msfragger.params <<EOF
database_name = $DB
decoy_prefix = rev_
num_threads = 100
precursor_mass_lower = -25
precursor_mass_upper = 25
precursor_mass_units = 1
precursor_true_tolerance = 25
precursor_true_units = 1
fragment_mass_tolerance = 25
fragment_mass_units = 1
isotope_error = -1/0/1/2
search_enzyme_name_1 = trypsin
search_enzyme_cut_1 = KR
search_enzyme_nocut_1 = P
allowed_missed_cleavage_1 = 2
num_enzyme_termini = 2
digest_min_length = 7
digest_max_length = 35
digest_mass_range = 500.0 5000.0
max_variable_mods_per_peptide = 2
variable_mod_01 = 15.9949 M 3
variable_mod_02 = 42.0106 [^ 1
add_C_cysteine = 57.02146
precursor_charge = 2 4
override_charge = 0
output_format = tsv
output_report_topN = 1
output_max_expect = 50
minimum_peaks = 6
min_matched_fragments = 4
use_topN_peaks = 150
labile_fragment_ion_series = b,y
EOF

run_msf () {
  local NAME=$1 MZ=$2
  local d=$W/$NAME; mkdir -p $d
  local fixed=$d/fixed.mzML
  echo "[$NAME] fix cvParams -> $fixed"
  python3 $B/fix_mzml_cvparams.py "$MZ" "$fixed"
  echo "[$NAME] MSFragger (this is the slow step) ..."
  ( cd $d && java -Xmx220G -jar $MSF $W/msfragger.params "$fixed" > $d/engine.log 2>&1 )
  local tsv=$d/fixed.tsv
  [ -s "$tsv" ] || tsv=$(ls $d/*.tsv 2>/dev/null | head -1)
  if [ -z "$tsv" ] || [ ! -s "$tsv" ]; then
    echo "[$NAME] MSFRAGGER FAILED -- engine.log tail:"; tail -6 $d/engine.log; return 1
  fi
  echo "[$NAME] Scans reported: $(grep -oE '[0-9]+ Scans|Scans = [0-9]+' $d/engine.log | tail -1)"
  echo "[$NAME] SCORE:"
  python3 $B/joint_bench.py score "$tsv" --engine msfragger --label "$NAME"
}

echo ""; echo "===== MSFragger baseline (det4, 1.53M spectra) ====="
run_msf baseline /scratch/kohlbach/prof/det4/pseudo.mzML
echo ""; echo "===== MSFragger gated (924k spectra) ====="
run_msf gated /scratch/kohlbach/prof/gate/pseudo.mzML
echo ""; echo "MSF_VALIDATE_DONE"

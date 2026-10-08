# VF-coupled backup independent postverify

**Status:** `FAIL_READ_ONLY_POSTVERIFY`

Checked all 43 files (936,512 bytes) by raw source, destination, and committed blob comparison. Plan SHA-256 `d0564be84a6a51887db11a3aa2410fb9f3154935adc066e1c1d5487b8fb989e7`; execution receipt SHA-256 `32f8e57bda700e169c56720f0885f64499c543841e4f063f7fefbc88e3b0b35e`.

- PG: `97d213c988323da39ddbaa9ebb2135b675190c93`, 15 exact paths; remote matches; index/tracked clean True/True.
- VF: `f75c1a464e5806268cf2d5e09fcd3b833c2c19df`, 28 exact paths; remote matches; index/tracked clean True/True.
- Both raw push captures have rc=0 and include successful ref update lines; live `ls-remote` matches both heads.
- The receipt retains three earlier read-only/preflight failures; it records no repo mutations, then resumes the approved staged snapshot without recopies/restages. Full history is preserved in JSON.

Untracked files were preserved. This audit performed no copy, stage, commit, push, tests, CAD, or solver work.

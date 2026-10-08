# Narrow QA JSON coverage fix

The builder now includes `.json` review/QA records under `tmp/v147_user_merge_20261007/` that are at most 5 MiB and outside any parent directory containing `render`. Matching path components contain `qa`, `review`, `critic`, or `independent`; included rows are classified `closed_review_record`. This does not include render trees, the 39.8 MB structural diagnostic, or the 4.5 MB preflight diagnostic.

Before: 56155 bytes, SHA-256 `ae69f1ab9c0dda710cf1c9875295d185f81eeca9c7b38d0b1db1c6e7e5f5cd14`.

After: 56749 bytes, SHA-256 `cdb83cdea2c78f1e1a04df6d0ba6c21c9d02c94b9b9ced34999cb3eec7bdd90e`.

The exact pre-change bytes are preserved at `tmp/backup_coordinator/closeout_20261007/build_closeout_inventory_v2.py.pre_qa_json_coverage_fix_20261008.snapshot`. AST parsing passed; the source diff contains one inserted classifier block and no removed lines.

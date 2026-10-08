import ast
from pathlib import Path
p = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tools\next_experiment_export.py")
text = p.read_text(encoding="utf-8")
text = text.replace('import argparse\nimport json\nimport sys',
                    'import argparse\nimport collections\nimport json\nimport sys')
text = text.replace('    parser.add_argument("--release", default=None,\n'
                    '                        help="release id for the export step (default: the last frozen one)")',
                    '    parser.add_argument("--release", default=None,\n'
                    '                        help="release id for the export step (default: the last frozen one)")\n'
                    '    parser.add_argument("--allow-unverified", action="store_true",\n'
                    '                        help="if the freeze is refused, still export the batch scope through "\n'
                    '                             "a manifest that is explicitly marked UNFROZEN (never written to "\n'
                    '                             "<store>/releases) so the export/loader machinery can be exercised")')
ast.parse(text)
p.write_text(text, encoding="utf-8", newline="\n")
print("ok")

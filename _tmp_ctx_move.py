"""One-shot move: place the context export block *after* the queries table is built."""
from __future__ import annotations

import pathlib

P = pathlib.Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\storage\export.py")
lines = P.read_text(encoding="utf-8").splitlines(keepends=True)

start = next(i for i, line in enumerate(lines)
             if "simulated excavation context (plan t088)" in line and line.lstrip().startswith("#"))
end = next(i for i, line in enumerate(lines)
           if "degradation diversity (axis x level" in line)
block = lines[start:end]
rest = lines[:start] + lines[end:]

# ``counts["context_queries"]`` reads ``queries_rows``, so the block must follow the queries table
anchor = next(i for i, line in enumerate(rest)
              if "truth separation declaration" in line)
moved = rest[:anchor] + block + rest[anchor:]
P.write_text("".join(moved), encoding="utf-8")
print(f"moved {len(block)} lines from {start + 1} to before line {anchor + 1}")

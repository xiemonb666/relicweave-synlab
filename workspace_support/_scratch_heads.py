import io, re, sys

path = r"C:\Users\xiemo\Desktop\ShardForge\A12_Codex_Execution_Plan_V1.2.md"
raw = open(path, "rb").read()
for enc in ("utf-8", "gbk", "utf-16", "cp936"):
    try:
        text = raw.decode(enc)
        print("DECODED WITH", enc, "chars", len(text))
        break
    except Exception as e:
        print("fail", enc, e)
lines = text.splitlines()
print("total lines", len(lines))
out = []
for i, ln in enumerate(lines, 1):
    if re.match(r"^#{1,4}\s", ln):
        out.append("%d: %s" % (i, ln))
open(r"C:\Users\xiemo\Desktop\ShardForge\_scratch_heads.txt", "w", encoding="utf-8").write("\n".join(out))
print("heads", len(out))

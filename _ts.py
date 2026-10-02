import re
src = open("synlab/training/trainer.py", encoding="utf-8").read()
i = src.index("def train_step")
j = src.index("\n    def ", i+10)
body = src[i:j]
for m in re.finditer(r"return \{[^}]*\}", body, re.S):
    print(m.group(0)[:600]); print("---")

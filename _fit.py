import re
src = open("synlab/training/trainer.py", encoding="utf-8").read()
i = src.index("def fit")
j = src.index("\n    def ", i+10)
body = src[i:j]
k = body.find("accumulate")
# find the accumulation handling
for m in re.finditer(r"(accumulate|n_eff|window|zero_grad|optimizer.step)", body):
    pass
lines = body.splitlines()
for n, ln in enumerate(lines):
    if any(t in ln for t in ("accumulate", "n_eff", "optimizer.step", "zero_grad", "scale")):
        print(f"{n:4d}: {ln}")

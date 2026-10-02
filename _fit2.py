src = open("synlab/training/trainer.py", encoding="utf-8").read()
i = src.index("def fit")
j = src.index("\n    def ", i+10)
lines = src[i:j].splitlines()
for n, ln in enumerate(lines[10:60], start=10):
    print(f"{n:4d}: {ln}")

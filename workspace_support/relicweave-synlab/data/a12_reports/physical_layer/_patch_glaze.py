"""Patch v5: fix the glaze-strip remap shape and make the runner merge stages into the report."""
from pathlib import Path

a = Path("synlab/observe/fracture_appearance.py")
t = a.read_text(encoding="utf-8")
old = '''    def sample(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(modulation, d mod/du, d mod/dv)`` by bilinear lookup, outside the patch = 1."""
        import cv2

        iu = ((np.asarray(u, dtype=np.float64) - self.u0) / self.step_mm).astype(np.float32)
        iv = ((np.asarray(v, dtype=np.float64) - self.v0) / self.step_mm).astype(np.float32)
        grid = self.grid.astype(np.float32)
        mod = cv2.remap(grid, iu, iv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=1.0)
        gy, gx = np.gradient(self.grid.astype(np.float64), self.step_mm)
        d_mod_du = cv2.remap(gx.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        d_mod_dv = cv2.remap(gy.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        return (mod.astype(np.float64), d_mod_du.astype(np.float64), d_mod_dv.astype(np.float64))'''
new = '''    def sample(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(modulation, d mod/du, d mod/dv)`` by bilinear lookup, outside the patch = 1.

        ``cv2.remap`` wants ``(H, W)`` maps, so a flat query of N points is reshaped to ``(N, 1)``
        and the result is reshaped back: the renderer queries one point per pixel, the builder
        queries a whole grid, and both must give the same array shape back.
        """
        import cv2

        shape = np.broadcast(np.asarray(u, dtype=np.float64),
                             np.asarray(v, dtype=np.float64)).shape
        iu = ((np.asarray(u, dtype=np.float64) - self.u0) / self.step_mm)
        iv = ((np.asarray(v, dtype=np.float64) - self.v0) / self.step_mm)
        iu = np.ascontiguousarray(iu.astype(np.float32).reshape(-1, 1))
        iv = np.ascontiguousarray(iv.astype(np.float32).reshape(-1, 1))
        grid = self.grid.astype(np.float32)
        mod = cv2.remap(grid, iu, iv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=1.0)
        gy, gx = np.gradient(self.grid.astype(np.float64), self.step_mm)
        d_mod_du = cv2.remap(gx.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        d_mod_dv = cv2.remap(gy.astype(np.float32), iu, iv, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
        return (mod.astype(np.float64).reshape(shape),
                d_mod_du.astype(np.float64).reshape(shape),
                d_mod_dv.astype(np.float64).reshape(shape))'''
assert old in t, "glaze strip pattern missing"
t = t.replace(old, new, 1)
a.write_text(t, encoding="utf-8")

r = Path("tests/a12/observe/_run_fracture_appearance.py")
s = r.read_text(encoding="utf-8")
old2 = '''    report: dict = {"schema": fa.APPEARANCE_SCHEMA + ".run", "config": config.as_dict(),
                    "master_seed": MASTER_SEED, "specimen_entry": SPECIMEN,
                    "started_at_s": 0.0, "stages": {}, "timing": {}}'''
new2 = '''    # Stages are merged into an existing report when one is present, so a follow-up run of a single
    # stage does not throw away the stages already measured in a previous process.
    report_path = REPORT_DIR / "fracture_appearance_run.json"
    report: dict = {"schema": fa.APPEARANCE_SCHEMA + ".run", "config": config.as_dict(),
                    "master_seed": MASTER_SEED, "specimen_entry": SPECIMEN,
                    "started_at_s": 0.0, "stages": {}, "timing": {}}
    if report_path.exists() and not args.fresh:
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        report["stages"] = dict(previous.get("stages") or {})
        report["timing"] = dict(previous.get("timing") or {})
        report["previous_runs"] = list(previous.get("previous_runs") or []) + [
            {"finished_at": previous.get("finished_at"), "timing": previous.get("timing")}]
        print(f"[appearance] merging into {report_path} "
              f"({sorted(report['stages'])})", flush=True)'''
assert old2 in s, "report init pattern missing"
s = s.replace(old2, new2, 1)
old3 = '''    parser.add_argument("--no-store", action="store_true")'''
new3 = '''    parser.add_argument("--no-store", action="store_true")
    parser.add_argument("--fresh", action="store_true",
                        help="start a new report instead of merging into the existing one")'''
assert old3 in s
s = s.replace(old3, new3, 1)
old4 = '''        report["timing"][stage] = float(time.perf_counter() - t0)
        fa.write_json(report, REPORT_DIR / "fracture_appearance_run.json")'''
new4 = '''        report["timing"][stage] = float(time.perf_counter() - t0)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        fa.write_json(report, report_path)'''
assert old4 in s
s = s.replace(old4, new4, 1)
s = s.replace('fa.write_json(report, REPORT_DIR / "fracture_appearance_run.json")',
              'fa.write_json(report, report_path)')
r.write_text(s, encoding="utf-8")
print("patched")

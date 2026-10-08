"""Scratch probe 17: smoothness of h along a cell edge."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
h = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05, n_bands=3,
                        wavelength_min_mm=0.9)
A = np.array([6.3, -4.2])
P = np.array([6.825, -3.15])
ts = np.linspace(0.0, 1.0, 9)
uu = A[0] + (P[0] - A[0]) * ts
vv = A[1] + (P[1] - A[1]) * ts
exact = h(uu, vv)
hA = float(h(np.array([A[0]]), np.array([A[1]]))[0])
hP = float(h(np.array([P[0]]), np.array([P[1]]))[0])
lin = hA + ts * (hP - hA)
print("hA", round(hA, 6), "hP", round(hP, 6), flush=True)
print("exact", np.round(exact, 6).tolist(), flush=True)
print("linear", np.round(lin, 6).tolist(), flush=True)
du, dv = h.gradient(np.array([P[0]]), np.array([P[1]]))
print("grad at P", float(du[0]), float(dv[0]), flush=True)
print("h(u+0.01)", float(h(np.array([6.835]), np.array([-3.15]))[0]),
      "h(v+0.01)", float(h(np.array([6.825]), np.array([-3.14]))[0]), flush=True)
# numerical Hessian along the edge direction e
e = (P - A) / np.linalg.norm(P - A)
steps = np.array([-0.02, -0.01, 0.0, 0.01, 0.02])
base = P[None, :] + steps[:, None] * e[None, :]
vals = h(base[:, 0], base[:, 1])
print("along-edge h", np.round(vals, 8).tolist(), flush=True)
print("second difference", float(vals[0] - 2 * vals[2] + vals[4]) / (0.02 ** 2), flush=True)

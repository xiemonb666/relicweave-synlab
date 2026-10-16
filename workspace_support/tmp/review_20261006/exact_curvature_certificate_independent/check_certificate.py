"""Independent stdlib/Fraction checker for one saved certificate JSON.

Usage: python check_certificate.py CERTIFICATE.json EXPECTED_SHA256
Never imports or executes the certificate producer.
"""
from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction as F
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASE_FILE = ROOT / "vesselforge/experiments/exact_curvature_certificate_20261006/fixed_cases.json"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def pair(values):
    need(len(values) == 2, "point must have two coordinates")
    return F(values[0]), F(values[1])


def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def scale(a, x):
    return a[0] * x, a[1] * x


def controls(row, stations):
    h = F(row["h_mm"])
    need(h > 0, "nonpositive span length")
    a, b = stations[row["from"]], stations[row["to"]]
    p0, p1 = pair(a["rz_mm"]), pair(b["rz_mm"])
    v0, v1 = pair(a["d1"]), pair(b["d1"])
    q0, q1 = pair(a["d2"]), pair(b["d2"])
    j0, j1 = pair(a["d3"]), pair(b["d3"])
    u, v, w = h / 7, h * h / 42, h * h / 14
    x = h * h * h / 210
    return (p0, add(p0, scale(v0, u)), add(add(p0, scale(v0, 2*u)), scale(q0, v)),
            add(add(add(p0, scale(v0, 3*u)), scale(q0, w)), scale(j0, x)),
            add(sub(p1, scale(v1, 3*u)), sub(scale(q1, w), scale(j1, x))),
            add(sub(p1, scale(v1, 2*u)), scale(q1, v)), sub(p1, scale(v1, u)), p1)


def derivative(points):
    n = len(points) - 1
    return tuple(scale(sub(points[i+1], points[i]), F(n)) for i in range(n))


def split(values):
    levels = [list(values)]
    while len(levels[-1]) > 1:
        old = levels[-1]
        levels.append([(old[i] + old[i+1]) / 2 for i in range(len(old)-1)])
    return tuple(row[0] for row in levels), tuple(row[-1] for row in reversed(levels))


def split_points(points):
    levels = [list(points)]
    while len(levels[-1]) > 1:
        old = levels[-1]
        levels.append([scale(add(old[i], old[i+1]), F(1, 2)) for i in range(len(old)-1)])
    return tuple(row[0] for row in levels), tuple(row[-1] for row in reversed(levels))


def quarters(points):
    left, right = split_points(points)
    return (*split_points(left), *split_points(right))


def bprod(a, b):
    m, n = len(a)-1, len(b)-1
    out = [F(0)] * (m+n+1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            k = i+j
            out[k] += x*y*F(comb(m, i)*comb(n, j), comb(m+n, k))
    return tuple(out)


def elevate(a, target):
    out = tuple(a)
    while len(out)-1 < target:
        n = len(out)-1
        row = [out[0], *([F(0)]*n), out[-1]]
        for i in range(1, n+1):
            row[i] = F(i, n+1)*out[i-1] + F(n+1-i, n+1)*out[i]
        out = tuple(row)
    need(len(out)-1 == target, "degree elevation target too small")
    return out


def poly(points, radius):
    d1 = derivative(points)
    d2 = derivative(d1)
    x1, y1 = tuple(p[0] for p in d1), tuple(p[1] for p in d1)
    x2, y2 = tuple(p[0] for p in d2), tuple(p[1] for p in d2)
    s = tuple(a+b for a, b in zip(bprod(x1, x1), bprod(y1, y1)))
    det = tuple(a-b for a, b in zip(bprod(x1, y2), bprod(y1, x2)))
    s3 = bprod(bprod(s, s), s)
    d2e = elevate(bprod(det, det), 36)
    return tuple(a-radius*radius*b for a, b in zip(s3, d2e))


def frac_list(values):
    return [str(x) for x in values]


def parse_coefficients(leaf):
    raw = leaf.get("bernstein_coefficients")
    need(isinstance(raw, list) and raw, "missing leaf coefficients")
    return tuple(F(x) for x in raw)


def restricted(base, index, depth):
    row = tuple(base)
    for bitpos in range(depth-1, -1, -1):
        left, right = split(row)
        row = right if (index >> bitpos) & 1 else left
    return row


def check_cover(result, base, strict):
    leaves = result.get("cover")
    need(isinstance(leaves, list) and leaves, "empty polynomial cover")
    need(F(leaves[0]["interval"][0]) == 0 and F(leaves[-1]["interval"][1]) == 1, "cover endpoints")
    prior = F(0)
    labels = []
    for leaf in leaves:
        lo, hi = map(F, leaf["interval"])
        depth = leaf["depth"]
        need(lo == prior and hi > lo, "cover gap, overlap, or reversed leaf")
        need(isinstance(depth, int) and depth >= 0, "invalid leaf depth")
        cells = 1 << depth
        scaled = lo * cells
        need(scaled.denominator == 1 and hi-lo == F(1, cells), "non-dyadic leaf interval")
        coeff = parse_coefficients(leaf)
        need(len(coeff) == len(base) == 37, "polynomial must have degree 36")
        need(coeff == restricted(base, int(scaled), depth), "leaf coefficients do not match exact subdivision")
        left, right = coeff[0], coeff[-1]
        all_nonnegative, all_nonpositive = all(x >= 0 for x in coeff), all(x <= 0 for x in coeff)
        if (strict and (left <= 0 or right <= 0)) or (not strict and (left < 0 or right < 0)):
            need(leaf["status"] == "FAIL_CERTIFIED" and leaf["reason"] == "EXACT_ENDPOINT_VIOLATION", "bad endpoint failure")
        elif all_nonnegative and (not strict or (left > 0 and right > 0)):
            need(leaf["status"] == "PASS" and leaf["reason"] == "BERNSTEIN_COEFFICIENTS_PROVE_SIGN", "bad sign pass")
        elif all_nonpositive and any(x < 0 for x in coeff):
            need(leaf["status"] == "FAIL_CERTIFIED" and leaf["reason"] == "NEGATIVE_ON_OPEN_INTERVAL", "bad negative interval proof")
        elif strict and all(x == 0 for x in coeff):
            need(leaf["status"] == "FAIL_CERTIFIED" and leaf["reason"] == "IDENTICALLY_ZERO_NOT_STRICT", "bad zero strict failure")
        else:
            need(leaf["status"] == "UNKNOWN", "unproved leaf given a definitive status")
            if leaf["reason"] == "MAX_DEPTH_8":
                need(depth >= 8, "depth limit reported too early")
        labels.append(leaf["status"])
        prior = hi
    need(prior == 1, "cover does not end at one")
    expected = "FAIL_CERTIFIED" if "FAIL_CERTIFIED" in labels else "PASS" if set(labels) == {"PASS"} else "UNKNOWN"
    need(result.get("status") == expected, "top-level status disagrees with leaf proofs")
    nodes = result.get("nodes", 0)
    need(isinstance(nodes, int) and 0 <= nodes <= 256, "invalid target node count")
    return nodes


def check_target(result, points, radius, strict, field):
    need(result is not None, "missing target certificate")
    if radius is not None:
        need(F(result[field]) == radius, "wrong target value")
    base = poly(points, radius)
    if any(leaf.get("bernstein_coefficients") is None for leaf in result.get("cover", [])):
        need(result.get("status") == "UNKNOWN" and len(result["cover"]) == 1, "invalid unstarted target")
        leaf = result["cover"][0]
        need(leaf["interval"] == ["0", "1"] and leaf["status"] == "UNKNOWN", "invalid unstarted cover")
        return 0
    need(result.get("degree") == 36, "wrong polynomial degree")
    return check_cover(result, base, strict)


def main():
    need(len(sys.argv) == 3, "usage: check_certificate.py CERTIFICATE.json EXPECTED_SHA256")
    path = Path(sys.argv[1]).resolve()
    expected = sys.argv[2].lower()
    need(len(expected) == 64 and all(c in "0123456789abcdef" for c in expected), "bad expected SHA256")
    need(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "certificate SHA256 mismatch")
    fixed = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    case_sha = hashlib.sha256(CASE_FILE.read_bytes()).hexdigest()
    cert = json.loads(path.read_text(encoding="utf-8"))
    need(cert["status"] == "PURE_EXACT_LOCAL_CURVATURE_CERTIFICATE", "unexpected certificate status")
    need(cert["provenance"]["fixed_cases_sha256"] == case_sha, "fixed-case provenance mismatch")
    profile = ROOT / "vesselforge/experiments/whole_body_c2_profiles_20261006/profile_design.py"
    diagnostic = ROOT / "tmp/review_20261006/whole_body_c2_profiles_20261006/fixed_outer_trial/outer_math_diagnostic.json"
    need(cert["provenance"]["prior_profile_design_sha256"] == hashlib.sha256(profile.read_bytes()).hexdigest(), "profile provenance mismatch")
    need(cert["provenance"]["prior_math_diagnostic_sha256"] == hashlib.sha256(diagnostic.read_bytes()).hexdigest(), "diagnostic provenance mismatch")
    nodes_total = 0
    for family in ("bowl", "jar"):
        source = fixed["cases"][family]
        spans = cert["cases"][family]["spans"]
        need(len(spans) == len(source["outer_spans"]) == 8, f"{family}: span count")
        prior_end = None
        for row, got in zip(source["outer_spans"], spans):
            need(got["semantic"] == row["semantic"] and got["region"] == row["region"], f"{family}: span identity")
            need(prior_end is None or prior_end == row["from"], f"{family}: source span order")
            prior_end = row["to"]
            pts = controls(row, source["outer_stations"])
            rows = [[str(x), str(y)] for x, y in pts]
            need(got["control_points_rz_mm"] == rows, f"{family}/{row['semantic']}: controls mismatch")
            digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("ascii")).hexdigest()
            need(got["control_points_sha256"] == digest, f"{family}/{row['semantic']}: control hash")
            h = F(row["h_mm"])
            start, end = source["outer_stations"][row["from"]], source["outer_stations"][row["to"]]
            for order, data in enumerate((derivative(pts), derivative(derivative(pts)), derivative(derivative(derivative(pts)))) , 1):
                need(data[0] == scale(pair(start[f"d{order}"]), h**order), f"{family}/{row['semantic']}: start jet {order}")
                need(data[-1] == scale(pair(end[f"d{order}"]), h**order), f"{family}/{row['semantic']}: end jet {order}")
            proof = got["strict_projection_proof"]
            w = pair(row["projection_w"])
            norm = F(row["projection_norm_upper"])
            qs = []
            for i, net in enumerate(quarters(pts)):
                m = min(w[0]*p[0] + w[1]*p[1] for p in derivative(net))
                qs.append({"interval": [str(F(i, 4)), str(F(i+1, 4))],
                           "minimum_control_projection_local_parameter": str(m),
                           "minimum_control_projection_global_parameter": str(4*m), "strictly_positive": m > 0})
            need(proof["quarter_projection_cover"] == qs, f"{family}/{row['semantic']}: projection quarter proof")
            min_global = min(F(q["minimum_control_projection_global_parameter"]) for q in qs)
            valid = norm > 0 and norm*norm >= w[0]*w[0]+w[1]*w[1] and all(q["strictly_positive"] for q in qs)
            need(proof["minimum_derivative_control_projection"] == str(min_global), "projection minimum mismatch")
            need(proof["status"] == ("STRICT_SPEED_LOWER_BOUND" if valid else "UNKNOWN_STRICT_PROJECTION_NOT_PROVED"), "projection status mismatch")
            if valid:
                need(F(proof["speed_lower_per_local_parameter"]) == min_global/norm, "speed lower bound mismatch")
            radius = None
            region = row["region"]
            if region in {"base", "base_transition"}:
                radius = F(fixed["curvature_targets"]["base_and_inner_base_fairing_minimum_radius_mm"][family])
            elif region != "lip_closure":
                radius = F(fixed["curvature_targets"]["body_and_shoulder_minimum_radius_mm"])
            radius_cert = got["curvature_radius_certificate"]
            if radius is None:
                need(radius_cert["status"] == "REPORT_ONLY_NO_RADIUS_TARGET" and radius_cert.get("cover") == [], "unexpected lip radius target")
            else:
                nodes_total += check_target(radius_cert, pts, radius, False, "radius_mm")
            offset = got.get("three_mm_local_offset_certificate")
            if row["semantic"] in source["normal_offset_side_spans"]:
                nodes_total += check_target(offset, pts, F(3), True, "offset_distance_mm")
            else:
                need(offset is None, "unexpected offset target")
    limits = cert["limits"]
    need(nodes_total == limits["global_nodes_used"] and nodes_total <= 1024, "global node accounting mismatch")
    print(f"PASS: {path.name}; independent exact checks passed; nodes={nodes_total}")


if __name__ == "__main__":
    main()

from math import ceil, inf, isclose, isfinite, prod, nan
from types import SimpleNamespace

from synlab.errors import ErrorCode, SynLabError
from synlab.physical.sdf import choose_spacing, spacing_budget_report

bbox = (60.0, 40.0, 20.0)
declared = 0.5701
choice = choose_spacing(
    min_wall_thickness_mm=0.6,
    shortest_structure_mm=3.2,
    requested_mm=0.9,
    max_nodes=1000,
    bbox_mm=bbox,
    explicit_mm=declared,
)
assert choice['spacing_mm'] == declared
assert choice['basis'] == 'explicit'
assert choice['declared_spacing_mm'] == declared
assert choice['requested_spacing_mm'] == 0.9
assert isclose(choice['criteria']['min_wall_thickness/6'], 0.1, rel_tol=1e-12, abs_tol=1e-15)
assert choice['criteria']['shortest_structure/4'] == 0.8
assert choice['criteria']['requested'] == 0.9
assert choice['budget_limited'] is False
assert choice['relaxation_steps'] == 0
estimated = prod(ceil(side / declared) + 3 for side in bbox)
assert choice['budget_ok'] is (estimated <= choice['max_nodes'])
assert choice['budget_ok'] is False

report = spacing_budget_report(choice, bbox_mm=bbox)
assert report['requested_mm'] == 0.9
assert report['declared_mm'] == declared
assert report['request_honoured'] is False
assert report['request_honoured_basis'] == 'requested'
assert report['declared_honoured'] is True

implicit_request = choose_spacing(explicit_mm=declared)
report_declared = spacing_budget_report(implicit_request)
assert report_declared['requested_mm'] is None
assert report_declared['declared_mm'] == declared
assert report_declared['declared_honoured'] is True
assert report_declared['request_honoured'] is True
assert report_declared['request_honoured_basis'] == 'declared'

actual_grid = SimpleNamespace(spacing=0.9, shape=(4, 4, 4), n_nodes=64)
actual_report = spacing_budget_report(choice, bbox_mm=bbox, grid=actual_grid)
assert actual_report['realised_spacing_mm'] == 0.9
assert actual_report['request_honoured'] is True
assert actual_report['request_honoured_basis'] == 'requested'
assert actual_report['declared_honoured'] is False
actual_declared_only = spacing_budget_report(implicit_request, grid=actual_grid)
assert actual_declared_only['request_honoured'] is False
assert actual_declared_only['request_honoured_basis'] == 'declared'
assert actual_declared_only['declared_honoured'] is False

for invalid in (nan, inf, -inf, 0.0, -0.1, 'nan', 'invalid'):
    try:
        choose_spacing(explicit_mm=invalid)
    except SynLabError as exc:
        code = getattr(exc.code, 'value', exc.code)
        assert code == ErrorCode.SCHEMA_INVALID.value, (invalid, code)
    else:
        raise AssertionError(f'accepted invalid explicit spacing: {invalid!r}')

smallest_positive = float.fromhex('0x0.0000000000001p-1022')
small_choice = choose_spacing(explicit_mm=smallest_positive)
assert small_choice['spacing_mm'] == smallest_positive
assert small_choice['basis'] == 'explicit'
assert isfinite(small_choice['spacing_mm']) and small_choice['spacing_mm'] > 0.0

# Automatic selection remains the legacy min rule and relaxation behavior.
auto_no_bbox = choose_spacing(min_wall_thickness_mm=0.6, shortest_structure_mm=3.2)
assert auto_no_bbox['spacing_mm'] == 0.6 / 6.0
assert auto_no_bbox['basis'] == 'min_wall_thickness/6'
assert auto_no_bbox['budget_ok'] is True
assert auto_no_bbox['budget_limited'] is False
auto_budget = choose_spacing(
    min_wall_thickness_mm=0.6,
    shortest_structure_mm=3.2,
    max_nodes=600_000,
    bbox_mm=bbox,
)
assert auto_budget['spacing_mm'] > 0.1
assert auto_budget['basis'].endswith('+node_budget_relaxation')
assert auto_budget['budget_ok'] is False
assert auto_budget['budget_limited'] is True
assert auto_budget['relaxation_steps'] >= 1

print({
    'explicit_spacing_mm': choice['spacing_mm'],
    'explicit_criteria': choice['criteria'],
    'explicit_estimated_nodes': estimated,
    'explicit_max_nodes': choice['max_nodes'],
    'explicit_budget_ok': choice['budget_ok'],
    'explicit_budget_limited': choice['budget_limited'],
    'invalid_explicit_cases': 7,
    'smallest_positive_spacing_mm': small_choice['spacing_mm'],
    'auto_no_bbox': auto_no_bbox,
    'auto_budget': auto_budget,
    'report_no_requested': {
        'request_honoured': report_declared['request_honoured'],
        'request_honoured_basis': report_declared['request_honoured_basis'],
        'declared_honoured': report_declared['declared_honoured'],
    },
    'report_actual_grid_mismatch': {
        'realised_spacing_mm': actual_report['realised_spacing_mm'],
        'request_honoured': actual_report['request_honoured'],
        'request_honoured_basis': actual_report['request_honoured_basis'],
        'declared_honoured': actual_report['declared_honoured'],
    },
})


# Independent automatic-path equivalence against choose_spacing extracted from the frozen source.
import ast
import hashlib
import json
from pathlib import Path
from typing import Any
import math
import numpy as np

artifact_dir = Path(__file__).resolve().parent
repo_root = artifact_dir.parents[3]
original_source_path = artifact_dir / 'sdf.py.original'
current_source_path = repo_root / 'synlab' / 'physical' / 'sdf.py'
original_source_bytes = original_source_path.read_bytes()
current_source_bytes = current_source_path.read_bytes()
original_sha = hashlib.sha256(original_source_bytes).hexdigest().upper()
current_sha = hashlib.sha256(current_source_bytes).hexdigest().upper()
assert original_sha == '186583014D706CFCC20FBEFDA04A0C68E427F68E3BA7187A48F9A9115DDB827F'
assert current_sha == 'FD433876FA4DF84D2316C93DBBE521E1094241829D5FCCF93CEDEEAC02467B1D'
original_tree = ast.parse(original_source_bytes.decode('utf-8'), filename=str(original_source_path))
original_function = next(
    node for node in original_tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'choose_spacing'
)
function_module = ast.Module(body=[original_function], type_ignores=[])
function_code = compile(ast.fix_missing_locations(function_module), str(original_source_path), 'exec')
original_namespace = {
    'Any': Any,
    'ErrorCode': ErrorCode,
    'SynLabError': SynLabError,
    'math': math,
    'np': np,
}
exec(function_code, original_namespace)
original_choose_spacing = original_namespace['choose_spacing']

auto_cases = {
    'default': {},
    'wall_and_structure': {
        'min_wall_thickness_mm': 0.6,
        'shortest_structure_mm': 3.2,
    },
    'requested_finer': {
        'min_wall_thickness_mm': 0.6,
        'requested_mm': 0.05,
    },
    'requested_coarser': {
        'min_wall_thickness_mm': 0.6,
        'requested_mm': 0.8,
    },
    'budget_relax': {
        'min_wall_thickness_mm': 0.6,
        'shortest_structure_mm': 3.2,
        'max_nodes': 600_000,
        'bbox_mm': (60.0, 40.0, 20.0),
    },
    'bbox_fit': {
        'min_wall_thickness_mm': 1.2,
        'shortest_structure_mm': 8.0,
        'max_nodes': 4_000_000,
        'bbox_mm': (10.0, 10.0, 10.0),
    },
}
auto_case_results = {}
for case_name, kwargs in auto_cases.items():
    original_result = original_choose_spacing(**kwargs)
    current_result = choose_spacing(**kwargs)
    field_names = sorted(set(original_result) | set(current_result))
    field_equal = {
        field: field in original_result and field in current_result
        and original_result[field] == current_result[field]
        for field in field_names
    }
    keys_equal = set(original_result) == set(current_result)
    equal = keys_equal and all(field_equal.values()) and current_result == original_result
    auto_case_results[case_name] = {
        'kwargs': kwargs,
        'keys_equal': keys_equal,
        'field_equal': field_equal,
        'equal': equal,
        'original': original_result,
        'current': current_result,
    }
    assert equal, (case_name, auto_case_results[case_name])

machine_report = {
    'original_source_sha256': original_sha,
    'final_source_sha256': current_sha,
    'explicit_boundary': {
        'declared_spacing_mm': declared,
        'spacing_mm': choice['spacing_mm'],
        'strict_float_equal': choice['spacing_mm'] == declared,
        'basis': choice['basis'],
        'criteria': choice['criteria'],
        'estimated_nodes': estimated,
        'max_nodes': choice['max_nodes'],
        'budget_ok': choice['budget_ok'],
        'budget_limited': choice['budget_limited'],
        'invalid_explicit_inputs': [repr(value) for value in (nan, inf, -inf, 0.0, -0.1, 'nan', 'invalid')],
        'smallest_positive_spacing_mm': small_choice['spacing_mm'],
    },
    'report_without_requested': report_declared,
    'report_with_actual_grid_spacing': actual_report,
    'automatic_source_equivalence': auto_case_results,
}
report_path = artifact_dir / 'boundary_probe.v3.report.json'
report_path.write_text(json.dumps(machine_report, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
print('MACHINE_REPORT_JSON=' + json.dumps(machine_report, sort_keys=True, separators=(',', ':'), allow_nan=False))

from math import ceil, inf, isfinite, prod, nan
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
assert choice['criteria']['min_wall_thickness/6'] == 0.1
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
assert auto_no_bbox['spacing_mm'] == 0.1
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

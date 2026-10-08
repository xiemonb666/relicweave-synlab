# Frozen code snapshot — patches applied

This directory is a **scratch build artifact** of the realism pilot
(`tests/a12/observe/run_realistic_lineage.py`).  It is a copy of `synlab/`,
`blender_scripts/`, `configs/a12/` and the two realism test files, taken at the time the
runs were started, because the live working tree was being edited concurrently by other
agents (measured: `synlab/pipeline.py`, `synlab/fracture/*`, `synlab/observe/routes.py`
changed between 13:07 and 13:12 while the runs were in flight).

Nothing in this directory is a deliverable, and no file outside `data/a12_realistic/` is
affected by it.  It exists so that a reported measurement can be tied to an exact code
revision.  Delete the directory to reclaim the space.

## Patch 1 — `synlab/pipeline.py`, use-before-assignment (live-tree bug)

The live tree at the snapshot revision contained, inside `build_one_mother`:

```python
stamp_context(observation, context_for_fragment.get(primary_fragment_id, lineage_context))   # line 1739 (snapshot)
...
primary_fragment_id = str(getattr(observation, "fragment_id", "") or "")                     # line 1754 (snapshot)
```

`primary_fragment_id` is a function-local, so the first use raises

```
UNEXPECTED UnboundLocalError: cannot access local variable 'primary_fragment_id'
where it is not associated with a value
```

on **every** lineage (measured twice: `LIN0002_V23_M07_PAT12`, `LIN0003_V23_M11_PAT06`,
both `frag=3 obs=0`).  The patch only moves the assignment above its first use; no
semantics change.  The live file was *not* touched (it is outside this task's write scope).

An earlier transient state of the same file (13:07) raised
`TypeError: _commit_fragments() got an unexpected keyword argument 'context_for'`; the
snapshot was taken after that inconsistency was resolved.

## Everything else

No other file in this snapshot differs from the live tree at snapshot time, except that
`synlab/observe/realism.py` and `synlab/observe/quality.py` are the author's own new/modified
files (also present in the live tree) and the two realism test files are copies of the live
ones.

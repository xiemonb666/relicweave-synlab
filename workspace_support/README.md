# Shared workspace source and evidence archive

This directory preserves project scripts and small evidence that originally lived outside the
three Git repositories, plus project scripts from ignored SynLab `tmp/` and `data/` locations.
`archive_manifest.json` records original workspace-relative paths, bytes and SHA-256 hashes.
It excludes solver installations, SDK binaries, runtime caches and large raw histories. The
repository inventory under `docs/handover/20261016/repository_inventory/` describes local files.

Clone `vesselforge`, `pgfrag` and `relicweave-synlab` as siblings under one workspace. On Windows,
enable Git's long-path handling during cloning because historical source snapshots contain long
paths. From the workspace directory:

```powershell
git clone -c core.longpaths=true https://github.com/xiemonb666/vesselforge.git
git clone -c core.longpaths=true https://github.com/xiemonb666/pgfrag.git
git clone -c core.longpaths=true https://github.com/xiemonb666/relicweave-synlab.git
```

For an existing checkout, run `git config core.longpaths true` inside each repository. Then from
the SynLab repository root, use Python 3.11+ to inspect restoration:

```powershell
python tools/handover/archive_workspace_support.py restore --workspace .. --dry-run
```

After reviewing that report, restore missing files with:

```powershell
python tools/handover/archive_workspace_support.py restore --workspace ..
```

Both commands validate the whole archive and preflight all destination conflicts. A differing
existing file aborts restoration before any copying. No solver, experiment or feature code runs.
The archive operation itself is a maintainer action and should not be run in a fresh clone.

`docs/continuation/` contains shared status/math notes, `experiments/` contains root experiment
scripts and small receipts, and the other directories retain their original workspace names.
Archived scripts can contain machine-specific historical paths. Restoring them does not install
their external dependencies or make an unstarted experiment an accepted result. Development
remains paused; start with the [handover](../docs/handover/20261016/START_HERE.md).

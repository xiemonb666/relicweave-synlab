# A12 deployment package boundary, v2

`TrainingPackage` keeps the package schema at `synlab.training_package.v1` and requires
`synlab.training_package_deploy.v2` for forward reads. `TrainingPackage(path)` uses deployment
access by default. Reading labels, relations, measured observation quality, or the UUID-to-source
map requires `TrainingPackage(path, access="research")`. A historical v1 package remains readable
through that explicit research access; it is rejected as a forward feature source until migrated.

The deployment roster contains a fresh random opaque UUID for each observed fragment. A
ground-truth fragment without an actual observation does not enter that roster. Missing
observations raise `INPUT_UNAVAILABLE`; the loader does not synthesize a zero observation. The
optional `bag_id` roster column is accepted only when the manifest's capture-context scan declares
it in both policy blocks with the required capture-context, rig-available, and claim-allowed
properties. It remains excluded from the model feature bundle.

Deploy readers expose a generated manifest projection. Its view summary uses fixed public values,
its file rows contain only the allowlisted deploy path, verified SHA-256, and measured byte count,
and its `package_id` is derived from the deploy file inventory. Its `manifest_hash` hashes that
sanitized public projection. The full root manifest hash and caller-supplied package id are not
part of this API: they also commit to research labels and provenance. Explicit research access
continues to expose the full research manifest.

Construction validates the complete deploy inventory once and keeps its deploy path/hash pairs
as a read-only snapshot. Every later on-disk metadata or feature read hashes the exact bytes it
parses against that snapshot. JSON indices are checked against their closed v2 field contracts; NPZ and
observation TAR reads validate the same byte buffer against the declared member, array, shape, and
dtype allowlists. A changed file, extra alias, unsupported container, or unlisted deploy path is
rejected. Zarr is not a v2 deployment container.

These checks establish package structure and integrity for the loader. They do not establish
physical qualification or scientific validity of the observations.

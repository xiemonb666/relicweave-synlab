const cp = require("child_process");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const args = process.argv.slice(2);
const repo = args[0];
const revision = args[1];
const files = args.slice(2);
const hash = b => crypto.createHash("sha256").update(b).digest("hex");
const out = [];
for (const file of files) {
  const ref = revision === "INDEX" ? ":" + file : revision + ":" + file;
  const oid = cp.execFileSync("git", ["-C", repo, "rev-parse", ref], {encoding:"utf8"}).trim();
  const blob = cp.execFileSync("git", ["-C", repo, "cat-file", "blob", oid], {encoding:null, maxBuffer:16*1024*1024});
  const disk = fs.readFileSync(path.resolve(repo, file));
  out.push({path:file, blob_oid:oid, object_bytes:blob.length, object_sha256:hash(blob), worktree_bytes:disk.length, worktree_sha256:hash(disk), matches_worktree:blob.equals(disk)});
}
process.stdout.write(JSON.stringify(out));
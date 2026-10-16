"""Plot observed features only, without opening offline physics/identity targets."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def main():
    dataset = ROOT/"relicweave-synlab/data/continuation_20261015/native_cohesive_v6_dataset"
    output = ROOT/"pgfrag/experiments/cohesive_vessel_20261015/visualization_v6/observations_01"
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((dataset/"manifest.json").read_text())
    path = dataset/manifest["research_features"]["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != manifest["files"][path.name]["sha256"]:
        raise ValueError("feature payload hash mismatch")
    with np.load(path, allow_pickle=False) as features:
        rgb, depth = features["rgb_u8"], features["depth_m"]*1000
        if rgb.shape[0] != 6 or depth.shape != rgb.shape[:3]:
            raise ValueError("unexpected observed RGBD dimensions")
        finite = depth[np.isfinite(depth)]
        fig, axes = plt.subplots(2, 6, figsize=(15, 5), constrained_layout=True)
        for i in range(6):
            axes[0, i].imshow(rgb[i]); axes[0, i].set_title(f"View {i+1}")
            im = axes[1, i].imshow(depth[i], cmap="viridis", vmin=finite.min(), vmax=finite.max())
            for row in axes:
                row[i].axis("off")
        fig.colorbar(im, ax=axes[1].tolist(), label="Observed depth (mm)", shrink=.75)
        fig.suptitle("Closed-fragment observations | ideal software RGBD | uncalibrated research data")
        image = output/"six_observed_rgbd_views.png"
        fig.savefig(image, dpi=160)
        plt.close(fig)
    receipt = {"source_feature_sha256": digest, "source_dataset_manifest_sha256": hashlib.sha256((dataset/"manifest.json").read_bytes()).hexdigest(),
               "output_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "views": 6,
               "offline_targets_opened": False, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(image)


if __name__ == "__main__":
    main()

"""Observation: rendering, imaging chain, reconstruction routes, quality and features.

Module boundaries (plan 13 / 14):

* :mod:`synlab.observe.render`   -- real software rasteriser (CUSTOM_GAP for Blender)
* :mod:`synlab.observe.imaging`  -- ordered imaging chain (scene -> ... -> derivation)
* :mod:`synlab.observe.routes`   -- ideal_visible / proxy_scan / photo_mvs
* :mod:`synlab.observe.quality`  -- OBS_EST quality estimates (no GT prefill)
* :mod:`synlab.observe.features` -- observation-only feature adapter + leakage guard
* :mod:`synlab.observe.spurious` -- G08 spurious surfaces at the observation layer
* :mod:`synlab.observe.api`      -- the frozen façade
"""

from .api import (
    adapt_observed_features,
    commit_observation,
    estimate_quality,
    load_observation,
    observation_to_dict,
    observe,
)
from .imaging import ImagingSpec, apply_imaging_chain
from .quality import OBS_EST_VERSION, estimate_quality as estimate_quality_dict
from .render import (
    BACKEND_SOFTWARE,
    BLENDER_GAP,
    LightSpec,
    RenderSpec,
    Scene,
    build_scene,
    capability_probe,
    render_view,
)
from .routes import ROUTE_SPECS, observation_from_dict

__all__ = [
    "observe", "commit_observation", "load_observation", "adapt_observed_features",
    "estimate_quality", "observation_to_dict", "observation_from_dict",
    "ImagingSpec", "apply_imaging_chain", "OBS_EST_VERSION",
    "BACKEND_SOFTWARE", "BLENDER_GAP", "LightSpec", "RenderSpec", "Scene", "build_scene",
    "capability_probe", "render_view", "ROUTE_SPECS", "estimate_quality_dict",
]

"""A12 SynLab HTTP API package.

The public entry point is :func:`create_app`; the heavy lifting always happens in a
separate worker process (:mod:`synlab.api.worker`), never inside a request thread.
"""

from __future__ import annotations

from .app import API_PREFIX, create_app

__all__ = ["create_app", "API_PREFIX"]

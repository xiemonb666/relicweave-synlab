"""A12 controllable synthetic fragment laboratory (standalone ``relicweave-synlab``).

Main repository integration is *not* completed: this package is a standalone
implementation exposing ``ObsPackAdapter``-style contracts, marked
``MAIN_REPO_INTEGRATION_PENDING`` (plan 0.1 step 4).
"""

from __future__ import annotations

__version__ = "0.1.0"

INTEGRATION_STATUS = "MAIN_REPO_INTEGRATION_PENDING"

__all__ = ["__version__", "INTEGRATION_STATUS"]

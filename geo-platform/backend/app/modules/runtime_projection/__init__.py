"""Read-only virtual Runtime projection for the frozen Golden cases."""

from .projector import (
    CASE_MANIFESTS,
    SPIKE_CONTRACT_VERSION,
    RuntimeProjectionProjector,
    run_projection_spike,
)

__all__ = [
    "CASE_MANIFESTS",
    "SPIKE_CONTRACT_VERSION",
    "RuntimeProjectionProjector",
    "run_projection_spike",
]

"""Platform adapter registry."""
from .base import (
    PlatformAdapter, PlatformError, OutOfWindowError, HumanReviewNeeded,
    ReturnModel,
)
from .flipkart import FlipkartAdapter
from .amazon import AmazonAdapter

_REGISTRY: dict[str, PlatformAdapter] = {
    "flipkart": FlipkartAdapter(),
    "amazon": AmazonAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter:
    key = platform.strip().lower()
    if key not in _REGISTRY:
        raise PlatformError(f"No adapter registered for platform: {platform!r}")
    return _REGISTRY[key]


__all__ = [
    "get_adapter", "PlatformAdapter", "PlatformError",
    "OutOfWindowError", "HumanReviewNeeded", "ReturnModel",
]

"""
Abstract platform adapter.

Every platform (Amazon, Flipkart, future: Myntra, Meesho, ...) implements
this contract. The runner is completely platform-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from browser import BrowserSession
    from excel_io import TaskRow, Result


class ReturnModel(str, Enum):
    BATCH = "Batch"            # one return flow covers every eligible SKU in the order
    SEQUENTIAL = "Sequential"  # repeat the return micro-flow once per SKU


# --- exceptions ------------------------------------------------------------

class PlatformError(Exception):
    """Generic hard failure inside a platform adapter."""


class OutOfWindowError(PlatformError):
    """Item is past its return window — recoverable, per-item only."""


class HumanReviewNeeded(PlatformError):
    """
    CAPTCHA, OTP challenge, unusual verification, or otherwise blocked.
    Runner MUST NOT retry — that behaviour is itself a bot signal.
    """


# --- contract --------------------------------------------------------------

class PlatformAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def login(self, session: "BrowserSession") -> None:
        """Bring the session to a logged-in state. Idempotent — if the
        persistent profile is already authed, this is a no-op."""

    @abstractmethod
    def detect_return_model(
        self, session: "BrowserSession", order_id: str
    ) -> ReturnModel:
        """
        Open the order page and inspect its return UI. If the page
        presents a multi-select "choose items to return" screen, return
        BATCH; if returns are single-SKU only, return SEQUENTIAL.
        """

    @abstractmethod
    def execute(
        self, session: "BrowserSession", order_id: str,
        tasks: list["TaskRow"], model: ReturnModel,
    ) -> Iterator["Result"]:
        """
        Execute returns for every task on this order and YIELD a Result
        per line item as soon as it completes.  Yielding (instead of
        returning a full list at the end) is what lets the runner do
        immediate write-back — partial progress survives a crash.
        """

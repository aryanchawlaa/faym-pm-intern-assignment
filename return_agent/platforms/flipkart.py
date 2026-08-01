"""
Flipkart return adapter.

Flipkart's return UI is sequential: one micro-flow per line item. There
is no batch multi-select return screen, so detect_return_model always
returns SEQUENTIAL.

Auth: mobile + OTP. The test account (per the brief) is
9205359199 — the human on that phone must supply the OTP.

Selector strategy:
  - Every selector is centralized in SELECTORS so a UI change is one
    file to update, not scattered across the flow.
  - We prefer `data-testid` / stable text over auto-generated class
    names (Flipkart uses hashed Tailwind-ish class names that churn).
  - Real selectors will need periodic maintenance — the brief noted
    this in the "Platform UI changes" risk row.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterator

from playwright.sync_api import TimeoutError as PWTimeout

from .base import (
    PlatformAdapter, ReturnModel, OutOfWindowError, HumanReviewNeeded,
    PlatformError,
)

log = logging.getLogger("flipkart")

# Selectors are best-effort against production Flipkart at time of writing.
# They MUST be re-verified on any UI change.
SELECTORS = {
    "login_input":        "input[type='text']",
    "login_continue_btn": "button:has-text('Continue')",
    "otp_input":          "input[maxlength='6']",
    "otp_submit":         "button:has-text('Verify')",
    "captcha_hint":       "text=/captcha|robot|verify you are human/i",
    "order_row":          "div[data-testid='order-row']",
    "item_return_btn":    "button:has-text('Return')",
    "return_reason":      "select[name='reason']",
    "refund_method_upi":  "input[value='UPI']",
    "confirm_return":     "button:has-text('Confirm')",
    "return_id_text":     "text=/Return ID[:\\s]+([A-Z0-9-]+)/i",
    "refund_amount_text": "text=/Refund of ₹\\s?([0-9,]+)/i",
    "out_of_window_msg":  "text=/return window has (closed|expired)/i",
}

FLIPKART_LOGIN_URL  = "https://www.flipkart.com/account/login"
FLIPKART_ORDERS_URL = "https://www.flipkart.com/account/orders"
FLIPKART_ORDER_URL  = "https://www.flipkart.com/account/order-details?order_id={order_id}"


class FlipkartAdapter(PlatformAdapter):
    name = "flipkart"

    # ---------- login ----------

    def login(self, session) -> None:
        session.goto(FLIPKART_LOGIN_URL)
        # If persistent profile is already logged in, orders link is
        # reachable and we're done.
        if "login" not in session.page.url:
            log.info("Flipkart: reusing existing session (cookies present)")
            return

        phone = os.environ.get("FAYM_FLIPKART_PHONE", "9205359199")
        log.info("Flipkart login required for %s", phone)
        session.human_type(SELECTORS["login_input"], phone)
        session.human_click(SELECTORS["login_continue_btn"])
        self._check_challenge(session)

        # Ask a human for the OTP (never intercept SMS automatically).
        from browser import request_otp_from_human
        otp = request_otp_from_human(phone)
        session.human_type(SELECTORS["otp_input"], otp)
        session.human_click(SELECTORS["otp_submit"])
        session.human_pause(1.5, 2.5)
        self._check_challenge(session)
        log.info("Flipkart login OK")

    # ---------- detect ----------

    def detect_return_model(self, session, order_id: str) -> ReturnModel:
        # Flipkart is sequential-only. We still open the order page to
        # confirm the account can see it — if the order isn't visible we
        # want to fail fast rather than loop.
        session.goto(FLIPKART_ORDER_URL.format(order_id=order_id))
        session.human_pause()
        self._check_challenge(session)
        # Sanity check: does the order page even show a Return control?
        # (count() is the safe, timeout-free API — is_visible() in modern
        # Playwright doesn't accept a timeout kwarg.)
        try:
            session.page.locator(SELECTORS["item_return_btn"]).first.wait_for(
                state="visible", timeout=5_000
            )
        except PWTimeout:
            log.warning("No Return button visible for order %s", order_id)
        return ReturnModel.SEQUENTIAL

    # ---------- execute ----------

    def execute(self, session, order_id, tasks, model) -> Iterator:
        from excel_io import Result, Status  # local import to avoid cycle

        for task in tasks:
            log.info("Flipkart: order=%s sku=%s", order_id, task.sku)
            try:
                # Re-open the order page each time — Flipkart typically
                # bounces you back to orders list after a confirmation.
                session.goto(FLIPKART_ORDER_URL.format(order_id=order_id))
                self._check_challenge(session)

                item = self._find_item_row(session, task.sku)
                if item is None:
                    yield Result(
                        row_id=task.row_id, sku=task.sku,
                        return_status="Failed",
                        task_status=Status.NEEDS_REVIEW,
                        error=f"SKU {task.sku!r} not found on order page",
                    )
                    continue

                # Out-of-window check up front — no point clicking through.
                if item.locator(SELECTORS["out_of_window_msg"]).count() > 0:
                    yield Result(
                        row_id=task.row_id, sku=task.sku,
                        return_status="Out of window",
                        task_status=Status.NEEDS_REVIEW,
                        error="Return window closed",
                    )
                    continue

                # Kick off the micro-flow.
                item.locator(SELECTORS["item_return_btn"]).first.click()
                session.human_pause()
                self._check_challenge(session)

                # Reason: hardcode a safe default; policy question flagged
                # in PRD §12.  Ops can override via env var.
                reason = os.environ.get("FAYM_DEFAULT_REASON", "Item not as described")
                session.page.locator(SELECTORS["return_reason"]).select_option(label=reason)
                session.human_pause(0.4, 0.9)

                # Refund method — default to source; also configurable.
                if session.page.locator(SELECTORS["refund_method_upi"]).count() > 0:
                    session.human_click(SELECTORS["refund_method_upi"])

                session.human_click(SELECTORS["confirm_return"])
                session.human_pause(1.5, 2.8)
                self._check_challenge(session)

                return_id = self._extract(session, SELECTORS["return_id_text"])
                refund_raw = self._extract(session, SELECTORS["refund_amount_text"])
                refund_amount = _parse_amount(refund_raw) if refund_raw else None

                if not return_id:
                    # Confirmation screen didn't load as expected.
                    yield Result(
                        row_id=task.row_id, sku=task.sku,
                        return_status="Failed",
                        task_status=Status.NEEDS_REVIEW,
                        error="No return ID captured; UI may have changed",
                    )
                    continue

                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Placed",
                    return_id=return_id,
                    refund_amount=refund_amount,
                    task_status=Status.DONE,
                )

            except OutOfWindowError as e:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Out of window",
                    task_status=Status.NEEDS_REVIEW,
                    error=str(e),
                )
            except HumanReviewNeeded:
                # Bubble up — runner flags every remaining SKU on this order
                # and stops hitting the challenge screen.
                raise
            except PWTimeout as e:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error=f"Timeout: {e}",
                )
            except Exception as e:  # noqa: BLE001 - deliberate catch-all per SKU
                # Never let one SKU take out the whole order.
                log.exception("Unexpected error on SKU %s", task.sku)
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error=f"{type(e).__name__}: {e}",
                )

    # ---------- helpers ----------

    def _find_item_row(self, session, sku: str):
        """Return the locator for the order-page row matching this SKU."""
        rows = session.page.locator(SELECTORS["order_row"])
        for i in range(rows.count()):
            row = rows.nth(i)
            if sku.lower() in (row.inner_text() or "").lower():
                return row
        return None

    def _extract(self, session, selector: str) -> str | None:
        loc = session.page.locator(selector)
        if loc.count() == 0:
            return None
        text = loc.first.inner_text()
        # Selectors above embed a capture group in the text= regex; pull it out.
        m = re.search(r"([A-Z0-9-]{4,}|₹\s?[0-9,]+)", text)
        return m.group(1) if m else text

    def _check_challenge(self, session) -> None:
        """Detect CAPTCHA / verification screens and bail cleanly."""
        if session.page.locator(SELECTORS["captcha_hint"]).count() > 0:
            raise HumanReviewNeeded("CAPTCHA / verification challenge detected")


def _parse_amount(raw: str) -> float | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d.]", "", raw)
    return float(digits) if digits else None

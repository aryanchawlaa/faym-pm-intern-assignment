"""
Amazon return adapter.

Amazon exposes both flows depending on the order:
  - BATCH:      the "Return or replace items" page shows a checkbox
                list of all eligible SKUs → we tick all our targets
                and go through one shared reason/refund flow.
  - SEQUENTIAL: some orders (esp. digital, third-party sellers, or
                orders where only one SKU is eligible) drop straight
                into a per-item return flow → we loop.

detect_return_model() reads the actual return page and decides.
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

log = logging.getLogger("amazon")

SELECTORS = {
    "signin_email":      "input#ap_email",
    "signin_continue":   "input#continue",
    "signin_password":   "input#ap_password",
    "signin_submit":     "input#signInSubmit",
    "captcha_hint":      "text=/enter the characters you see|solve this puzzle|robot check/i",
    "otp_hint":          "text=/two.?step verification|enter otp/i",
    "order_row":         "div.order-card",
    "return_or_replace": "a:has-text('Return or replace items')",
    "item_checkbox":     "input[type='checkbox'][name^='selectedItem']",
    "item_container":    "div.a-box-group:has(input[type='checkbox'])",
    "reason_dropdown":   "select[name^='reasonDropDown']",
    "continue_btn":      "input[data-testid='continue-button'], input[aria-labelledby*='continue']",
    "refund_method":     "input[name='refundMethod'][value='ORIGINAL']",
    "submit_return":     "input[data-testid='submit-return']",
    "return_confirm":    "text=/Return request received|Your return is being processed/i",
    "return_id_text":    "text=/Return authorization[:\\s]+([A-Z0-9-]+)/i",
    "refund_amount_text":"text=/Refund total[:\\s]+\\$([0-9,.]+)/i",
    "out_of_window_msg": "text=/no longer eligible for return|return window has passed/i",
}

AMAZON_LOGIN_URL   = "https://www.amazon.in/ap/signin"
AMAZON_ORDERS_URL  = "https://www.amazon.in/gp/your-account/order-history"
AMAZON_RETURN_URL  = "https://www.amazon.in/gp/orc/returns/homepage.html?orderId={order_id}"


class AmazonAdapter(PlatformAdapter):
    name = "amazon"

    # ---------- login ----------

    def login(self, session) -> None:
        session.goto(AMAZON_ORDERS_URL)
        if "signin" not in session.page.url and "ap/signin" not in session.page.url:
            log.info("Amazon: reusing existing session")
            return

        email = os.environ.get("FAYM_AMAZON_EMAIL")
        password = os.environ.get("FAYM_AMAZON_PASSWORD")
        if not (email and password):
            raise PlatformError(
                "Amazon credentials missing. Set FAYM_AMAZON_EMAIL and "
                "FAYM_AMAZON_PASSWORD env vars."
            )
        session.human_type(SELECTORS["signin_email"], email)
        session.human_click(SELECTORS["signin_continue"])
        session.human_pause()
        session.human_type(SELECTORS["signin_password"], password)
        session.human_click(SELECTORS["signin_submit"])
        session.human_pause(1.5, 2.5)
        self._check_challenge(session)
        log.info("Amazon login OK")

    # ---------- detect ----------

    def detect_return_model(self, session, order_id: str) -> ReturnModel:
        session.goto(AMAZON_RETURN_URL.format(order_id=order_id))
        session.human_pause()
        self._check_challenge(session)
        checkbox_count = session.page.locator(SELECTORS["item_checkbox"]).count()
        log.debug("Amazon order %s: found %d item checkboxes",
                  order_id, checkbox_count)
        if checkbox_count >= 2:
            return ReturnModel.BATCH
        return ReturnModel.SEQUENTIAL

    # ---------- execute ----------

    def execute(self, session, order_id, tasks, model) -> Iterator:
        if model == ReturnModel.BATCH:
            yield from self._execute_batch(session, order_id, tasks)
        else:
            for task in tasks:
                yield from self._execute_sequential_single(session, order_id, task)

    # ---------- batch flow ----------

    def _execute_batch(self, session, order_id, tasks):
        from excel_io import Result, Status
        session.goto(AMAZON_RETURN_URL.format(order_id=order_id))
        self._check_challenge(session)

        # Tick the checkbox next to each SKU we've been asked to return.
        selected: list = []
        skipped: list[tuple] = []  # (task, reason)
        for task in tasks:
            container = self._find_item_container(session, task.sku)
            if container is None:
                skipped.append((task, "SKU not found on return page"))
                continue
            if container.locator(SELECTORS["out_of_window_msg"]).count() > 0:
                skipped.append((task, "Out of window"))
                continue
            cb = container.locator(SELECTORS["item_checkbox"]).first
            if not cb.is_checked():
                cb.check()
                session.human_pause(0.2, 0.5)
                # Reason dropdown appears per item in Amazon's batch UI.
                reason = os.environ.get("FAYM_DEFAULT_REASON", "No longer needed")
                dd = container.locator(SELECTORS["reason_dropdown"]).first
                if dd.count() > 0:
                    dd.select_option(label=reason)
            selected.append(task)

        # Yield per-item results for the ones we couldn't include.
        for task, reason in skipped:
            yield Result(
                row_id=task.row_id, sku=task.sku,
                return_status="Out of window" if "window" in reason.lower() else "Failed",
                task_status=Status.NEEDS_REVIEW,
                error=reason,
            )

        if not selected:
            return  # every item skipped; nothing to submit

        # One shared submit for every ticked item.
        try:
            session.human_click(SELECTORS["continue_btn"])
            session.human_pause(1, 2)
            if session.page.locator(SELECTORS["refund_method"]).count() > 0:
                session.human_click(SELECTORS["refund_method"])
            session.human_click(SELECTORS["submit_return"])
            session.human_pause(2, 3.5)
            self._check_challenge(session)
        except PWTimeout as e:
            for task in selected:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error=f"Batch submit timeout: {e}",
                )
            return

        # Amazon's confirmation page lists each item + its own return
        # authorization ID. We match back to each SKU.
        for task in selected:
            return_id, refund = self._extract_per_sku(session, task.sku)
            if return_id:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Placed",
                    return_id=return_id,
                    refund_amount=refund,
                    task_status=Status.DONE,
                )
            else:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error="Batch confirmation reached but no return ID captured",
                )

    # ---------- sequential per-item ----------

    def _execute_sequential_single(self, session, order_id, task):
        from excel_io import Result, Status
        try:
            session.goto(AMAZON_RETURN_URL.format(order_id=order_id))
            self._check_challenge(session)
            container = self._find_item_container(session, task.sku)
            if container is None:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error=f"SKU {task.sku!r} not found",
                )
                return
            if container.locator(SELECTORS["out_of_window_msg"]).count() > 0:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Out of window",
                    task_status=Status.NEEDS_REVIEW,
                    error="Return window closed",
                )
                return

            container.locator(SELECTORS["item_checkbox"]).first.check()
            session.human_pause(0.3, 0.7)
            reason = os.environ.get("FAYM_DEFAULT_REASON", "No longer needed")
            dd = container.locator(SELECTORS["reason_dropdown"]).first
            if dd.count() > 0:
                dd.select_option(label=reason)

            session.human_click(SELECTORS["continue_btn"])
            session.human_pause(1, 2)
            if session.page.locator(SELECTORS["refund_method"]).count() > 0:
                session.human_click(SELECTORS["refund_method"])
            session.human_click(SELECTORS["submit_return"])
            session.human_pause(2, 3.5)
            self._check_challenge(session)

            return_id, refund = self._extract_per_sku(session, task.sku)
            if not return_id:
                yield Result(
                    row_id=task.row_id, sku=task.sku,
                    return_status="Failed",
                    task_status=Status.NEEDS_REVIEW,
                    error="No return ID captured on confirmation page",
                )
                return

            yield Result(
                row_id=task.row_id, sku=task.sku,
                return_status="Placed",
                return_id=return_id,
                refund_amount=refund,
                task_status=Status.DONE,
            )
        except HumanReviewNeeded:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Amazon sequential failure on %s", task.sku)
            yield Result(
                row_id=task.row_id, sku=task.sku,
                return_status="Failed",
                task_status=Status.NEEDS_REVIEW,
                error=f"{type(e).__name__}: {e}",
            )

    # ---------- helpers ----------

    def _find_item_container(self, session, sku: str):
        containers = session.page.locator(SELECTORS["item_container"])
        for i in range(containers.count()):
            c = containers.nth(i)
            if sku.lower() in (c.inner_text() or "").lower():
                return c
        return None

    def _extract_per_sku(self, session, sku: str):
        # Very tolerant extractor — Amazon's confirmation markup varies.
        text = session.page.locator("body").inner_text()
        return_id = None
        refund = None
        # find a chunk of text near the SKU and pull IDs from it
        idx = text.lower().find(sku.lower())
        window = text[max(0, idx - 200): idx + 400] if idx != -1 else text
        m_id = re.search(r"Return authorization[:\s]+([A-Z0-9-]{6,})", window, re.I)
        if m_id:
            return_id = m_id.group(1)
        m_amt = re.search(r"Refund total[:\s]+[₹$]?\s?([0-9][0-9,]*\.?\d*)", window, re.I)
        if m_amt:
            refund = float(m_amt.group(1).replace(",", ""))
        return return_id, refund

    def _check_challenge(self, session) -> None:
        if session.page.locator(SELECTORS["captcha_hint"]).count() > 0:
            raise HumanReviewNeeded("Amazon CAPTCHA / robot check")
        if session.page.locator(SELECTORS["otp_hint"]).count() > 0:
            raise HumanReviewNeeded("Amazon two-step verification")

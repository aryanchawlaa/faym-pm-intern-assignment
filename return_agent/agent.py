"""
Faym.co Return Automation Agent — main runner.

End-to-end flow:
    1. Load pending return tasks from Excel (openpyxl).
    2. Group tasks by (platform, order_id).
    3. For each order, dispatch to the right platform adapter.
    4. Adapter auto-detects Batch vs Sequential return model.
    5. Adapter executes returns and yields a Result per line item.
    6. Runner writes each Result back to Excel immediately (never batched
       at the end — a crash mid-run must never lose progress).
    7. Order is only rolled up to fully Done when every one of its line
       items has a terminal state.

Run:
    pip install -r requirements.txt
    playwright install chromium
    python agent.py --excel returns_queue.xlsx --platform flipkart

Design notes:
    - Adapters are pluggable (platforms/base.py); adding a new platform
      = one new file, zero core changes.
    - Excel is the source of truth. No external DB in v1.
    - CAPTCHA / OTP / unexpected verification → flag for human review;
      never blindly retry against a challenge screen (that itself looks
      like bot behaviour).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime

from excel_io import ExcelQueue, TaskRow, Result, Status
from browser import BrowserSession
from platforms import get_adapter, PlatformError, OutOfWindowError, HumanReviewNeeded

log = logging.getLogger("agent")


def process_order(adapter, session, order_id: str, tasks: list[TaskRow], queue: ExcelQueue) -> None:
    """Run every line item for one order through the adapter, writing back per-item."""
    log.info("Order %s: %d line item(s), platform=%s",
             order_id, len(tasks), tasks[0].platform)

    # Detect return model once per order (this determines whether we can
    # do one batch flow or must loop the micro-flow per SKU).
    model = adapter.detect_return_model(session, order_id)
    log.info("Order %s: return_model=%s", order_id, model)

    try:
        # Adapter yields one Result per line item, in real time.
        for result in adapter.execute(session, order_id, tasks, model):
            log.info("  → SKU=%s status=%s return_id=%s refund=%s",
                     result.sku, result.return_status, result.return_id, result.refund_amount)
            # Immediate write-back — never batched.
            queue.write_result(result, return_model=model)

    except HumanReviewNeeded as e:
        # e.g. CAPTCHA / OTP / unexpected verification screen.
        # Flag every unprocessed item in this order for human review,
        # do NOT retry — repeated retries against a challenge screen is
        # itself a strong bot signal (§8 of PRD).
        log.warning("Order %s hit human-review gate: %s", order_id, e)
        for t in tasks:
            if not queue.is_terminal(t):
                queue.write_result(
                    Result(
                        row_id=t.row_id, sku=t.sku,
                        return_status="Failed", refund_amount=None, return_id=None,
                        task_status=Status.NEEDS_REVIEW,
                        error=f"Human review: {e}",
                    ),
                    return_model=model,
                )

    except PlatformError as e:
        log.exception("Order %s failed hard: %s", order_id, e)
        for t in tasks:
            if not queue.is_terminal(t):
                queue.write_result(
                    Result(
                        row_id=t.row_id, sku=t.sku,
                        return_status="Failed", refund_amount=None, return_id=None,
                        task_status=Status.NEEDS_REVIEW,
                        error=str(e),
                    ),
                    return_model=model,
                )


def run(excel_path: str, platform_filter: str | None, headless: bool) -> None:
    queue = ExcelQueue(excel_path)
    pending = queue.load_pending()
    log.info("Loaded %d pending line item(s) from %s", len(pending), excel_path)

    if platform_filter:
        pending = [t for t in pending if t.platform.lower() == platform_filter.lower()]
        log.info("Filtered to %d task(s) on %s", len(pending), platform_filter)

    # Group by (platform, order_id) so a batch-eligible order can be closed
    # out in one flow, and adjacent line items on the same order aren't
    # spread across separate browser sessions.
    grouped: dict[tuple[str, str], list[TaskRow]] = defaultdict(list)
    for t in pending:
        grouped[(t.platform, t.order_id)].append(t)

    # One browser session per platform (persistent profile → looks like a
    # real returning user, not a fresh anonymous client).
    sessions: dict[str, BrowserSession] = {}
    try:
        for (platform, order_id), tasks in grouped.items():
            adapter = get_adapter(platform)
            if platform not in sessions:
                sessions[platform] = BrowserSession(platform=platform, headless=headless)
                sessions[platform].login(adapter)
            process_order(adapter, sessions[platform], order_id, tasks, queue)
    finally:
        for s in sessions.values():
            s.close()
        queue.save()
        log.info("Done. Results written to %s", excel_path)


def main() -> int:
    p = argparse.ArgumentParser(description="Faym returns automation agent")
    p.add_argument("--excel", required=True, help="Path to returns queue .xlsx")
    p.add_argument("--platform", default=None,
                   help="Optional filter: only run tasks on this platform")
    p.add_argument("--headless", action="store_true",
                   help="Run browser headless (NOT recommended — increases bot-detection risk)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Agent starting at %s", datetime.now().isoformat(timespec="seconds"))
    run(args.excel, args.platform, args.headless)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Faym Return-Automation Agent

Browser agent that reads pending return tasks from Excel, executes the
correct return flow per platform (Amazon or Flipkart), and writes the
outcome back per line item — line-item-level, partial-success-safe,
crash-safe.

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
# Full run
python agent.py --excel returns_queue.xlsx

# Only Flipkart tasks
python agent.py --excel returns_queue.xlsx --platform flipkart

# Verbose logging
python agent.py --excel returns_queue.xlsx -v
```

Credentials (set before running):

```bash
export FAYM_FLIPKART_PHONE=9205359199        # brief's test account
export FAYM_AMAZON_EMAIL=you@example.com
export FAYM_AMAZON_PASSWORD=...
export FAYM_OTP=123456                       # optional; else agent prompts
export FAYM_DEFAULT_REASON="Item not as described"
```

## Excel schema

One row per line item (SKU) — never one row per order. See
`returns_queue_template.xlsx` for a blank template.

| Column | Written by | Notes |
|---|---|---|
| Platform | Input | Amazon / Flipkart |
| Order ID | Input | Locates the parent order |
| Product / SKU | Input | Identifies the line item |
| Return window | Input | Verified before acting |
| Return ID | Agent | Captured from the platform |
| Return status | Agent | Placed / Failed / Out of window |
| Refund amount | Agent | As shown by the platform |
| Task status | Agent | Pending / Done / Needs human review |
| Timestamp | Agent | ISO-8601 UTC of the run |
| Attempt count | Agent | Retries so far |
| Return model used | Agent | Batch / Sequential — for audit |
| Error / log | Agent | Reason if failed / flagged |

## Architecture

```
agent.py                # main runner: reads Excel, groups by order, dispatches
browser.py              # Playwright session + stealth patches + human pacing
excel_io.py             # openpyxl-based per-row write-back
platforms/
  base.py               # abstract PlatformAdapter contract
  flipkart.py           # sequential-only; OTP-driven login
  amazon.py             # batch OR sequential — auto-detected per order
```

**Adding a new platform** = one new file in `platforms/` + one entry in
`platforms/__init__.py`. The runner is platform-agnostic.

## Design decisions worth calling out

- **Per-row write-back (never batched).** Every completed line item is
  flushed to the .xlsx immediately. If the process dies mid-run,
  everything already done survives.
- **Persistent browser profile per platform.** Cookies + localStorage +
  fingerprint carry across runs → looks like a returning user, not a
  fresh anonymous device every time.
- **Stealth patches applied on every new document** (`STEALTH_JS` in
  `browser.py`). Masks the obvious Playwright fingerprints
  (`navigator.webdriver`, empty plugins, etc). Not a substitute for a
  full stealth suite at scale — see PRD §8.
- **Human-scale pacing.** No fixed `time.sleep(1)`; delays are
  uniform-random in a small range, clicks include hover + jitter.
- **CAPTCHA / OTP / verification screens → flag, don't retry.** Retrying
  against a challenge screen is itself a bot signal.
- **Order dispatch is grouped by (platform, order_id)** so batch-eligible
  orders close out in one flow, and adjacent SKUs on the same order
  aren't fragmented across separate browser sessions.
- **Adapter yields `Result` per SKU, not returns a list.** The runner
  writes each Result immediately, so partial-success handling comes
  from the control flow, not from a special-case branch.

## Testing / smoke check

The brief provided a Flipkart test account. To smoke-test end-to-end:

```bash
# 1. Put one row in returns_queue_template.xlsx with a real test order.
# 2. Run non-headless so you can see what happens.
python agent.py --excel returns_queue_template.xlsx --platform flipkart
```

Nightly, run `agent.py --platform flipkart` against a known
already-returned test order and assert the "Out of window" branch fires
— this catches selector drift before it breaks production runs.

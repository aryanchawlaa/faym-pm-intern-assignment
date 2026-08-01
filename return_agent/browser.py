"""
Browser session with anti-bot-detection hardening.

Playwright's default Chromium leaks obvious automation signals (navigator.
webdriver=true, headless UA, empty plugins array, mismatched permissions,
etc). This module patches the worst offenders on every new page and
provides a persistent, per-platform user-data profile so cookies /
localStorage / device fingerprint survive across runs — a returning user
looks very different from an anonymous session every time.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

log = logging.getLogger("browser")

# Realistic desktop UA (updated periodically; do NOT ship a stale one).
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# JS shim run on every new document. Patches the well-known Playwright /
# Puppeteer fingerprint leaks.  This is intentionally minimal — a full
# stealth suite (playwright-stealth, undetected-chromedriver, etc.) is a
# better fit at scale, but that's an ops decision, not agent logic.
STEALTH_JS = r"""
() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  Object.defineProperty(navigator, 'plugins',  { get: () => [1,2,3,4,5] });
  Object.defineProperty(navigator, 'languages',{ get: () => ['en-IN','en-US','en'] });
  window.chrome = window.chrome || { runtime: {} };
  const origQuery = navigator.permissions && navigator.permissions.query;
  if (origQuery) {
    navigator.permissions.query = (p) =>
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(p);
  }
}
"""


class BrowserSession:
    """Wraps a Playwright persistent context. One session per platform."""

    def __init__(self, platform: str, headless: bool = False,
                 profile_root: str = ".browser_profiles"):
        self.platform = platform
        self.headless = headless
        self.profile_dir = Path(profile_root) / platform
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        # Persistent context = cookies + localStorage + fingerprint survive
        # across runs. Critical for avoiding "fresh anonymous device" flags.
        self.ctx: BrowserContext = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=headless,
            viewport={"width": 1366, "height": 768},
            user_agent=DEFAULT_UA,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-default-browser-check",
            ],
        )
        self.ctx.add_init_script(STEALTH_JS)
        self.page: Page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        log.info("Browser session ready: platform=%s headless=%s profile=%s",
                 platform, headless, self.profile_dir)

    # ---------- pacing helpers (used by adapters) ----------

    def human_pause(self, lo: float = 0.6, hi: float = 1.8) -> None:
        """Sleep for a human-scale, non-uniform delay between actions.

        Fixed sleeps (e.g. time.sleep(1)) are a strong bot signal on their
        own — real users' inter-action intervals are noisy."""
        time.sleep(random.uniform(lo, hi))

    def human_click(self, selector: str, timeout: int = 15_000) -> None:
        """Click after a short scroll-into-view + tiny mouse-jitter, not
        a teleport to (x,y)."""
        loc = self.page.locator(selector).first
        loc.wait_for(state="visible", timeout=timeout)
        loc.scroll_into_view_if_needed()
        self.human_pause(0.15, 0.5)
        loc.hover()
        self.human_pause(0.1, 0.35)
        loc.click()

    def human_type(self, selector: str, text: str) -> None:
        loc = self.page.locator(selector).first
        loc.wait_for(state="visible")
        loc.click()
        # Modern Playwright API (press_sequentially replaces the
        # deprecated Locator.type). Vary per-char delay — real typing
        # isn't uniform.
        loc.press_sequentially(text, delay=random.randint(35, 140))

    def goto(self, url: str) -> None:
        log.debug("goto %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.human_pause()

    # ---------- lifecycle ----------

    def login(self, adapter) -> None:
        """Delegated to the platform adapter, which knows the auth flow."""
        adapter.login(self)

    def close(self) -> None:
        try:
            self.ctx.close()
        finally:
            self._pw.stop()


def request_otp_from_human(phone: str) -> str:
    """
    OTP-driven logins (Flipkart's test account: request OTP by calling
    9205359199) must be supervised. The agent asks for the code via
    stdin — in production this becomes a Slack DM or a webhook that
    ops fills in. We deliberately do NOT try to intercept SMS.
    """
    log.warning("OTP required for %s. Waiting for human to supply it.", phone)
    # In production: post to Slack, block on a webhook, timeout after N min.
    otp = os.environ.get("FAYM_OTP") or input(f"OTP for {phone}: ").strip()
    if not otp:
        raise RuntimeError("No OTP supplied — cannot continue login.")
    return otp

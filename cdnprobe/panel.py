"""Driving the ilook.tv account panel through Playwright.

The password is read from the environment and never leaves the process: it
is not printed, not written to snapshots, and never passed as an argument.

The session is cached on disk and reused. The site sits behind Cloudflare
and repeated automated logins draw a challenge, so a long run must log in
once rather than twenty times.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from playwright.sync_api import Page, TimeoutError as PwTimeout, sync_playwright

from . import config
from .api import SetCdnResult, parse_set_cdn
from .parsing import find_playlist_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class CdnOption:
    value: str
    label: str


class Panel:
    """A logged-in session. Use as a context manager."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self._last_failure = ""
        self.page: Page | None = None

    def __enter__(self) -> "Panel":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            storage_state=(
                str(config.STATE_FILE) if config.STATE_FILE.exists() else None
            ),
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(45_000)
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            if closer:
                try:
                    closer.close()
                except Exception:
                    pass
        if self._pw:
            self._pw.stop()

    # --- session ----------------------------------------------------------

    def save_state(self) -> None:
        if self._context:
            self._context.storage_state(path=str(config.STATE_FILE))

    def ensure_logged_in(self) -> bool:
        """Opens settings, logging in only if the cached session is dead."""
        if self._open_settings_if_authorised():
            return False
        self.login()
        if not self._open_settings_if_authorised():
            raise SystemExit(f"Logged in but settings never opened: {self._last_failure}")
        return True

    def open_settings(self) -> None:
        """Opens settings, logging in again if needed.

        A full run lasts hours and the session does not; the redirect to the
        login page has to be recovered from here rather than crashing.
        """
        if self._open_settings_if_authorised():
            return
        self.login()
        if not self._open_settings_if_authorised():
            raise SystemExit(f"Cannot open settings: {self._last_failure}")

    def _open_settings_if_authorised(self, attempts: int = 3) -> bool:
        """Right after a login the site bounces to /cabinet for a few seconds,
        so one attempt is not enough."""
        for attempt in range(1, attempts + 1):
            if self._try_open_settings():
                return True
            if attempt < attempts:
                assert self.page is not None
                self.page.wait_for_timeout(4_000)
        return False

    def _try_open_settings(self) -> bool:
        page = self.page
        assert page is not None
        try:
            page.goto(config.SETTINGS_URL, wait_until="domcontentloaded", timeout=45_000)
        except PwTimeout:
            self._last_failure = "timed out opening the settings page"
            return False
        self._settle_cloudflare()
        if "/auth/" in page.url:
            self._last_failure = f"redirected to login: {page.url}"
            return False
        try:
            page.wait_for_selector("select[name=cdn]", state="attached", timeout=20_000)
        except PwTimeout:
            self._last_failure = f"no select[name=cdn]; url={page.url}"
            return False
        return True

    def login(self) -> None:
        email, password = config.require_credentials()
        page = self.page
        assert page is not None
        page.goto(config.LOGIN_URL, wait_until="domcontentloaded")
        self._settle_cloudflare()
        page.get_by_role("textbox", name="email").fill(email)
        page.get_by_role("textbox", name="пароль").fill(password)
        page.get_by_role("button", name="OK").click()

        # networkidle never fires: the support chat widget holds a connection
        # open. Wait for the URL to leave the login page instead, tolerating
        # Cloudflare's interstitial redirect.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            page.wait_for_timeout(1000)
            if "__cf_chl" in page.url:
                continue
            if "/auth/login" not in page.url:
                self.save_state()
                return
        raise SystemExit(
            "Login failed: Cloudflare did not let us through. Run with "
            "HEADLESS=0 and solve the challenge once - the session is cached."
        )

    def _settle_cloudflare(self) -> None:
        page = self.page
        assert page is not None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and "__cf_chl" in page.url:
            page.wait_for_timeout(1000)

    # --- account data -----------------------------------------------------

    def playlist_url(self) -> str:
        """Reads the personal playlist link from the download page.

        Discovering it beats configuring it: the link carries a token that
        the user may rotate, and the container should not need editing then.
        """
        page = self.page
        assert page is not None
        page.goto(config.DOWNLOAD_URL, wait_until="domcontentloaded")
        self._settle_cloudflare()
        page.wait_for_timeout(1500)
        url = find_playlist_url(page.evaluate("() => document.body.innerText"))
        if not url:
            url = find_playlist_url(page.content())
        if not url:
            raise SystemExit(f"No playlist link found on {config.DOWNLOAD_URL}")
        return url

    def _require_settings_page(self) -> None:
        """Fails loudly if the settings select is not on the current page.

        Reading it blind gives a bare "null has no options" from inside the
        browser, which says nothing about the actual mistake: having navigated
        elsewhere and never come back.
        """
        page = self.page
        assert page is not None
        if not page.evaluate(
            "() => !!document.querySelector('select[name=cdn]')"
        ):
            raise RuntimeError(
                f"the CDN select is not on {page.url} - call open_settings() "
                f"before reading or changing the CDN"
            )

    def cdn_options(self) -> list[CdnOption]:
        page = self.page
        assert page is not None
        self._require_settings_page()
        raw = page.evaluate(
            """() => [...document.querySelectorAll('select[name=cdn] option')]
                 .map(o => [o.value, o.text.trim()])"""
        )
        return [CdnOption(value=v, label=t) for v, t in raw]

    def current_cdn(self) -> CdnOption:
        page = self.page
        assert page is not None
        self._require_settings_page()
        value, label = page.evaluate(
            """() => { const s = document.querySelector('select[name=cdn]');
                       const o = s.options[s.selectedIndex];
                       return [o.value, o.text.trim()]; }"""
        )
        return CdnOption(value=value, label=label)

    def set_cdn(self, value: str) -> SetCdnResult:
        """Changes the CDN through the request the SAVE button sends.

        We call the API instead of clicking: a refusal is invisible in the
        UI - the page stays silent and the setting simply does not change -
        whereas the response carries both the status and the cooldown left.
        """
        # The single place that changes a live setting, so the single place
        # worth guarding. A passive copy measures an account someone else is
        # steering; one stray call from a future code path would have it
        # fighting the active copy, invisibly and for hours.
        if config.OBSERVE_ONLY:
            raise RuntimeError(
                "OBSERVE_ONLY is set: this copy measures the account, it never "
                "changes it"
            )
        page = self.page
        assert page is not None
        # Reload first: over a long run the document goes stale and a fetch
        # issued from it may never return.
        self.open_settings()
        raw = page.evaluate(
            """async (cdnId) => {
              // page.evaluate has no timeout on the Playwright side, so a
              // stalled fetch would hang the whole run. Abort it here.
              const controller = new AbortController();
              const timer = setTimeout(() => controller.abort(), 20000);
              try {
                const response = await fetch('/ajax/set_cdn', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                  },
                  body: 'cdn_id=' + encodeURIComponent(cdnId),
                  credentials: 'same-origin',
                  signal: controller.signal,
                });
                return await response.text();
              } catch (error) {
                return JSON.stringify({
                  state: 'error',
                  message: 'request failed: ' + error.name,
                  cur_cdn: '',
                });
              } finally {
                clearTimeout(timer);
              }
            }""",
            str(value),
        )
        result = parse_set_cdn(raw)
        if not result.accepted:
            return result
        self.open_settings()
        return replace(result, stored=self.current_cdn().value)

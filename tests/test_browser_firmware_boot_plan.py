"""Isolated headless browser checks for firmware-bank boot consequences.

No real ONU, credentials, firmware operations or WAN requests are used.
The actual shipped JavaScript is loaded into a synthetic document.
"""
import os
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "overlay/www/luci-static/resources/view/8311.js"
JQUERY = Path("/usr/share/javascript/jquery/jquery.min.js")
HOST = "http://aott.test"
URL = HOST + "/firmware-fixture"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def chrome_binary():
    return next(
        (shutil.which(name) for name in
         ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
         if shutil.which(name)), None,
    )


def bank(valid=True, receipt="complete"):
    return {"valid": valid, "receipt": receipt, "components": {}}


def state(active="B", committed="B", pending=None, trial=False):
    snapshot = {"schema": 1, "boot_contract": True, "active": active,
                "committed": committed, "pending": pending,
                "running_trial": trial, "banks": {"A": bank(), "B": bank()}}
    # Test-only checksum over synthetic data. Real firmware derives a
    # lock-bound fingerprint from its exact native bankctl status output.
    snapshot["state_guard"] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return snapshot


class RealFirmwareBankBootPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        strict = os.environ.get("AOTT_REQUIRE_BROWSER") == "1"
        missing = []
        chrome = chrome_binary()
        if sync_playwright is None:
            missing.append("Python Playwright")
        if chrome is None:
            missing.append("Chrome/Chromium executable")
        if not JQUERY.is_file():
            missing.append("system libjs-jquery")
        if missing:
            why = "Browser dependencies unavailable: " + ", ".join(missing)
            if strict:
                raise AssertionError(why)
            raise unittest.SkipTest(why)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-background-networking",
                  "--disable-extensions", "--disable-component-update",
                  "--no-first-run"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "playwright", None):
            cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 1024, "height": 768},
            service_workers="block", accept_downloads=False)
        self.page = self.context.new_page()
        self.unexpected = []
        self.page.route("**/*", self.route)
        self.page.goto(URL, wait_until="load", timeout=15000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function("typeof updateBankState === 'function'")
        # Insert the mock firmware panel only after the full shipped script's
        # document-ready handler has run. No automatic device requests occur.
        self.page.wait_for_timeout(40)
        self.page.evaluate("""() => {
            const panel = document.createElement('section');
            panel.innerHTML = [
              '<span id="bank-active"></span>',
              '<span id="bank-committed"></span>',
              '<span id="bank-pending"></span>',
              '<span id="bank-contract"></span>',
              '<span id="bank-next-reboot"></span>',
              '<span id="bank-recovery"></span>',
              '<span id="bank-explanation"></span>',
              '<p id="bank-state-freshness"></p>',
              '<p id="firmware-message"></p>',
              '<p id="bank-install-impact"></p>',
              '<table id="upload-table"><tbody><tr><td>',
              '<input name="upload-selection" type="radio" value="synthetic-upload" data-sha256="synthetic-hash" checked>',
              '</td></tr></tbody></table>',
              '<p id="upload-empty"></p>',
              '<button id="firmware-upload-btn"></button>',
              '<button class="firmware-artifact" data-action="install" data-confirm="Overwrite inactive bank?">Install</button>',
              '<button class="firmware-artifact" data-action="validate">Validate</button>',
              '<button class="firmware-artifact" data-action="discard_upload">Discard</button>',
              '<pre id="bank-receipts"></pre>',
              '<span id="receipt-A"></span><span id="receipt-B"></span>',
              '<span id="valid-A"></span><span id="valid-B"></span>',
              '<button class="firmware-bank" data-action="trial" data-bank="A">Trial A</button>',
              '<button class="firmware-bank" data-action="trial" data-bank="B">Trial B</button>',
              '<button class="firmware-bank" data-action="commit">Commit</button>',
              '<button class="firmware-bank" data-action="reboot" data-confirm="Confirm reboot?">Reboot</button>',
              '<button class="firmware-bank" data-action="cancel_trial">Cancel</button>',
              '<button class="firmware-bank" data-action="return_saved">Return</button>'
            ].join('');
            document.body.appendChild(panel);
        }""")

    def tearDown(self):
        self.context.close()

    def route(self, route):
        u = route.request.url
        if u == URL:
            return route.fulfill(
                status=200, content_type="text/html",
                body="<html><head></head><body></body></html>")
        self.unexpected.append(urlsplit(u).path)
        return route.abort()

    def render(self, snapshot):
        self.page.evaluate("(s) => updateBankState(s)", snapshot)
        return {key: self.page.locator("#" + key).inner_text() for key in
                ("bank-next-reboot", "bank-recovery", "bank-explanation")}

    def enabled(self, action, bank=None):
        selector = '[data-action="' + action + '"]'
        if bank:
            selector += '[data-bank="' + bank + '"]'
        return not self.page.locator(selector).is_disabled()

    def test_committed_v2r5_reboots_into_same_bank(self):
        r = self.render(state())
        self.assertIn("Bank B (committed)", r["bank-next-reboot"])
        self.assertIn("Bank B (committed)", r["bank-recovery"])
        self.assertIn("No one-time trial", r["bank-explanation"])
        self.assertFalse(self.enabled("commit"))
        self.assertTrue(self.enabled("trial", "A"))
        self.assertFalse(self.enabled("trial", "B"))
        self.assertTrue(self.enabled("reboot"))
        self.assertEqual(self.unexpected, [])

    def test_pending_one_shot_b_preserves_a_as_saved(self):
        r = self.render(state(active="A", committed="A", pending="B"))
        self.assertIn("Bank B (one-time boot)", r["bank-next-reboot"])
        self.assertIn("Bank A (saved)", r["bank-recovery"])
        self.assertIn("further reset", r["bank-explanation"])
        self.assertFalse(self.enabled("commit"))
        self.assertFalse(self.enabled("trial", "B"))
        self.assertTrue(self.enabled("cancel_trial"))
        self.assertEqual(self.unexpected, [])

    def test_running_trial_b_reboot_would_return_to_a(self):
        r = self.render(state(active="B", committed="A", trial=True))
        self.assertEqual(r["bank-next-reboot"], "Bank A (saved)")
        self.assertEqual(r["bank-recovery"], "Bank A (saved)")
        self.assertIn("uncommitted trial", r["bank-explanation"])
        self.assertTrue(self.enabled("commit"))
        self.assertFalse(self.enabled("trial", "A"))
        self.assertTrue(self.enabled("return_saved"))
        self.assertEqual(self.unexpected, [])

    def test_conflicting_selector_combinations_fail_closed(self):
        for bad in (
            state(active="A", committed="A", pending="A"),
            state(active="A", committed="B", pending="B", trial=False),
            state(active="B", committed="A", pending="B", trial=True),
            state(active="A", committed="A", trial=True),
        ):
            with self.subTest(bad=bad):
                r = self.render(bad)
                self.assertEqual(r["bank-recovery"], "Unverified")
                self.assertIn("Unknown", r["bank-next-reboot"])
                self.assertTrue(all(
                    self.page.locator(".firmware-bank").evaluate_all(
                        "(els) => els.every(el => el.disabled)") for _ in range(1)))
        self.assertEqual(self.unexpected, [])

    def test_missing_bank_data_locks_actions(self):
        bad = state()
        del bad["banks"]["B"]
        r = self.render(bad)
        self.assertIn("not verified", r["bank-explanation"])
        self.assertFalse(self.enabled("reboot"))
        self.assertFalse(self.enabled("commit"))
        self.assertEqual(self.page.locator("#bank-active").inner_text(), "unknown")
        self.assertEqual(self.unexpected, [])

    def test_invalid_pending_target_locks_actions(self):
        bad = state(active="A", committed="A", pending="B")
        bad["banks"]["B"] = bank(False, "incomplete")
        r = self.render(bad)
        self.assertIn("Unknown", r["bank-next-reboot"])
        self.assertFalse(self.enabled("reboot"))
        self.assertEqual(self.unexpected, [])

    def test_malicious_pending_text_never_becomes_dom_markup(self):
        bad = state(active="A", committed="A",
                    pending="<script>window.attack=1</script>")
        r = self.render(bad)
        self.assertEqual(r["bank-recovery"], "Unverified")
        self.assertEqual(self.page.locator("#bank-next-reboot script").count(), 0)
        self.assertIsNone(self.page.evaluate("window.attack"))
        self.assertFalse(self.enabled("reboot"))
        self.assertEqual(self.unexpected, [])

    def install_action_mocks(self, next_state, confirm=True):
        # Intercept both the live read and any hypothetical mutation. No
        # request reaches the ONU. Browser network routes also deny others.
        self.page.evaluate("""({snapshot, confirm}) => {
            window.__actionHarness = {
                reads: [], posts: [], confirms: 0, jobs: 0,
                response: snapshot, confirm: confirm
            };
            window.request8311 = async path => {
                window.__actionHarness.reads.push(path);
                return window.__actionHarness.response;
            };
            window.post8311 = async (path, values) => {
                window.__actionHarness.posts.push({path, values});
                return {id:'synthetic',kind:'firmware',state:'done'};
            };
            window.monitorJob = () => {
                window.__actionHarness.jobs++;
            };
            window.refreshFirmwareState = async () => null;
            window.confirm = () => {
                window.__actionHarness.confirms++;
                return window.__actionHarness.confirm;
            };
        }""", {"snapshot": next_state, "confirm": confirm})

    def run_action(self, action, bank=None):
        selector = '[data-action="' + action + '"]'
        if bank:
            selector += '[data-bank="' + bank + '"]'
        return self.page.evaluate("""async selector => {
            const button = document.querySelector(selector);
            await submitCheckedFirmwareBankAction(button);
            return window.__actionHarness;
        }""", selector)

    def test_live_state_age_is_visible_and_locks_stale_controls(self):
        self.render(state())
        freshness = self.page.locator("#bank-state-freshness").inner_text()
        self.assertIn("checked in this browser", freshness)
        self.page.evaluate("""() => {
            firmwareBankStateVerifiedAt = Date.now() - 90000;
            refreshFirmwareControls();
        }""")
        self.assertFalse(self.enabled("reboot"))
        self.assertIn("stale", self.page.locator("#bank-state-freshness").inner_text())
        self.install_action_mocks(state())
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], [])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertEqual(self.unexpected, [])

    def test_live_bank_change_blocks_mutation_and_updates_preview(self):
        self.render(state(active="B", committed="B"))
        self.install_action_mocks(state(active="A", committed="A"))
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertIn("Bank state changed",
                      self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.page.locator("#bank-active").inner_text(), "A")
        self.assertEqual(self.page.locator("#bank-next-reboot").inner_text(),
                         "Bank A (committed)")
        self.assertEqual(self.unexpected, [])

    def test_invalid_preaction_response_blocks_mutation(self):
        self.render(state())
        bad = state(active="B", committed="B", pending="B")
        self.install_action_mocks(bad)
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertFalse(self.enabled("reboot"))
        self.assertEqual(self.page.locator("#bank-active").inner_text(), "unknown")
        self.assertIn("invalid", self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_confirmation_cancellation_never_submits_mutation(self):
        snapshot = state(active="A", committed="A", pending="B")
        self.render(snapshot)
        self.install_action_mocks(snapshot, confirm=False)
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["confirms"], 1)
        self.assertEqual(result["posts"], [])
        self.assertIn("Cancelled", self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_identical_fresh_state_allows_one_explicit_submission(self):
        snapshot = state()
        self.render(snapshot)
        self.install_action_mocks(snapshot, confirm=True)
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["confirms"], 1)
        self.assertEqual(result["posts"],
                         [{"path": "firmware", "values": {
                             "action": "reboot", "state_guard": snapshot["state_guard"]}}])
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(self.unexpected, [])

    def test_modified_bank_component_hash_blocks_stale_action(self):
        snapshot = state()
        snapshot["banks"]["A"]["components"] = {
            "rootfs": {"bytes": 100, "sha256": "example"}}
        self.render(snapshot)
        fresh = state()
        fresh["banks"]["A"]["components"] = {
            "rootfs": {"bytes": 100, "sha256": "different"}}
        self.install_action_mocks(fresh)
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertIn("Bank state changed",
                      self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_invalid_committed_fallback_blocks_running_trial_actions(self):
        bad = state(active="B", committed="A", trial=True)
        bad["banks"]["A"] = bank(False, "incomplete")
        self.render(bad)
        self.assertEqual(self.page.locator("#bank-recovery").inner_text(),
                         "Unverified")
        self.assertFalse(self.enabled("commit"))
        self.assertFalse(self.enabled("reboot"))
        self.assertEqual(self.unexpected, [])

    def test_status_endpoint_failure_clears_stale_authorization(self):
        self.render(state())
        self.install_action_mocks(state())
        self.page.evaluate("""() => {
            window.request8311 = async path => {
                window.__actionHarness.reads.push(path);
                throw {error: 'Synthetic status endpoint unavailable', _httpStatus: 503};
            };
        }""")
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertEqual(self.page.locator("#bank-active").inner_text(), "unknown")
        self.assertIn("unavailable", self.page.locator("#firmware-message").inner_text())
        self.assertFalse(self.enabled("reboot"))
        self.assertEqual(self.unexpected, [])

    def test_external_commit_while_page_open_blocks_second_commit(self):
        prior = state(active="B", committed="A", trial=True)
        self.render(prior)
        self.assertTrue(self.enabled("commit"))
        self.install_action_mocks(state(active="B", committed="B"))
        result = self.run_action("commit")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertFalse(self.enabled("commit"))
        self.assertEqual(self.page.locator("#bank-committed").inner_text(), "B")
        self.assertIn("Bank state changed",
                      self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_missing_status_fingerprint_locks_all_actions(self):
        snapshot = state()
        del snapshot["state_guard"]
        self.render(snapshot)
        self.assertEqual(self.page.locator("#bank-recovery").inner_text(),
                         "Unverified")
        self.assertFalse(self.enabled("reboot"))
        self.assertFalse(self.enabled("trial", "A"))
        self.assertEqual(self.unexpected, [])

    def test_malformed_status_fingerprint_locks_actions(self):
        for fingerprint in ("", "A" * 64, "g" * 64, "1" * 63,
                            "<script>bad</script>"):
            with self.subTest(fingerprint=fingerprint):
                snapshot = state()
                snapshot["state_guard"] = fingerprint
                self.render(snapshot)
                self.assertFalse(self.enabled("reboot"))
                self.assertEqual(
                    self.page.locator("#bank-next-reboot").inner_text(),
                    "Unknown, refresh required")
        self.assertEqual(self.unexpected, [])

    def test_same_selectors_different_server_fingerprint_rejects_submission(self):
        observed = state()
        self.render(observed)
        changed = state()
        changed["state_guard"] = ("0" if changed["state_guard"][0] != "0"
                                  else "1") + changed["state_guard"][1:]
        self.install_action_mocks(changed)
        result = self.run_action("reboot")
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertIn("Bank state changed",
                      self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_trial_and_commit_posts_include_native_state_fingerprint(self):
        for snapshot, action, bank in (
            (state(active="A", committed="A"), "trial", "B"),
            (state(active="B", committed="A", trial=True), "commit", None),
        ):
            with self.subTest(action=action):
                self.render(snapshot)
                self.install_action_mocks(snapshot)
                result = self.run_action(action, bank)
                expected = {"action": action, "state_guard": snapshot["state_guard"]}
                if bank:
                    expected["bank"] = bank
                self.assertEqual(result["posts"],
                                 [{"path": "firmware", "values": expected}])
                self.assertEqual(self.unexpected, [])

    def test_unknown_firmware_button_action_fails_closed(self):
        self.render(state())
        self.page.evaluate("""() => {
            const unknown = document.createElement('button');
            unknown.className = 'firmware-bank';
            unknown.dataset.action = 'unknown_action';
            document.body.appendChild(unknown);
            refreshFirmwareControls();
        }""")
        self.assertTrue(self.page.locator('[data-action="unknown_action"]').is_disabled())
        self.install_action_mocks(state())
        self.assertEqual(self.run_action("unknown_action")["posts"], [])
        self.assertEqual(self.unexpected, [])

    def run_install(self):
        return self.page.evaluate("""async () => {
            const button = document.querySelector('.firmware-artifact[data-action="install"]');
            const selection = document.querySelector('input[name="upload-selection"]:checked');
            await submitCheckedFirmwareInstall(button, selection);
            return window.__actionHarness;
        }""")

    def test_install_preview_identifies_inactive_recovery_bank(self):
        self.render(state(active="B", committed="B"))
        impact = self.page.locator("#bank-install-impact").inner_text()
        self.assertIn("OVERWRITE bank A", impact)
        self.assertIn("currently contains a valid firmware image", impact)
        self.assertIn("backups", impact)
        self.assertFalse(self.page.locator('[data-action="install"]').is_disabled())
        self.assertEqual(self.unexpected, [])

    def test_install_preview_reverses_target_when_running_bank_changes(self):
        self.render(state(active="A", committed="A"))
        impact = self.page.locator("#bank-install-impact").inner_text()
        self.assertIn("OVERWRITE bank B", impact)
        self.assertNotIn("OVERWRITE bank A", impact)
        self.assertEqual(self.unexpected, [])

    def test_invalid_live_status_disables_install_but_not_archive_preflight(self):
        self.render(None)
        self.assertTrue(self.page.locator('[data-action="install"]').is_disabled())
        self.assertFalse(self.page.locator('[data-action="validate"]').is_disabled())
        self.assertFalse(self.page.locator('[data-action="discard_upload"]').is_disabled())
        self.assertIn("not verified", self.page.locator("#bank-install-impact").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_trial_and_pending_boot_lock_installer(self):
        for candidate in (state(active="B", committed="A", trial=True),
                          state(active="A", committed="A", pending="B")):
            with self.subTest(candidate=candidate):
                self.render(candidate)
                self.assertTrue(self.page.locator('[data-action="install"]').is_disabled())
                self.assertIn("Installation is locked",
                              self.page.locator("#bank-install-impact").inner_text())
                self.assertFalse(self.page.locator('[data-action="validate"]').is_disabled())
        self.assertEqual(self.unexpected, [])

    def test_expired_live_state_disables_flash_upload_action(self):
        self.render(state())
        self.page.evaluate("""() => {
            firmwareBankStateVerifiedAt = Date.now() - 90000;
            refreshFirmwareControls();
        }""")
        self.assertTrue(self.page.locator('[data-action="install"]').is_disabled())
        self.install_action_mocks(state())
        self.assertEqual(self.run_install()["posts"], [])
        self.assertEqual(self.unexpected, [])

    def test_install_requires_fresh_same_target_state_before_confirmation(self):
        self.render(state(active="B", committed="B"))
        self.install_action_mocks(state(active="A", committed="A"))
        result = self.run_install()
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertIn("changed", self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])

    def test_install_invalid_refreshed_state_blocks_write(self):
        self.render(state())
        bad = state(active="A", committed="A", pending="A")
        self.install_action_mocks(bad)
        result = self.run_install()
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertTrue(self.page.locator('[data-action="install"]').is_disabled())
        self.assertEqual(self.unexpected, [])

    def test_install_cancel_does_not_write_and_confirmation_has_target(self):
        snapshot = state(active="B", committed="B")
        self.render(snapshot)
        self.install_action_mocks(snapshot, confirm=False)
        self.page.evaluate("""() => {
            window.confirm = text => {
                window.__actionHarness.confirmation = text;
                window.__actionHarness.confirms++;
                return false;
            };
        }""")
        result = self.run_install()
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 1)
        self.assertIn("OVERWRITE bank A", result["confirmation"])
        self.assertIn("BOTH A and B", result["confirmation"])
        self.assertEqual(self.unexpected, [])

    def test_install_approved_same_state_posts_one_upload(self):
        snapshot = state()
        self.render(snapshot)
        self.install_action_mocks(snapshot, confirm=True)
        result = self.run_install()
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["confirms"], 1)
        self.assertEqual(result["posts"], [{"path": "firmware", "values": {
            "action": "install", "upload_id": "synthetic-upload",
            "sha256": "synthetic-hash",
            "expected_active": "B", "expected_target": "A",
            "state_guard": snapshot["state_guard"]}}])
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(self.unexpected, [])

    def test_switched_upload_during_refresh_does_not_install(self):
        snapshot = state()
        self.render(snapshot)
        self.install_action_mocks(snapshot, confirm=True)
        self.page.evaluate("""() => {
            window.request8311 = async path => {
                window.__actionHarness.reads.push(path);
                document.querySelector('input[name="upload-selection"]').value = 'changed-upload';
                return window.__actionHarness.response;
            };
        }""")
        result = self.run_install()
        self.assertEqual(result["reads"], ["bank_status"])
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["confirms"], 0)
        self.assertIn("selected upload changed",
                      self.page.locator("#firmware-message").inner_text())
        self.assertEqual(self.unexpected, [])


if __name__ == "__main__":
    unittest.main()

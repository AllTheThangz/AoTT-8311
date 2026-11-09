from pathlib import Path
import json, os, re, shutil, unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/tls.htm"
HOST="https://192.0.2.1"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

def actual_script():
    text=VIEW.read_text()
    blocks=re.findall(r"<script>(.*?)</script>",text,re.S)
    if not blocks:
        raise AssertionError("TLS inline script unavailable")
    script=blocks[-1]
    if "<%" in script:
        raise AssertionError("TLS inline script unexpectedly contains template directives")
    return script

def html():
    return """<!doctype html><html><body>
<p id="tls-candidate-state">absent</p>
<p id="tls-candidate-fingerprint">No inactive candidate is present.</p>
<p id="tls-operation-status"></p>
<form id="tls-candidate-generate" action="/admin/8311/tls_generate">
<input name="token" value="csrf-fixture"><button id="tls-generate-button">Generate</button></form>
<form id="tls-candidate-import" action="/admin/8311/tls_import" enctype="multipart/form-data">
<input name="token" value="csrf-fixture">
<input id="tls-import-cert" name="certificate_file" type="file">
<input id="tls-import-key" name="private_key_file" type="file">
<input id="tls-import-chain" name="chain_file" type="file">
<input id="tls-import-dns" name="dns_sans" value="onu.example.test">
<input id="tls-import-ip" name="ip_sans" value="">
<button id="tls-import-button" type="submit">Validate and stage imported candidate</button>
</form>
<form id="tls-candidate-discard" action="/admin/8311/tls_discard">
<input name="token" value="csrf-fixture"><button id="tls-discard-button" disabled>Discard</button></form>
</body></html>"""

class BrowserTlsImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
        if missing:
            msg="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1": raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None): cls.browser.close()
        if getattr(cls,"runner",None): cls.runner.stop()

    def test_import_uses_multipart_csrf_and_stages_candidate_only(self):
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        seen=[]
        def handler(route):
            u=urlsplit(route.request.url)
            if route.request.resource_type=="document" and u.path=="/tls":
                return route.fulfill(status=200,content_type="text/html",body=html())
            if route.request.method=="POST" and u.path=="/admin/8311/tls_import":
                seen.append({
                    "headers":route.request.headers,
                    "body":route.request.post_data_buffer,
                })
                return route.fulfill(status=201,content_type="application/json",
                    body=json.dumps({
                        "success":True,"status":"TLS_IMPORT_CANDIDATE_READY",
                        "candidate_ready":True,
                        "certificate_sha256":"a"*64,
                        "certificate_bytes":1024,"private_key_bytes":512,
                        "private_key_mode":"0600","expires_utc":"20271201000000Z",
                        "dns_san_count":1,"ipv4_san_count":0,
                        "chain_certificates":1,
                        "native_uhttpd_pair_verified":True,
                        "chain_name_links_verified":1,
                        "browser_trust_unverified":True,
                        "active_https_changed":False,
                    }))
            return route.abort()
        page.route("**/*",handler)
        try:
            page.goto(HOST+"/tls",wait_until="load")
            page.add_script_tag(content=actual_script())
            page.locator("#tls-import-cert").set_input_files({
                "name":"leaf.pem","mimeType":"application/x-pem-file",
                "buffer":b"synthetic certificate fixture"
            })
            page.locator("#tls-import-key").set_input_files({
                "name":"key.pem","mimeType":"application/x-pem-file",
                "buffer":b"synthetic private key fixture"
            })
            page.locator("#tls-import-button").click()
            page.wait_for_function(
                "() => document.getElementById('tls-candidate-state').textContent === 'ready'")
            self.assertEqual(len(seen),1)
            headers={k.lower():v for k,v in seen[0]["headers"].items()}
            self.assertEqual(headers.get("x-csrf-token"),"csrf-fixture")
            self.assertIn("multipart/form-data",headers.get("content-type",""))
            body=seen[0]["body"] or b""
            self.assertIn(b'filename="leaf.pem"',body)
            self.assertIn(b'filename="key.pem"',body)
            self.assertIn(b'name="dns_sans"',body)
            self.assertIn(b"onu.example.test",body)
            self.assertEqual(page.locator("#tls-candidate-fingerprint").inner_text(),"a"*64)
            status=page.locator("#tls-operation-status").inner_text()
            self.assertIn("HTTPS remains unchanged",status)
            self.assertIn("browser trust",status)
            self.assertTrue(page.locator("#tls-import-button").is_disabled())
            self.assertFalse(page.locator("#tls-discard-button").is_disabled())
        finally:
            context.close()

    def test_view_retains_guarded_activation_boundary(self):
        text=VIEW.read_text()
        self.assertIn("Import operator-owned certificate",text)
        self.assertIn("native uhttpd TLS handshake",text)
        self.assertIn("Generated and imported candidates use the same guarded activation",text)
        self.assertIn("Confirm this HTTPS certificate",text)
        self.assertIn("rolls back automatically",text)

if __name__=="__main__":
    unittest.main()

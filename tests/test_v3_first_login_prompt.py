from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
MODULE=OVERLAY/"usr/lib/lua/8311/first_login.lua"
CONTROLLER=OVERLAY/"usr/lib/lua/luci/controller/8311.lua"
HEADER=OVERLAY/"usr/lib/lua/luci/view/themes/bootstrap/header.htm"
CSS=OVERLAY/"www/luci-static/bootstrap/aott-theme.css"
FIXTURE=ROOT/"tests/v3_first_login_prompt_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class V3FirstLoginPromptTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_FIRST_LOGIN_PROMPT_PASS",p.stdout)

    def test_host_lua_state_and_acknowledgement(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1",str(FIXTURE),str(OVERLAY/"usr/lib/lua")])

    def test_vendor_mips_state_and_acknowledgement(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(OVERLAY/"usr/lib/lua")
        ])

    def test_persistent_marker_is_fixed_private_device_state(self):
        s=MODULE.read_text()
        self.assertIn('local ROOT="/ptconf/8311"',s)
        self.assertIn('local ACK=ROOT.."/.factory-password-prompt-v1.ack"',s)
        self.assertIn('modedec==600',s)
        self.assertIn('factory_default_root_password',s)
        self.assertNotIn("localStorage",s)
        self.assertNotIn("cookie",s.lower())

    def test_ack_route_is_authenticated_root_and_csrf_protected(self):
        s=CONTROLLER.read_text()
        self.assertIn('entry({"admin", "8311", "factory_password_ack"}, post("action_factory_password_ack"))',s)
        start=s.index("function action_factory_password_ack()")
        end=s.index("\nend\n",start)+5
        block=s[start:end]
        self.assertIn("dispatcher.context.authsession",block)
        self.assertIn("dispatcher.test_post_security()",block)
        self.assertIn('dispatcher.context.authuser~="root"',block)
        self.assertIn("first_login.acknowledge()",block)

    def test_header_prompts_factory_login_and_keeps_password_page_accessible(self):
        s=HEADER.read_text()
        self.assertIn("aott_first_login_prompt",s)
        self.assertIn('state.prompt_required == true',s)
        self.assertIn('aott_current_path ~= "admin/system/admin/password"',s)
        self.assertIn("Change the default administrator password?",s)
        self.assertIn("root / root",s)
        self.assertIn("Change password now",s)
        self.assertIn("Keep root/root",s)
        self.assertIn("disp.context.authtoken",s)
        self.assertIn("factory_password_ack",s)
        self.assertIn('method="get"',s)
        self.assertIn("action=\"<%=url('admin/system/admin/password')%>\"",s)
        self.assertIn('id="aott-first-login-change"',s)
        self.assertIn('id="aott-first-login-keep"',s)

    def test_ack_response_is_complete_html_not_empty_redirect(self):
        s=CONTROLLER.read_text()
        start=s.index("function action_factory_password_ack()")
        end=s.index("\nend\n",start)+5
        block=s[start:end]
        self.assertIn('http.prepare_content("text/html; charset=utf-8")',block)
        self.assertIn("Factory login choice saved",block)
        self.assertIn("No password was changed",block)
        self.assertNotIn("http.redirect",block)

    def test_prompt_is_modal_responsive_and_not_javascript_dependent(self):
        css=CSS.read_text()
        self.assertIn(".aott-first-login-overlay",css)
        self.assertIn("position:fixed",css)
        self.assertIn(".aott-first-login-dialog",css)
        self.assertIn("@media(max-width:560px)",css)
        header=HEADER.read_text()
        block=header[header.index('class="aott-first-login-overlay"'):header.index('id="maincontent"')]
        self.assertNotIn("<script",block)
        self.assertIn('role="dialog"',block)
        self.assertIn('aria-modal="true"',block)

if __name__=="__main__":
    unittest.main()

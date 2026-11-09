from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
LUA=OVERLAY/"usr/lib/lua"
FIXTURE=ROOT/"tests/v3_management_preflight_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class V3ManagementPreflightTests(unittest.TestCase):
    def run_fixture(self,argv):
        p=subprocess.run(argv+[str(FIXTURE),str(LUA)],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_PREFLIGHT_PASS",p.stdout)

    def test_host_lua_preflight(self):
        if not shutil.which("lua5.1"): self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_preflight(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua")])

    def test_guarded_runtime_modules_are_present(self):
        required=(
            "native_management_reader.lua","recovery_storage.lua",
            "vlan_transition.lua","management_preflight.lua",
            "management_environment.lua","management_recovery_store.lua",
            "management_uci.lua","management_runtime.lua",
            "management_transaction.lua","management_access.lua",
        )
        for name in required:
            self.assertTrue((LUA/"8311"/name).is_file(),name)
        self.assertTrue((OVERLAY/"usr/libexec/8311-management-apply").is_file())
        self.assertTrue((OVERLAY/"usr/libexec/8311-management-apply.lua").is_file())
        self.assertTrue((OVERLAY/"usr/libexec/8311-management-recover-pending").is_file())

    def test_controller_has_preview_apply_and_confirm_guards(self):
        ctl=(OVERLAY/"usr/lib/lua/luci/controller/8311.lua").read_text()
        for route in ("management_preflight","management_vlan_preview",
                      "management_preview","management_apply","management_confirm"):
            self.assertIn(f'"{route}"',ctl)
        apply=ctl[ctl.index("function action_management_apply()"):
                  ctl.index("function action_management_confirm()")]
        self.assertIn('HTTPS',apply)
        self.assertIn('dispatcher.context.authsession',apply)
        self.assertIn('dispatcher.context.authuser~="root"',apply)
        self.assertIn('dispatcher.test_post_security()',apply)
        self.assertIn('"management_apply"',apply)
        self.assertIn('management_preflight.preview_management(values)',apply)
        confirm=ctl[ctl.index("function action_management_confirm()"):
                    ctl.index("function action_tls()")]
        self.assertIn('jobs.confirm_management(values.job_id)',confirm)
        self.assertIn('dispatcher.context.authuser~="root"',confirm)

    def test_management_worker_uses_shared_environment_lock_and_private_request(self):
        wrapper=(OVERLAY/"usr/libexec/8311-management-apply").read_text()
        worker=(OVERLAY/"usr/libexec/8311-management-apply.lua").read_text()
        jobs=(LUA/"8311/jobs.lua").read_text()
        self.assertIn(". /lib/8311-env-lock.sh",wrapper)
        self.assertIn("lock_environment",wrapper)
        self.assertIn('exec /usr/bin/lua /usr/libexec/8311-management-apply.lua "$1"',wrapper)
        self.assertIn('dir.."/request.json"',worker)
        self.assertIn('argv={"/usr/libexec/8311-management-apply",dir}',jobs)
        for field in ("ipaddr","netmask","gateway","dns_server","lct_mac"):
            self.assertNotIn(f'argv={{"/usr/libexec/8311-management-apply",dir,request.args.{field}',jobs)

    def test_boot_recovers_pending_change_before_normal_start_logic(self):
        sysinit=(OVERLAY/"etc/init.d/_8311-sysinit.sh").read_text()
        recover=sysinit.index("/usr/libexec/8311-management-recover-pending")
        console=sysinit.index("CONSOLE_EN=$(get_8311_console_en)")
        self.assertLess(recover,console)
        self.assertIn("return 1",sysinit[recover:console])

    def test_view_exposes_confirmation_but_keeps_hardware_status_honest(self):
        view=(OVERLAY/"usr/lib/lua/luci/view/8311/management_preflight.htm").read_text()
        self.assertIn("Pending guarded transaction",view)
        self.assertIn("Confirm this management path",view)
        self.assertIn("automatically roll back",view)
        self.assertIn("not yet hardware-qualified",view)
        self.assertNotIn("Apply is intentionally unavailable",view)

if __name__=="__main__":
    unittest.main()

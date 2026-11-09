from pathlib import Path
import os, re, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULES=[
 ROOT/"overlay/usr/lib/lua/8311/access_config.lua",
 ROOT/"overlay/usr/lib/lua/8311/access_recovery_store.lua",
 ROOT/"overlay/usr/lib/lua/8311/access_runtime.lua",
 ROOT/"overlay/usr/lib/lua/8311/access_transaction.lua",
 ROOT/"overlay/usr/lib/lua/8311/access_uci.lua",
 ROOT/"overlay/usr/lib/lua/8311/management_access.lua",
 ROOT/"overlay/usr/lib/lua/8311/remote_firewall.lua",
]
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/access.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311-access.js"
JOBS=ROOT/"overlay/usr/lib/lua/8311/jobs.lua"
SYSINIT=ROOT/"overlay/etc/init.d/_8311-sysinit.sh"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3AccessTransactionTests(unittest.TestCase):
    def test_modules_compile_host_and_vendor(self):
        for path in MODULES:
            p=subprocess.run(["luac5.1","-p",str(path)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
        if os.getenv("AOTT_VENDOR_ROOTFS"):
            lua=VENDOR/"usr/bin/lua"
            for path in MODULES:
                p=subprocess.run([
                    "qemu-mips-static","-L",str(VENDOR),str(lua),"-e",
                    f"assert(loadfile({str(path)!r}))"
                ],capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_exact_twenty_two_access_fields(self):
        s=MODULES[0].read_text()
        block=s[s.index("local FIELDS={"):s.index("local FIELD={")]
        ids=re.findall(r'id="([a-z0-9_]+)"',block)
        self.assertEqual(len(ids),22)
        self.assertEqual(len(set(ids)),22)
        for required in ("ssh_enabled","ssh_port","ssh_root_login","luci_sessiontime",
                         "web_http_port","web_https_port","web_max_connections",
                         "web_rfc1918_filter","remote_gui_enabled",
                         "remote_gui_ipv4_sources"):
            self.assertIn(required,ids)

    def test_remote_firewall_is_inside_access_recovery_transaction(self):
        recovery=(ROOT/"overlay/usr/lib/lua/8311/access_recovery_store.lua").read_text()
        writer=(ROOT/"overlay/usr/lib/lua/8311/access_uci.lua").read_text()
        runtime=(ROOT/"overlay/usr/lib/lua/8311/access_runtime.lua").read_text()
        tx=(ROOT/"overlay/usr/lib/lua/8311/access_transaction.lua").read_text()
        self.assertIn('firewall={path=ROOT.."/firewall.before"',recovery)
        self.assertIn('firewall_sha256',recovery)
        self.assertIn('remote_firewall.apply',writer)
        self.assertIn('"firewall"',writer)
        self.assertIn('remote_firewall.verify',runtime)
        self.assertIn('{"/etc/init.d/firewall","restart"}',tx)
        self.assertIn("kernel_packet_path_unverified",runtime)

    def test_recovery_is_armed_before_access_mutation(self):
        s=(ROOT/"overlay/usr/lib/lua/8311/access_transaction.lua").read_text()
        self.assertLess(s.index("recovery.arm(job,raw)"),s.index("uci.apply(before,prepared.desired)"))
        self.assertIn("return rollback(job,",s)
        self.assertIn("access_confirmation_timeout",s)
        self.assertIn("runtime.verify(snapshot)",s)

    def test_luci_routes_are_root_https_guarded(self):
        s=CONTROLLER.read_text()
        for route in ("access","access_preview","access_apply","access_confirm","access_status"):
            self.assertIn(f'"{route}"',s)
        apply=s[s.index("function action_access_apply()"):s.index("function action_access_confirm()")]
        confirm=s[s.index("function action_access_confirm()"):s.index("function action_access_status()")]
        for block in (apply,confirm):
            self.assertIn('http.getenv("HTTPS")',block)
            self.assertIn('dispatcher.context.authuser~="root"',block)
            self.assertIn("dispatcher.test_post_security()",block)
        self.assertIn('jobs.start("access_apply"',apply)
        self.assertIn("jobs.confirm_access",confirm)

    def test_page_is_guarded_and_does_not_expose_management_address_or_credentials(self):
        v=VIEW.read_text()
        j=JS.read_text()
        self.assertIn('id="aott-access-form"',v)
        self.assertIn('name="token"',v)
        self.assertIn("Guarded access configuration",v)
        self.assertIn("automatic rollback",v)
        self.assertNotIn("management_ip",v)
        self.assertNotIn("password_hash",v)
        self.assertIn("same-origin",j)
        self.assertIn("Open the intended HTTPS endpoint",j)
        self.assertIn("job_id",j)

    def test_job_worker_and_boot_recovery_are_wired(self):
        jobs=JOBS.read_text()
        self.assertIn("access_apply=true",jobs)
        self.assertIn('argv={"/usr/libexec/8311-access-apply",dir}',jobs)
        self.assertIn("function M.confirm_access",jobs)
        boot=SYSINIT.read_text()
        self.assertIn("/usr/libexec/8311-access-recover-pending",boot)
        self.assertLess(boot.index("8311-access-recover-pending"),
                        boot.index("CONSOLE_EN=$(get_8311_console_en)"))

    def test_no_dynamic_shell_in_access_modules(self):
        for path in MODULES:
            s=path.read_text()
            self.assertNotIn("os.execute",s,path.name)
            self.assertNotIn("io.popen",s,path.name)
            self.assertNotIn("shellquote",s,path.name)

if __name__=="__main__":
    unittest.main()

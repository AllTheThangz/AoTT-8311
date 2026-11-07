from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
LUA=OVERLAY/"usr/lib/lua"
FIXTURE=ROOT/"tests/v3_history_runtime_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class V3HistoryRuntimeTests(unittest.TestCase):
    def test_host_lua_projection_and_config_contract(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        p=subprocess.run(["lua5.1",str(FIXTURE),str(LUA)],
                         cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_HISTORY_RUNTIME_FIXTURE_PASS",p.stdout)

    def test_vendor_mips_projection_and_config_contract(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        p=subprocess.run([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(LUA)
        ],cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_HISTORY_RUNTIME_FIXTURE_PASS",p.stdout)

    def test_vendor_mips_production_lock_and_snapshot_path(self):
        if os.geteuid()!=0:
            self.skipTest("Production lock fixture requires root-owned /run")
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        runtime=Path("/run/aott-history")
        if runtime.exists():
            self.skipTest("/run/aott-history already exists")
        runtime.mkdir(mode=0o700)
        try:
            p=subprocess.run([
                "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                str(ROOT/"tests/v3_history_production_lock_fixture.lua"),str(LUA)
            ],cwd=ROOT,capture_output=True,text=True,timeout=25)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn("AOTT_V3_HISTORY_PRODUCTION_LOCK_PASS",p.stdout)
            self.assertFalse((runtime/"snapshot.json").exists())
        finally:
            for name in ("snapshot.json.new","snapshot.json","publication.lock","collector.lock"):
                path=runtime/name
                if path.exists() and not path.is_symlink():
                    path.unlink()
            if runtime.exists():
                runtime.rmdir()

    def test_service_is_opt_in_and_has_no_respawn(self):
        init=(OVERLAY/"etc/init.d/8311-history").read_text()
        self.assertIn('config_get enabled main enabled 0',init)
        self.assertIn('[ "$enabled" = "1" ] || return 0',init)
        self.assertNotIn("procd_set_param respawn",init)
        self.assertIn("/usr/libexec/8311-history-wrapper",init)
        wrapper=(OVERLAY/"usr/libexec/8311-history-wrapper").read_text()
        self.assertIn("ulimit -c 0",wrapper)
        self.assertIn("ulimit -n 32",wrapper)
        self.assertIn("/bin/nice -n 10",wrapper)

    def test_worker_is_read_only_and_ram_first(self):
        worker=(OVERLAY/"usr/libexec/8311-history-worker.lua").read_text()
        for forbidden in ("fwenv_set","fw_setenv","ubiupdatevol","/dev/mtd",
                          "uci:commit","socket.","http.request","curl ","wget "):
            self.assertNotIn(forbidden,worker)
        self.assertIn("history_native_probe",worker)
        self.assertIn("history_live_snapshot",worker)
        self.assertIn("consecutive_failures>=4",worker)

    def test_dual_lock_freshness_and_fixed_runtime_path(self):
        live=(LUA/"8311/history_live_snapshot.lua").read_text()
        gate=(LUA/"8311/history_publication_gate.lua").read_text()
        lock=(LUA/"8311/history_process_lock.lua").read_text()
        self.assertIn('local PRODUCTION_DIR="/run/aott-history"',lock)
        self.assertIn('mode=="production_runtime" and directory==PRODUCTION_DIR',gate)
        self.assertIn('lock.writer_present(DIR)',live)
        self.assertGreaterEqual(live.count('gate.reader_admitted(DIR,"production_runtime")'),2)
        self.assertIn('exporter.export_json(state,"hour",100,"local_runtime")',live)

    def test_history_routes_are_admin_only(self):
        ctl=(OVERLAY/"usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('entry({"admin", "8311", "history"}',ctl)
        self.assertIn('entry({"admin", "8311", "history_data"}',ctl)
        self.assertNotIn('entry({"8311", "history"}',ctl)
        self.assertNotIn('entry({"8311", "history_data"}',ctl)
        self.assertIn('not dispatcher.context.authsession',ctl)
        self.assertIn('history_snapshot.read_guarded()',ctl)

    def test_live_ui_does_not_claim_isp_uptime(self):
        view=(OVERLAY/"usr/lib/lua/luci/view/8311/history.htm").read_text()
        js=(OVERLAY/"www/luci-static/resources/view/aott-history.js").read_text()
        self.assertIn("does not claim ISP uptime",view)
        self.assertIn("PON association and Ethernet link status do not establish Internet service",view)
        self.assertIn('src.kind !== "aott_local_history"',js)
        self.assertIn('src.source_only_not_live !== false',js)
        self.assertIn('sourceOnly:false',js)

if __name__=="__main__":
    unittest.main()

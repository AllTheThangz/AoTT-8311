from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
TX=ROOT/"overlay/usr/lib/lua/8311/pon_config_transaction.lua"
REC=ROOT/"overlay/usr/lib/lua/8311/pon_config_recovery.lua"
ENV=ROOT/"overlay/usr/lib/lua/8311/pon_environment.lua"
UCI=ROOT/"overlay/usr/lib/lua/8311/pon_config_uci.lua"
RUNTIME=ROOT/"overlay/usr/lib/lua/8311/pon_config_runtime.lua"
FIXTURE=ROOT/"tests/v3_pon_transaction_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing"))

class V3PonTransactionTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_PON_TRANSACTION_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"): self.skipTest("No vendor rootfs")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_recovery_is_armed_before_any_mutation(self):
        s=TX.read_text()
        arm=s.index("safe(provider.arm")
        for token in ("safe(provider.apply_environment","safe(provider.apply_uci",
                      "safe(provider.apply_mib","safe(provider.apply_aux",
                      "safe(provider.restart"):
            self.assertLess(arm,s.index(token))

    def test_timeout_and_all_forward_failures_enter_restore(self):
        s=TX.read_text()
        self.assertIn('return rollback(provider,jobid,"pon_confirmation_timeout")',s)
        for reason in ("pon_environment_apply_failed","pon_uci_apply_failed",
                       "pon_mib_apply_failed","pon_aux_apply_failed",
                       "omcid_restart_failed","pon_runtime_convergence_failed"):
            self.assertIn(reason,s)

    def test_public_results_never_claim_olt_effect(self):
        s=TX.read_text()+RUNTIME.read_text()
        self.assertIn("olt_per_field_effect_proven=false",s)
        self.assertIn("subscriber_values_returned=false",s)
        self.assertIn("contains_configuration_values=false",s)
        self.assertNotIn("olt_per_field_effect_proven=true",s)

    def test_fw_match_storage_and_native_decode_contract(self):
        s=ENV.read_text()
        self.assertIn('local function storage(id)\n    return id\nend',s)
        config=(ROOT/"overlay/usr/lib/lua/8311/config.lua").read_text()
        self.assertIn('local function storage_id(item) return item.id end',config)
        probe=(ROOT/"overlay/usr/lib/lua/8311/effective_reporting_probe.lua").read_text()
        self.assertIn('return read_env(id,false,',probe)
        if os.getenv("AOTT_VENDOR_ROOTFS"):
            getter=(VENDOR/"usr/sbin/fwenv_get").read_text()
            secure=(VENDOR/"sbin/secure_upgrade.sh").read_text()
            self.assertIn('suffix=_b64',getter)
            self.assertIn('-b|--base64)',getter)
            self.assertIn("fwenv_get_8311 --base64 'fw_match'",secure)

    def test_persistent_store_captures_uci_environment_and_all_mibs(self):
        s=REC.read_text()
        for name in ("environment.before","gpon.before","omci.before","network.before"):
            self.assertIn(name,s)
        self.assertIn('fs.glob("/etc/mibs/*.ini")',s)
        self.assertIn("pon_mib_backup_digest_failed",s)
        self.assertIn("PON_CONFIRMATION_RECORDED",s)

    def test_fixed_native_paths_no_dynamic_shell(self):
        combined=TX.read_text()+UCI.read_text()+RUNTIME.read_text()
        for path in ("/etc/init.d/omcid.sh","/sbin/uboot_img_vars.sh",
                     "/sbin/secure_upgrade.sh"):
            self.assertIn(path,combined)
        for forbidden in ("os.execute","io.popen","shellquote","ubiupdatevol","8311-bankctl"):
            self.assertNotIn(forbidden,combined)

    def test_pristine_mib_clear_roundtrip_uses_rom_source(self):
        editor=ROOT/"overlay/usr/libexec/8311-mib-edit.lua"
        runtime=(ROOT/"overlay/usr/lib/lua/8311/pon_mib_runtime.lua").read_text()
        self.assertIn('local src="/rom"..p',runtime)
        self.assertIn('"copy-field"',runtime)
        self.assertIn('"check-field-source"',runtime)
        self.assertIn('"copy-slot"',runtime)
        self.assertIn('"check-slot-source"',runtime)
        self.assertIn('copy-field',editor.read_text())
        self.assertIn('copy-slot',editor.read_text())

    def test_boot_recovery_preserves_persistently_confirmed_candidate(self):
        s=TX.read_text()
        start=s.index("function M.recover_pending()")
        block=s[start:]
        self.assertIn("recovery.confirmed(state.job_id)",block)
        self.assertIn("confirmed_preserved=true",block)
        self.assertLess(block.index("recovery.confirmed(state.job_id)"),
                        block.index("production_provider().restore"))

    def test_lua_syntax(self):
        for p in (TX,REC,ENV,UCI,RUNTIME,ROOT/"overlay/usr/lib/lua/8311/pon_mib_runtime.lua"):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=="__main__":
    unittest.main()

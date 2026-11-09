"""Synthetic release checks, no running ONU or flash access."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/"tools"/"audit_firmware_trial_recovery.py"
spec=importlib.util.spec_from_file_location("audit_watchdog",TOOL)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class OfflineWatchdogAdmission(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/"rootfs"
        for path,mode in audit.FILES.items():
            source=ROOT/"overlay"/path
            target=self.root/path
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            target.chmod(mode)

    def test_candidate_contract(self):
        receipt=audit.verify(self.root)
        self.assertEqual(receipt["trial_timeout_seconds"],180)
        self.assertFalse(receipt["watchdog_requires_network"])
        self.assertFalse(receipt["hardware_rollback_qualified"])
        self.assertFalse(receipt["power_loss_qualified"])
        self.assertFalse(receipt["safe_for_live_install"])

    def test_missing_watchdog_is_fatal(self):
        (self.root/"usr/libexec/8311-firmware-trial-watchdog").unlink()
        with self.assertRaisesRegex(audit.AdmissionError,"required_recovery_component_absent"):
            audit.verify(self.root)

    def test_modified_boot_hook_denied(self):
        path=self.root/"etc/init.d/_8311-sysinit.sh"
        contents=path.read_text().replace(
            "/usr/libexec/8311-firmware-trial-watchdog",
            "/usr/libexec/not-the-watchdog")
        path.write_text(contents)
        path.chmod(0o755)
        with self.assertRaisesRegex(audit.AdmissionError,"missing_boot_watchdog_admission"):
            audit.verify(self.root)

    def test_symlink_recovery_file_denied(self):
        path=self.root/"usr/libexec/8311-firmware-trial-confirm"
        path.unlink()
        path.symlink_to(self.root/"usr/libexec/8311-firmware-trial-watchdog")
        with self.assertRaisesRegex(audit.AdmissionError,"symlink_in_recovery_path"):
            audit.verify(self.root)

    def test_permission_regression_denied(self):
        p=self.root/"usr/lib/lua/8311/firmware_trial_watchdog.lua"
        p.chmod(0o666)
        with self.assertRaisesRegex(audit.AdmissionError,"unsafe_recovery_component_mode_or_size"):
            audit.verify(self.root)

    def test_network_dependency_added_denied(self):
        p=self.root/"usr/lib/lua/8311/firmware_trial_watchdog.lua"
        p.write_text(p.read_text() + "\n" + "os.execute('curl example.invalid')\n")
        with self.assertRaisesRegex(audit.AdmissionError,"network_dependent_watchdog"):
            audit.verify(self.root)

if __name__=="__main__":
    unittest.main()

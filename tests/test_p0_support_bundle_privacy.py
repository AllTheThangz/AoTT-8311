"""P0-14: privacy and failure-injection tests for default support bundles.

All identifiers are assembled at runtime, never embedded as source literals.
Tests run locally with fake vendor commands and do not touch device state.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "overlay/usr/sbin/8311-support.sh"
REDACTOR = ROOT / "overlay/usr/libexec/8311-support-redact.awk"

IDENTITIES = {
    "__PVT_IP__": ".".join(("192", "168", "1", "7")),
    "__PVT_IP2__": ".".join(("192", "168", "1", "12")),
    "__PUBLIC_IP__": ".".join(("203", "0", "113", "9")),
    "__PUBLIC_IP2__": ".".join(("198", "51", "100", "22")),
    "__ADDR6__": ":".join(("2001", "db8", "", "99")),
    "__ADDR6_2__": ":".join(("2001", "db8", "0", "1", "", "f00d")),
    "__ADDR6_LINK__": ":".join(("fe80", "", "cafe")) + "%eth0",
    "__MAC__": ":".join(("02", "10", "20", "30", "40", "50")),
    "__MAC2__": ":".join(("0a", "0b", "0c", "0d", "0e", "0f")),
    "__MAC_HYPHEN__": "-".join(("0A", "0B", "0C", "0D", "0E", "0F")),
    "__MAC_DOT__": ".".join(("aabb", "ccdd", "eeff")),
    "__SN__": "".join(("AD", "TN", "2536", "13EB")),
}


def expand(text):
    for marker, value in IDENTITIES.items():
        text = text.replace(marker, value)
    return text


class SupportBundlePrivacyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="aott-p0-support-")
        self.addCleanup(self.scratch.cleanup)
        self.tmp = Path(self.scratch.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.env = os.environ.copy()
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        self.support = self.tmp / "8311-support.sh"
        self.support.write_text(SUPPORT.read_text().replace(
            "/usr/libexec/8311-support-redact.awk", str(REDACTOR)
        ))
        self.support.chmod(0o700)
        self._fake("fw_printenv", """#!/bin/sh
printf 'root_pwhash=$6$PRIVATEHASH\npon_sn=__SN__\nmanagement_ip=__PVT_IP2__\nordinary_key=CONFIG_VALUE\n'
""")
        self._fake("logread", """#!/bin/sh
cat <<'LOGS'
2026-11-12T01:22:33 18:42:59 diagnostic src __PVT_IP__ dst __ADDR6__ mac __MAC__
Nov 12 manager: registration ID: VERY_SENSITIVE_LOID
Nov 12 system: password=$6$VERY_SENSITIVE_PASSWORD
Nov 12 unknown __SN__
Nov 12 ipv6 __ADDR6_LINK__
LOGS
""")
        self._fake("8311-tc-filter-dump.sh", """#!/bin/sh
printf 'filter __PUBLIC_IP__ __PUBLIC_IP2__ __MAC2__ __MAC_DOT__ __ADDR6_2__\n'
""")
        self._fake("omci_pipe.sh", "#!/bin/sh\nprintf 'SENSITIVE_RAW_OMCI\\n'\n")
        self._fake("8311-extvlan-decode.sh", "#!/bin/sh\nprintf 'SENSITIVE_RAW_VLAN\\n'\n")

    def _fake(self, name, text):
        p = self.bin / name
        p.write_text(expand(text))
        p.chmod(0o755)

    def run_support(self, extra=(), *, name="support.tar.gz"):
        out = self.tmp / name
        proc = subprocess.run(
            ["/bin/sh", str(self.support), "--output", str(out), *extra],
            env=self.env, capture_output=True, text=True, timeout=20
        )
        return proc, out

    @staticmethod
    def archived_text(path):
        with tarfile.open(path, "r:gz") as archive:
            return {
                m.name: archive.extractfile(m).read().decode("utf-8", "replace")
                for m in archive.getmembers() if m.isfile()
            }

    def test_busybox_and_host_awk_mask_addresses_and_keep_times(self):
        fixture = expand(
            "IPv4 __PVT_IP__ and __PUBLIC_IP__\n"
            "MAC __MAC__ __MAC_HYPHEN__ __MAC_DOT__\n"
            "IPv6 __ADDR6__ __ADDR6_LINK__ ::1\n"
            "subscriber __SN__\n"
            "clock 2026-11-12T01:22:33 18:42:59\n"
        )
        for runner in (["awk"], ["busybox", "awk"]):
            with self.subTest(command=runner):
                if not shutil.which(runner[0]):
                    self.skipTest("awk binary unavailable")
                proc = subprocess.run(
                    [*runner, "-f", str(REDACTOR)], input=fixture,
                    capture_output=True, text=True, timeout=15
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                for marker in ("__PVT_IP__", "__PUBLIC_IP__", "__MAC__",
                               "__MAC_HYPHEN__", "__MAC_DOT__", "__ADDR6__",
                               "__ADDR6_LINK__", "__SN__"):
                    self.assertNotIn(IDENTITIES[marker], proc.stdout, marker)
                for tag in ("IPv4", "IPv6", "MAC", "PON-SERIAL"):
                    self.assertIn("[" + tag + "-REDACTED]", proc.stdout)
                self.assertIn("2026-11-12T01:22:33 18:42:59", proc.stdout)

    def test_default_archive_privacy_end_to_end(self):
        proc, out = self.run_support()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.is_file())
        files = self.archived_text(out)
        for required in ("support/system_log.txt", "support/tc_filters.txt",
                         "support/fwenvs.txt"):
            self.assertIn(required, files)
        payload = "\n".join(files.values())
        for marker, value in IDENTITIES.items():
            self.assertNotIn(value, payload, marker)
        for secret in ("VERY_SENSITIVE_LOID", "VERY_SENSITIVE_PASSWORD",
                       "PRIVATEHASH", "CONFIG_VALUE"):
            self.assertNotIn(secret, payload)
        self.assertIn("root_pwhash=<redacted>", files["support/fwenvs.txt"])
        self.assertIn("ordinary_key=<redacted>", files["support/fwenvs.txt"])
        self.assertIn("mode=sanitized", files["support/collection-status.txt"])
        self.assertIn("2026-11-12T01:22:33 18:42:59",
                      files["support/system_log.txt"])
        for tag in ("IPv4", "IPv6", "MAC"):
            self.assertIn("[" + tag + "-REDACTED]",
                          files["support/tc_filters.txt"])
        self.assertIn("[PON-SERIAL-REDACTED]", files["support/system_log.txt"])
        self.assertNotIn("SENSITIVE_RAW_OMCI", payload)

    def test_missing_privacy_filter_fails_closed(self):
        text = self.support.read_text()
        self.assertEqual(text.count(str(REDACTOR)), 1)
        self.support.write_text(text.replace(str(REDACTOR),
                                             str(self.tmp / "missing.awk")))
        proc, out = self.run_support()
        self.assertEqual(proc.returncode, 74)
        self.assertFalse(out.exists())
        self.assertIn("privacy filter unavailable", proc.stderr)

    def test_explicit_full_is_not_silently_redacted(self):
        proc, out = self.run_support(["--full"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = self.archived_text(out)
        self.assertIn("mode=full", files["support/collection-status.txt"])
        self.assertIn("PRIVATEHASH", files["support/fwenvs.txt"])
        self.assertIn(IDENTITIES["__PUBLIC_IP__"],
                      files["support/tc_filters.txt"])
        self.assertIn("SENSITIVE_RAW_OMCI", files["support/omci_pipe_md.txt"])

    def test_oversized_redaction_fails_closed_without_raw_archive(self):
        self._fake("logread", """#!/bin/sh
python3 - <<'PY'
import sys
sys.stdout.write((".".join(("192", "168", "1", "1")) + " ") * 260000)
PY
""")
        proc, out = self.run_support(name="oversized.tar.gz")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(out.exists())

    def test_other_commands_omit_credential_lines_before_address_mask(self):
        self._fake("8311-tc-filter-dump.sh", """#!/bin/sh
printf 'token=UNSAFE_TC_TOKEN __PUBLIC_IP__\n'
printf 'normal filter __PUBLIC_IP2__\n'
""")
        proc, out = self.run_support()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = self.archived_text(out)["support/tc_filters.txt"]
        self.assertNotIn("UNSAFE_TC_TOKEN", text)
        self.assertIn("[IPv4-REDACTED]", text)
        self.assertIn("sensitive diagnostic line omitted", text)


if __name__ == "__main__":
    unittest.main()

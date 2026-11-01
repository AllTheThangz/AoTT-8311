"""Qualified vendor syslog forwarding command-contract tests.

The actual extracted vendor /etc/init.d/log is sourced into a host-side
mock of OpenWrt procd. Nothing starts logd, opens a socket, or forwards logs.
The test is optional in public source-only CI; when AOTT_VENDOR_ROOTFS is
explicitly provided, failure to find the source is a hard error.
"""
import os
from pathlib import Path
import subprocess
import unittest

VENDOR = Path(os.getenv("AOTT_VENDOR_ROOTFS", "/nonexistent/vendor/rootfs"))


class VendorSyslogTransportContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = VENDOR / "etc/init.d/log"
        if not cls.script.is_file():
            if "AOTT_VENDOR_ROOTFS" in os.environ:
                raise AssertionError("Explicit vendor logger source is missing")
            raise unittest.SkipTest("Optional vendor logging service unavailable")

    def run_service(self, **settings):
        config = {
            "log_remote": "1",
            "log_ip": "collector.example.com",
            "log_port": "5514",
            "log_proto": "udp",
            "log_hostname": "generic-onu",
            "log_trailer_null": "0",
            "log_prefix": "",
            "PIDCOUNT": "0",
        }
        config.update(settings)
        script = r'''
procd_open_instance() { printf 'OPEN\n'; }
procd_set_param() { printf 'SET'; printf ' <%s>' "$@"; printf '\n'; }
procd_append_param() { printf 'APPEND'; printf ' <%s>' "$@"; printf '\n'; }
procd_close_instance() { printf 'CLOSE\n'; }
. "$SOURCE_INIT"
start_service_remote synthetic-system 0
'''
        result = subprocess.run(
            ["/bin/sh", "-c", script], capture_output=True, text=True,
            timeout=6, env={**os.environ, **config,
                            "SOURCE_INIT": str(self.script)}
        )
        # The vendor callback returns nonzero when disabled/validation fails.
        # That is expected so long as no logread process is started.
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.stdout.splitlines()

    def test_udp_uses_existing_logread_without_new_agent(self):
        lines = self.run_service()
        self.assertEqual(lines[0], "OPEN")
        self.assertTrue(lines[-1] == "CLOSE")
        joined = "\n".join(lines)
        self.assertIn('SET <command> </sbin/logread> <-f>', joined)
        self.assertIn('<-r> <collector.example.com> <5514>', joined)
        self.assertIn('APPEND <command> <-u>', joined)
        self.assertNotIn("<-0>", joined)

    def test_tcp_excludes_udp_flag(self):
        lines = self.run_service(log_proto="tcp")
        joined = "\n".join(lines)
        self.assertIn('<-r> <collector.example.com> <5514>', joined)
        self.assertNotIn('<-u>', joined)
        self.assertNotIn('<-0>', joined)

    def test_tcp_optional_null_trailer_and_prefix(self):
        lines = self.run_service(log_proto="tcp",
                                 log_trailer_null="1",
                                 log_prefix="generic-prefix")
        joined = "\n".join(lines)
        self.assertIn('APPEND <command> <-0>', joined)
        self.assertIn('APPEND <command> <-P> <generic-prefix>', joined)

    def test_disabled_or_missing_receiver_never_starts_forwarder(self):
        self.assertEqual(self.run_service(log_remote="0"), [])
        self.assertEqual(self.run_service(log_ip=""), [])

    def test_failed_vendor_validation_never_starts_remote(self):
        self.assertEqual(self.run_service(log_remote="1",
                                          log_ip="collector.example.com",
                                          log_proto="udp", log_port="5514",
                                          **{"PIDCOUNT": "0"})[0], "OPEN")
        # The vendor procd service invokes the remote start callback with
        # validation result 1 on malformed configuration.
        script = r'''
procd_open_instance() { echo BAD; }
procd_set_param() { echo BAD; }
procd_append_param() { echo BAD; }
procd_close_instance() { echo BAD; }
. "$SOURCE_INIT"
log_remote=1 log_ip=collector.example.com log_port=5514
log_proto=udp log_hostname=generic-onu log_trailer_null=0
start_service_remote synthetic-system 1
'''
        proc = subprocess.run(
            ["/bin/sh", "-c", script], text=True, capture_output=True,
            timeout=6, env={**os.environ,"SOURCE_INIT":str(self.script)}
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("validation failed", proc.stdout)
        self.assertNotIn("BAD", proc.stdout)

    def test_vendor_schema_supports_udp_tcp_and_not_severity(self):
        s = self.script.read_text()
        self.assertIn('log_proto:or("tcp", "udp"):udp', s)
        self.assertIn("log_remote:bool:1", s)
        self.assertIn("log_ip:host", s)
        self.assertIn("log_port:port:514", s)
        # The forwarding path has an optional regex pattern for local file
        # logging, not a remote log severity threshold.
        remote = s.split("start_service_remote()", 1)[1].split(
            "service_triggers()", 1)[0]
        self.assertNotIn("log_level", remote)
        self.assertNotIn("log_pattern", remote)
        self.assertIn('case "${log_proto}" in', remote)


if __name__ == "__main__":
    unittest.main()

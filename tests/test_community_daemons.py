"""Exercise bounded copies of PRX126 monitoring scripts without device access.

No real ping, GPIO writes, PON commands, fwenv reads or syslog operations.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
PING=(ROOT/"overlay/usr/sbin/8311-pingd.sh").read_text()
LOS=(ROOT/"overlay/usr/sbin/8311-rx_los.sh").read_text()


class CommunityServiceOptimizationTest(unittest.TestCase):
    def run_ping(self,mode):
        with tempfile.TemporaryDirectory() as tmp:
            step=Path(tmp)/"step"
            step.write_text("0")
            old="while true ; do"
            self.assertEqual(PING.count(old),1)
            script=PING.replace(old,"for _aott_round in 1 2 3; do",1)
            helpers=r'''
_lib_8311() { :; }
fwenv_get_8311() {
    current=$(cat "$AOTT_TICK")
    current=$((current + 1))
    printf '%s\n' "$current" > "$AOTT_TICK"
    if [ "$AOTT_MODE" = "toggle" ] && [ "$current" -eq 2 ]; then
        printf '0\n'
    else
        printf '1\n'
    fi
}
get_8311_ping_host() { printf 'example.invalid\n'; }
to_console() { cat; }
ping() { return 0; }
sleep() { :; }
'''
            env={**os.environ,"AOTT_TICK":str(step),"AOTT_MODE":mode}
            p=subprocess.run(["/bin/sh","-c",helpers+"\n"+script],
                             env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(p.stderr,"")
            return p.stdout

    def test_repeated_target_logs_once(self):
        out=self.run_ping("steady")
        self.assertEqual(out.count("Starting ping to: "),1)
        self.assertNotIn("password",out.lower())

    def test_reenabled_target_logs_again(self):
        out=self.run_ping("toggle")
        self.assertEqual(out.count("Starting ping to: "),2)

    def test_monitoring_ping_semantics_preserved(self):
        self.assertIn('ping -i 5 "$PING_HOST" > /dev/null 2>&1 < /dev/null',PING)
        self.assertIn('sleep 5',PING)
        self.assertIn('sleep 30',PING)

    def test_gpio_poll_uses_shell_builtin_twice(self):
        self.assertEqual(LOS.count('IFS= read -r LOS_VALUE < "$GPIO/value"'),2)
        self.assertNotIn('cat "$GPIO/value"',LOS)

    def run_gpio(self,enabled):
        with tempfile.TemporaryDirectory() as tmp:
            gpio=Path(tmp)/"gpio505"
            gpio.mkdir()
            (gpio/"value").write_text("0\n")
            (gpio/"direction").write_text("low\n")
            orig='GPIO="/sys/class/gpio/gpio'+'$'+'{PIN}"'
            self.assertEqual(LOS.count(orig),1)
            script=LOS.replace(orig,'GPIO="$AOTT_GPIO"',1)
            export='[ -d "$GPIO" ] || echo "$PIN" > "/sys/class/gpio/export"'
            self.assertEqual(script.count(export),1)
            script=script.replace(export,":",1)
            self.assertEqual(script.count("while true; do"),2)
            script=script.replace("while true; do","for _aott_round in 1 2; do")
            helpers=r'''
_lib_8311() { :; }
fwenv_get_8311() { printf '%s\n' "$AOTT_RX_LOS"; }
to_console() { cat; }
sleep() { :; }
'''
            env={**os.environ,"AOTT_GPIO":str(gpio),
                 "AOTT_RX_LOS":"1" if enabled else "0"}
            p=subprocess.run(["/bin/sh","-c",helpers+"\n"+script],
                             env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            return p.stdout,(gpio/"direction").read_text()

    def test_disabled_gpio_poll_in_sandbox(self):
        output,direction=self.run_gpio(False)
        self.assertIn("start disabling",output)
        self.assertEqual(direction,"low\n")

    def test_enabled_gpio_poll_in_sandbox(self):
        output,direction=self.run_gpio(True)
        self.assertIn("start monitoring LOS alarm",output)
        self.assertEqual(direction,"low\n")


if __name__=="__main__":
    unittest.main()

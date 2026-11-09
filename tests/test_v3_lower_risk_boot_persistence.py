from pathlib import Path
import os, unittest

ROOT=Path(__file__).resolve().parents[1]
SYSINIT=ROOT/"overlay/etc/init.d/_8311-sysinit.sh"
DEFAULTS=ROOT/"overlay/etc/uci-defaults/zzz-8311"
LIB=ROOT/"overlay/lib/8311.sh"
ACT=ROOT/"overlay/usr/lib/lua/8311/config_activation.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class LowerRiskBootPersistenceContract(unittest.TestCase):
    def test_saved_fields_have_boot_consumers(self):
        sysinit=SYSINIT.read_text()
        defaults=DEFAULTS.read_text()
        lib=LIB.read_text()
        self.assertIn('SYS_HOSTNAME=$(get_8311_hostname)',sysinit)
        self.assertIn('set_8311_hostname "$SYS_HOSTNAME"',sysinit)
        self.assertIn('SYS_LANG=$(get_8311_lang)',sysinit)
        self.assertIn('set_8311_lang "$SYS_LANG"',sysinit)
        self.assertIn('uci set "luci.main.lang"="$SYS_LANG"',defaults)
        self.assertIn('uci set "system.@system[0].hostname"="$SYS_HOSTNAME"',defaults)
        self.assertIn('TIMEZONE=$(get_8311_timezone)',defaults)
        self.assertIn('uci set "system.@system[0].zonename"="$TIMEZONE"',defaults)
        self.assertIn('NTP_SERVERS=$(get_8311_ntp_servers)',defaults)
        self.assertIn('uci add_list "system.ntp.server"="$NTP_SERVER"',defaults)
        for getter in ("get_8311_hostname()","get_8311_lang()",
                       "get_8311_timezone()","get_8311_ntp_servers()"):
            self.assertIn(getter,lib)

    def test_live_and_boot_consumers_share_native_domains(self):
        live=ACT.read_text()
        defaults=DEFAULTS.read_text()
        self.assertIn('"luci","main","lang"',live)
        self.assertIn('"system",system_section,"hostname"',live)
        self.assertIn('"system",system_section,"zonename"',live)
        self.assertIn('"system",ntp_section,"server"',live)
        self.assertIn('uci commit "system"',defaults)
        self.assertIn('uci commit "luci"',defaults)

    def test_vendor_system_and_ntp_reload_consumers_exist(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        system=(VENDOR/"etc/init.d/system").read_text()
        ntp=(VENDOR/"etc/init.d/sysntpd").read_text()
        self.assertIn('echo "$hostname" > /proc/sys/kernel/hostname',system)
        self.assertIn('/usr/share/zoneinfo/${zonename// /_}',system)
        self.assertIn('procd_append_param command -p $peer',ntp)
        self.assertIn('procd_add_config_trigger "config.change" "system"',ntp)

    def test_no_false_hardware_reboot_claim(self):
        for path in (ACT,SYSINIT,DEFAULTS):
            self.assertNotIn("FULLY_QUALIFIED",path.read_text())

if __name__=="__main__":
    unittest.main()

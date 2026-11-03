"""H-016: source-only bounded history JSON/CSV and epoch separation.

Runs the real Lua sampler, aggregation and export model using synthetic
observations. No real PON, network, firmware bank or collector is accessed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
PROTOTYPE=ROOT/"prototypes/history"
EXPORT=PROTOTYPE/"8311/history_export.lua"
SAMPLER=PROTOTYPE/"8311/history_sampler.lua"
FIXTURE=ROOT/"tests/h016_history_export_fixture.lua"
HTML=PROTOTYPE/"ui/history.html"
CSS=PROTOTYPE/"ui/history.css"
JS=PROTOTYPE/"ui/history.js"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/unavailable/offline-vendor-rootfs"))


def invoke(command, emit=False):
    args=command+[str(FIXTURE),str(PROTOTYPE)]
    if emit:
        args.append("emit_json")
    return subprocess.run(args,cwd=ROOT,capture_output=True,text=True,
                          timeout=30)


def payloads():
    result=invoke(["lua5.1"],True)
    if result.returncode!=0:
        raise AssertionError(result.stderr)
    reports={}
    for line in result.stdout.splitlines():
        for prefix in ("AOTT_H016_JSON_PAYLOAD=",
                       "AOTT_H016_SPAN_JSON_PAYLOAD="):
            if line.startswith(prefix):
                reports[prefix]=json.loads(line[len(prefix):])
    if len(reports)!=2:
        raise AssertionError("Missing synthetic JSON fixtures")
    return reports["AOTT_H016_JSON_PAYLOAD="],reports["AOTT_H016_SPAN_JSON_PAYLOAD="]


class HistoryExportSourceTests(unittest.TestCase):
    def test_lua_51_host_fixture(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        result=invoke(["lua5.1"])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_H016_EXPORT_FIXTURE_PASS checks=104",
                      result.stdout)

    def test_offline_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted offline MIPS rootfs supplied")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        result=invoke(["qemu-mips-static","-L",str(VENDOR),
                       str(VENDOR/"usr/bin/lua")])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_H016_EXPORT_FIXTURE_PASS checks=104",
                      result.stdout)

    def test_lua51_source_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler unavailable")
        for path in (EXPORT,SAMPLER,FIXTURE):
            with self.subTest(source=path.name):
                result=subprocess.run(
                    ["luac5.1","-p",str(path)],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_json_valid_and_no_cross_reboot_data(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        ready,spanning=payloads()
        self.assertEqual(ready["kind"],"aott_source_only_history")
        self.assertTrue(ready["source_only_not_live"])
        self.assertTrue(ready["actual_isp_uptime_unverified"])
        self.assertTrue(ready["calendar_time_unverified"])
        self.assertTrue(ready["history_is_volatile"])
        self.assertTrue(ready["optics_history_unavailable"])
        self.assertEqual(len(ready["windows"]),5)
        self.assertEqual(len(ready["samples"]),6)
        self.assertLessEqual(len(ready["events"]),100)
        self.assertEqual(ready["windows"]["hour"]["rx"]["interval_count"],3)
        self.assertFalse(ready["windows"]["ninety_days"]["window_complete"])
        self.assertEqual(ready["max_export_items"],100)
        self.assertEqual(len(spanning["samples"]),3)
        self.assertEqual(spanning["windows"]["hour"]["excluded_cross_window_intervals"],1)
        for p in (ready,spanning):
            data=json.dumps(p)
            for marker in ("boot-A","boot-C","RxGoodBytes",
                           "registration_credential","raw_output",
                           "destination","subscriber_mac"):
                self.assertNotIn(marker,data)

    def test_no_auto_collectors_or_firmware_overlay_change(self):
        for source in (EXPORT,HTML,CSS,JS):
            self.assertTrue(source.is_file())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/history_export.lua").exists())
        self.assertFalse((ROOT/"overlay/www/history.html").exists())
        self.assertNotIn("history_export.lua",
                         (ROOT/"MANIFEST.json").read_text())
        active="\n".join(line for line in EXPORT.read_text().splitlines()
                         if not line.lstrip().startswith("--"))
        for forbidden in ("io.open(","io.popen(","os.execute(",
                          "socket.","fwenv_set","uci:commit",
                          "luci.http","/usr/bin/pon","ethtool",
                          "setInterval","cron(","sleep("):
            self.assertNotIn(forbidden,active)

    def test_strict_boundaries_and_two_data_formats(self):
        source=EXPORT.read_text()
        for required in (
            "local MAX_RAW=100",
            "local MAX_EXPORT_BYTES=65536",
            "function M.project(state,range,limit)",
            "function M.export_json(state,range,limit)",
            "function M.export_csv(state,range,limit)",
            "value.epoch_index==state.epoch_index",
            "raw_tail_independent_of_selected_range=true",
            'source_only_not_live=true',
            'actual_isp_uptime_unverified=true',
            'optics_history_unavailable=true',
            'calendar_time_unverified=true',
            'return nil,"export_too_large"',
            'return nil,"invalid_export_range"',
        ):
            with self.subTest(required=required):
                self.assertIn(required,source)

    def test_source_preview_is_not_an_authenticated_live_luci_page(self):
        html=HTML.read_text()
        js=JS.read_text()
        css=CSS.read_text()
        for label in ("Source-only preview","Last 90 days",
                      "Not verified","Not collected","Export JSON",
                      "Export CSV","Observed state changes"):
            self.assertIn(label,html)
        self.assertIn("window.AoTTHistoryView=",js)
        self.assertIn("render:render",js)
        self.assertIn("exportJSON:toJSON",js)
        self.assertIn("exportCSV:toCSV",js)
        self.assertIn("document.createElementNS",js)
        self.assertIn("textContent",js)
        for forbidden in ("fetch(","XMLHttpRequest","WebSocket(",
                          "navigator.sendBeacon","eval(","new Function("):
            self.assertNotIn(forbidden,js)
        self.assertIn('html[data-aott-theme="dark"]',css)
        self.assertIn('html[data-aott-theme="light"]',css)


if __name__=="__main__":
    unittest.main()

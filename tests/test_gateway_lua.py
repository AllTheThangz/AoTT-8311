"""Exercise the actual Lua configuration planner without contacting a device.

The saved legacy gateway must be shown, preserved through unrelated saves,
and rejected as a *new* self-gateway. Clearing it must be an explicit edit.
"""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "overlay/usr/lib/lua/8311/config.lua"

class GatewayLuaMigrationTests(unittest.TestCase):
    def run_case(self, saved_gateway, proposed_gateway, saved_ip="192.0.2.10",
                 proposed_ip=None, new_hostname="new-test-host"):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 not installed on this test runner")
        proposed_ip = proposed_ip or saved_ip
        script=r"""
package.preload["8311.tools"] = function()
    return {fwenv_read_all=function()
        return {["8311_ipaddr"]=SAVED_IP, ["8311_netmask"]="255.255.255.0",
                ["8311_gateway"]=SAVED_GATEWAY, ["8311_hostname"]="old-test-host"}
    end}
end
package.preload["8311.webutil"] = function()
    return {digest_text=function() return "revision-token" end,
            read_json=function() return nil end}
end
package.preload["nixio.fs"] = function() return {} end
package.preload["base64"] = function() return {enc=function(x) return x end,
                                                  dec=function(x) return x end} end
package.preload["luci.jsonc"] = function() return {} end
local config = assert(loadfile(CONFIG_PATH))()
local schema={{items={
    {id="ipaddr",type="text",pattern="ipv4",default="192.168.11.1"},
    {id="netmask",type="text",pattern="ipv4",default="255.255.255.0"},
    {id="gateway",type="text",pattern="ipv4",default=""},
    {id="hostname",type="text",maxlength=64}
}}}
local snap=assert(config.snapshot(schema))
local form={complete="8311-v1", revision=snap.revision, mode="preview",
            ipaddr=PROPOSED_IP, netmask="255.255.255.0",
            gateway=PROPOSED_GATEWAY, hostname=NEW_HOSTNAME}
local plan,err,status=config.prepare(snap,form)
print("displayed_gateway="..snap.items[3].value)
if not plan then
    print("status="..tostring(status))
    print("gateway_error="..tostring(err.gateway or ""))
else
    print("status=200")
    local ids={}
    for _,change in ipairs(plan.changes) do ids[#ids+1]=change.item.id end
    print("changed="..table.concat(ids,","))
end
""".replace("SAVED_IP",json.dumps(saved_ip)).replace(
    "PROPOSED_IP",json.dumps(proposed_ip)).replace(
    "SAVED_GATEWAY",json.dumps(saved_gateway)).replace(
    "PROPOSED_GATEWAY",json.dumps(proposed_gateway)).replace(
    "NEW_HOSTNAME",json.dumps(new_hostname)).replace(
    "CONFIG_PATH",json.dumps(str(CONFIG)))
        p=subprocess.run(["lua5.1","-"],input=script,text=True,
                         capture_output=True,timeout=6)
        self.assertEqual(p.returncode,0,p.stderr)
        return dict(line.split("=",1) for line in p.stdout.splitlines() if "=" in line)

    def test_saved_self_route_remains_visible_and_untouched_on_unrelated_save(self):
        result=self.run_case("192.0.2.10","192.0.2.10")
        self.assertEqual(result["displayed_gateway"],"192.0.2.10")
        self.assertEqual(result["status"],"200")
        self.assertEqual(result["changed"],"hostname")

    def test_explicitly_clearing_saved_gateway_is_allowed_and_recorded(self):
        result=self.run_case("192.0.2.10","")
        self.assertEqual(result["status"],"200")
        self.assertIn("gateway",result["changed"])

    def test_blank_gateway_stays_blank(self):
        result=self.run_case("","")
        self.assertEqual(result["status"],"200")
        self.assertEqual(result["changed"],"hostname")

    def test_new_self_gateway_is_rejected(self):
        result=self.run_case("","192.0.2.10")
        self.assertEqual(result["status"],"422")
        self.assertIn("New self-address",result["gateway_error"])

    def test_valid_router_migration_is_supported(self):
        result=self.run_case("192.0.2.10","192.0.2.1")
        self.assertEqual(result["status"],"200")
        self.assertIn("gateway",result["changed"])

    def test_ip_change_cannot_reuse_legacy_route_without_review(self):
        result=self.run_case("192.0.2.10","192.0.2.10",proposed_ip="192.0.2.20")
        self.assertEqual(result["status"],"422")
        self.assertIn("explicitly replacing",result["gateway_error"])

    def test_ip_change_with_explicit_new_router_is_supported(self):
        result=self.run_case("192.0.2.10","192.0.2.1",proposed_ip="192.0.2.20")
        self.assertEqual(result["status"],"200")

    def test_saved_custom_router_is_not_rewritten(self):
        result=self.run_case("192.0.2.1","192.0.2.1")
        self.assertEqual(result["status"],"200")
        self.assertEqual(result["changed"],"hostname")

if __name__=="__main__":
    unittest.main()

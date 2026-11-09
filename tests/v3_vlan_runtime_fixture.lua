local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local env={fix_vlans="1",internet_vlan="35",services_vlan="36"}
local daemon=true
local receipt_present=true
local topology=string.rep("a",64)
local receipt=table.concat({
    "FIX_ENABLED=1",
    "INTERNET_VLAN=35",
    "SERVICES_VLAN=36",
    "STATE_HASH="..topology,
    ""
},"\n")

package.preload["nixio.fs"]=function()
    return {
        lstat=function(path)
            if path=="/tmp/8311-config.sh" and receipt_present then
                return {type="reg",uid=0,modedec=600,nlink=1,size=#receipt}
            end
        end,
        readfile=function(path)
            if path=="/tmp/8311-config.sh" and receipt_present then return receipt end
        end,
    }
end
package.preload["8311.webutil"]=function()
    return {
        capture=function(argv)
            local command=table.concat(argv," ")
            if command:find("/usr/sbin/fwenv_get --8311 ",1,true) then
                local id=argv[#argv]
                return 0,(env[id] or "").."\n",false
            elseif command:find("/bin/pidof 8311-vlansd.sh",1,true) then
                return daemon and 0 or 1,daemon and "123\n" or "",false
            elseif command:find("/usr/sbin/8311-detect-config.sh -H",1,true) then
                return 0,topology.."\n",false
            end
            return 1,"",false
        end,
    }
end

local runtime=require "8311.vlan_runtime"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"VLAN_RUNTIME_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end

local ok,value,source=runtime.matches("fix_vlans","1")
same(ok,true,"builtin_mode")
same(value,"1","builtin_mode_value")
same(source,"builtin_vlan_reconciliation_receipt","builtin_source")

ok,value=runtime.matches("internet_vlan","35")
same(ok,true,"internet_match")
same(value,"35","internet_value")
ok,value=runtime.matches("services_vlan","36")
same(ok,true,"services_match")
same(value,"36","services_value")
ok,value=runtime.matches("services_vlan","")
same(ok,true,"services_autodetect")
same(value,"auto-detected","services_autodetect_value")

topology=string.rep("b",64)
ok=runtime.matches("internet_vlan","35")
same(ok,false,"stale_topology_refused")
topology=string.rep("a",64)

env.fix_vlans="0";daemon=false;receipt_present=false
ok,value,source=runtime.matches("fix_vlans","0")
same(ok,true,"disabled_verified")
same(value,"0","disabled_value")
same(source,"builtin_vlan_translation_disabled","disabled_source")
ok,value,source=runtime.matches("internet_vlan","35")
same(ok,nil,"disabled_internet_inactive")
same(source,"vlan_translation_disabled_setting_inactive","disabled_inactive_source")

env.fix_vlans="2";daemon=true
ok,value,source=runtime.matches("fix_vlans","2")
same(ok,nil,"hook_only_pending")
same(source,"hook_only_runtime_effect_requires_hook_specific_proof","hook_pending_source")

receipt_present=true
ok=runtime.matches("fix_vlans","2")
same(ok,false,"hook_stale_receipt_refused")

same(checks>=16,true,"coverage")
print("AOTT_V3_VLAN_RUNTIME_PASS checks="..checks)

-- AoTT-8311 V3 runtime verifier for the three ISP/VLAN controls.
-- Uses only the private reconciliation receipt, current topology hash and daemon
-- identity. It never executes the receipt or treats hook-only mode as proven.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local model=require "8311.effective_vlan_state"
local M={}

local RECEIPT="/tmp/8311-config.sh"
local IDS={fix_vlans=true,internet_vlan=true,services_vlan=true}

local function env(id)
    if not IDS[id] then return nil end
    local code,out,overflow=web.capture({"/usr/sbin/fwenv_get","--8311",id},160)
    if code~=0 or overflow or type(out)~="string" then return nil end
    out=out:gsub("[\r\n]+$","")
    if #out>80 or out:find("[%z\1-\31\127]") then return nil end
    return out
end

local function receipt()
    local st=fs.lstat(RECEIPT)
    if not st then return nil,"absent" end
    if st.type~="reg" or st.uid~=0 or st.modedec~=600 or st.nlink~=1 or
       type(st.size)~="number" or st.size<1 or st.size>4096 then
        return nil,"unsafe"
    end
    local raw=fs.readfile(RECEIPT,4097)
    local parsed,why=model.parse_last_reconciliation(raw)
    if not parsed then return nil,why or "invalid" end
    return parsed
end

local function daemon()
    local code,out,overflow=web.capture({"/bin/pidof","8311-vlansd.sh"},256)
    if code==1 and not overflow then return false end
    if code~=0 or overflow or type(out)~="string" then return nil end
    return out:match("%d")~=nil
end

local function topology_hash()
    local code,out,overflow=web.capture({
        "/usr/bin/timeout","-k","1","5","/usr/sbin/8311-detect-config.sh","-H"
    },96)
    if code~=0 or overflow or type(out)~="string" then return nil end
    out=out:gsub("[\r\n]+$","")
    if #out~=64 or not out:match("^[0-9a-f]+$") then return nil end
    return out
end

function M.snapshot()
    local saved={
        fix_vlans=env("fix_vlans"),
        internet_vlan=env("internet_vlan"),
        services_vlan=env("services_vlan"),
    }
    if saved.fix_vlans=="" or saved.fix_vlans==nil then saved.fix_vlans="1" end
    if saved.internet_vlan=="" or saved.internet_vlan==nil then saved.internet_vlan="0" end
    local running=daemon()
    if running==nil then return nil,"vlan_daemon_state_unavailable" end
    local rec,receipt_state=receipt()
    local hash=rec and topology_hash() or nil
    return {
        saved=saved,daemon_running=running,receipt=rec,
        receipt_state=receipt_state,current_topology_hash=hash,
    }
end

function M.matches(id,desired)
    if not IDS[id] or type(desired)~="string" then
        return false,nil,"vlan_runtime_request_invalid"
    end
    local state,why=M.snapshot()
    if not state then return false,nil,why end
    local mode=state.saved.fix_vlans
    if mode=="0" then
        if state.daemon_running or state.receipt~=nil then
            return false,nil,"vlan_disabled_cleanup_incomplete"
        end
        if id=="fix_vlans" then return desired=="0","0","builtin_vlan_translation_disabled" end
        return nil,nil,"vlan_translation_disabled_setting_inactive"
    elseif mode=="2" then
        if not state.daemon_running or state.receipt~=nil then
            return false,nil,"vlan_hook_only_transition_incomplete"
        end
        return nil,nil,"hook_only_runtime_effect_requires_hook_specific_proof"
    elseif mode~="1" then
        return false,nil,"vlan_mode_unqualified"
    end
    local rec=state.receipt
    if not state.daemon_running or not rec or
       state.current_topology_hash~=rec.topology_hash then
        return false,nil,"vlan_builtin_reconciliation_unverified"
    end
    if id=="fix_vlans" then return desired=="1","1","builtin_vlan_reconciliation_receipt" end
    if id=="internet_vlan" then
        local expected=desired=="" and "0" or desired
        return rec.internet_vlan==expected,rec.internet_vlan,
               "builtin_vlan_reconciliation_receipt"
    end
    if desired=="" then
        return true,"auto-detected","builtin_vlan_reconciliation_auto_services"
    end
    return rec.services_vlan==desired,rec.services_vlan,
           "builtin_vlan_reconciliation_receipt"
end

return M

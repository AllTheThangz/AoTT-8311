-- AoTT-8311 V3 management-dependent SSH binding transaction.
-- The management interface can move between logical lct and mgmt. Dropbear's
-- DirectInterface must move with it or SSH recovery can remain on the old path.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local uci_lib=require "luci.model.uci"
local M={}

local MAX_EXPORT=32768
local ALLOWED={lct=true,mgmt=true}

local function desired(vlan)
    if type(vlan)=="string" and vlan:match("^%d+$") then vlan=tonumber(vlan) end
    if type(vlan)~="number" or vlan~=math.floor(vlan) or vlan<0 or vlan>4094 then
        return nil,"management_access_vlan_invalid"
    end
    return vlan>0 and "mgmt" or "lct"
end

local function section(cursor)
    local found={}
    cursor:foreach("dropbear","dropbear",function(s)
        if type(s)== "table" and type(s[".name"])=="string" then
            found[#found+1]=s[".name"]
        end
    end)
    if #found~=1 then return nil,"dropbear_instance_not_unique" end
    return found[1]
end

local function export_raw()
    local code,out,overflow=web.capture({"/sbin/uci","export","dropbear"},MAX_EXPORT)
    if code~=0 or overflow or type(out)~="string" or #out<1 or #out>MAX_EXPORT or out:find("%z") then
        return nil,"dropbear_export_failed"
    end
    return out
end

function M.snapshot()
    local cursor=uci_lib.cursor()
    local name,why=section(cursor)
    if not name then return nil,why end
    local current=cursor:get("dropbear",name,"DirectInterface")
    if current==nil or current=="" then
        return nil,"dropbear_direct_interface_unset"
    end
    if not ALLOWED[current] then return nil,"dropbear_direct_interface_unqualified" end
    local raw,raw_why=export_raw()
    if not raw then return nil,raw_why end
    return {raw=raw,section=name,direct_interface=current}
end

function M.apply(snapshot,vlan)
    if type(snapshot)~="table" or type(snapshot.section)~="string" or
       type(snapshot.direct_interface)~="string" or type(snapshot.raw)~="string" then
        return nil,"dropbear_snapshot_invalid"
    end
    local target,why=desired(vlan)
    if not target then return nil,why end
    local cursor=uci_lib.cursor()
    local name,current_why=section(cursor)
    if not name then return nil,current_why end
    if name~=snapshot.section then return nil,"dropbear_instance_changed" end
    local current=cursor:get("dropbear",name,"DirectInterface")
    if current~=snapshot.direct_interface then return nil,"dropbear_binding_changed" end
    if current==target then return {changed=false,target=target} end
    if cursor:set("dropbear",name,"DirectInterface",target)~=true or
       cursor:commit("dropbear")~=true then
        return nil,"dropbear_binding_write_failed"
    end
    if cursor:get("dropbear",name,"DirectInterface")~=target then
        return nil,"dropbear_binding_readback_failed"
    end
    return {changed=true,target=target}
end

function M.import_raw(file)
    local expected="/ptconf/8311/aott-recovery/v1/management/dropbear.before"
    if file~=expected then return nil,"dropbear_restore_scope_refused" end
    local st=fs.lstat(file)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
       st.modedec~=600 or st.nlink~=1 or type(st.size)~="number" or
       st.size<1 or st.size>MAX_EXPORT then return nil,"dropbear_restore_file_unsafe" end
    local code,_,overflow=web.capture({"/sbin/uci","-f",file,"import","dropbear"},4096)
    if code~=0 or overflow then return nil,"dropbear_restore_import_failed" end
    code,_,overflow=web.capture({"/sbin/uci","commit","dropbear"},4096)
    if code~=0 or overflow then return nil,"dropbear_restore_commit_failed" end
    return true
end

function M.reload()
    local code,_,overflow=web.capture({"/etc/init.d/dropbear","restart"},4096)
    if code~=0 or overflow then return nil,"dropbear_restart_failed" end
    return true
end

local function master_bound(expected_device)
    local code,out,overflow=web.capture({"/bin/pidof","dropbear"},512)
    if code~=0 or overflow or type(out)~="string" then return nil,"dropbear_pid_unavailable" end
    local found=false
    for pid in out:gmatch("%d+") do
        local raw=fs.readfile("/proc/"..pid.."/cmdline",4096)
        if type(raw)=="string" and raw:find("^/usr/sbin/dropbear%z") then
            local argv={}
            for part in raw:gmatch("([^%z]+)") do argv[#argv+1]=part end
            local foreground=false
            local binding=nil
            local i=1
            while i<=#argv do
                if argv[i]=="-F" then foreground=true;i=i+1
                elseif argv[i]=="-l" and type(argv[i+1])=="string" then
                    binding=argv[i+1];i=i+2
                else i=i+1 end
            end
            if foreground and binding==expected_device then found=true end
        end
    end
    return found or nil,found and nil or "dropbear_master_binding_mismatch"
end

function M.verify(vlan)
    local target,why=desired(vlan)
    if not target then return nil,why end
    local cursor=uci_lib.cursor()
    local name,swhy=section(cursor)
    if not name then return nil,swhy end
    if cursor:get("dropbear",name,"DirectInterface")~=target then
        return nil,"dropbear_uci_binding_mismatch"
    end
    local expected_device=target=="mgmt" and "mgmt" or "eth0_0_1_lct"
    local ok,pwhy=master_bound(expected_device)
    if not ok then return nil,pwhy end
    return {
        status="MANAGEMENT_SSH_BINDING_VERIFIED",
        logical_interface=target,
        process_binding_verified=true,
        contains_configuration_values=false,
    }
end

function M.preflight(vlan)
    local target,why=desired(vlan)
    if not target then return nil,why end
    local snap,swhy=M.snapshot()
    if not snap then return nil,swhy end
    return {
        status="MANAGEMENT_SSH_BINDING_PREFLIGHT",
        current_interface=snap.direct_interface,
        requested_interface=target,
        change_required=snap.direct_interface~=target,
        supported_current_binding=true,
        contains_configuration_values=false,
    }
end

M.desired=desired
return M

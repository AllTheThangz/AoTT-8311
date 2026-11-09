-- AoTT-8311 V3 production UCI adapter for guarded management transactions.
-- Package scope is fixed to network/firewall and all operations originate from
-- the validated private vlan_transition plan.
local web=require "8311.webutil"
local fs=require "nixio.fs"
local uci_lib=require "luci.model.uci"
local transition=require "8311.vlan_transition"
local M={}
local PACKAGES={network=true,firewall=true}

local function export(package)
    if not PACKAGES[package] then return nil,"management_uci_package_refused" end
    local code,out,overflow=web.capture({"/sbin/uci","export",package},65536)
    if code~=0 or overflow or type(out)~="string" or #out<1 then
        return nil,"management_uci_export_failed"
    end
    local parsed,why=transition.parse_export(out,package)
    if not parsed then return nil,why or "management_uci_export_invalid" end
    return out,parsed
end

function M.snapshot()
    local network_raw,network=export("network")
    if not network then return nil,network_raw end
    local firewall_raw,firewall=export("firewall")
    if not firewall then return nil,firewall_raw end
    return {network=network,firewall=firewall},
           {network=network_raw,firewall=firewall_raw}
end

local function split_operation(argument)
    if type(argument)~="string" or #argument<1 or #argument>4096 or
       argument:find("[%z\1-\31\127]") then return nil end
    local lhs,value=argument:match("^([^=]+)=(.*)$")
    if not lhs then lhs=argument end
    local package,section,option=lhs:match("^([^.]+)%.([^.]+)%.(.+)$")
    if not package then package,section=lhs:match("^([^.]+)%.(.+)$") end
    if not PACKAGES[package] or type(section)~="string" or #section>64 then return nil end
    if option and (#option>64 or option:find("[^A-Za-z0-9_]")) then return nil end
    return package,section,option,value
end

function M.adapter()
    local cursor=uci_lib.cursor()
    local adapter={production_runtime=true}

    function adapter.snapshot()
        local value=M.snapshot()
        return value
    end
    function adapter.persisted_snapshot()
        local value=M.snapshot()
        return value
    end
    function adapter.command(op)
        if type(op)~="table" or #op~=2 or type(op[1])~="string" then return false end
        local verb,arg=op[1],op[2]
        if verb=="commit" then
            return PACKAGES[arg] and cursor:commit(arg)==true
        end
        local package,section,option,value=split_operation(arg)
        if not package then return false end
        if verb=="delete" then
            return cursor:delete(package,section,option)==true
        elseif verb=="set" then
            if value==nil then return false end
            if option then return cursor:set(package,section,option,value)==true end
            return cursor:set(package,section,value)==true
        elseif verb=="add_list" then
            if not option or value==nil then return false end
            return cursor:add_list(package,section,option,value)==true
        end
        return false
    end
    return adapter
end

function M.apply(handle)
    local adapter=M.adapter()
    return transition.verify_staged(handle,adapter,"production_runtime")
end

function M.export_raw(package)
    local raw,parsed=export(package)
    if not parsed then return nil,raw end
    return raw
end

local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~="table" then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end

function M.import_raw(package,file)
    if not PACKAGES[package] or type(file)~="string" then
        return nil,"management_uci_restore_scope_refused"
    end
    local expected_prefix="/ptconf/8311/aott-recovery/v1/management/"
    local expected_file=expected_prefix..package..".before"
    if file~=expected_file then
        return nil,"management_uci_restore_scope_refused"
    end
    local st=fs.lstat(file)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
       st.modedec~=600 or st.nlink~=1 or type(st.size)~="number" or
       st.size<1 or st.size>65536 then
        return nil,"management_uci_restore_file_unsafe"
    end
    local raw=fs.readfile(file,65537)
    if type(raw)~="string" or #raw~=st.size then
        return nil,"management_uci_restore_file_read_failed"
    end
    local expected,parse_why=transition.parse_export(raw,package)
    if not expected then return nil,parse_why or "management_uci_restore_file_invalid" end
    local code,_,overflow=web.capture({"/sbin/uci","-f",file,"import",package},4096)
    if code~=0 or overflow then return nil,"management_uci_import_failed" end
    code,_,overflow=web.capture({"/sbin/uci","commit",package},4096)
    if code~=0 or overflow then return nil,"management_uci_commit_failed" end
    local _,actual=export(package)
    if not actual or not equal(expected,actual) then
        return nil,"management_uci_restore_readback_failed"
    end
    return true
end

return M

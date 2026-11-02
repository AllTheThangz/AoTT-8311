-- AoTT-8311 C-011: bounded read-only ISP VLAN snapshot probe.
-- Only three fixed environment names; no PON IDs, registration secrets,
-- hook script execution, TC mutations, saved files or flash writes.
local M={}
local model=require "8311.effective_vlan_state"
local NAME_MAP={"fix_vlans","internet_vlan","services_vlan"}

local function strip(value,limit)
    if type(value)~="string" or #value>(limit or 80)+2 then
        return nil
    end
    value=value:gsub("[\r\n]+$","")
    if #value>(limit or 80) or value:find("[%z\1-\31\127]") then
        return nil
    end
    return value
end

function M.capture(adapter)
    if type(adapter)~="table" or
       type(adapter.environment)~="function" or
       type(adapter.last_receipt)~="function" or
       type(adapter.daemon_status)~="function" or
       type(adapter.network_hash)~="function" then
        return nil,"invalid_readonly_vlan_adapter"
    end
    local function safe(fn,...)
        local ok,value=pcall(fn,...)
        if ok then return value end
        return nil
    end
    local saved={}
    for _,id in ipairs(NAME_MAP) do
        saved[id]=strip(safe(adapter.environment,id),80)
    end
    local snapshot=safe(adapter.last_receipt)
    if type(snapshot)~="string" or #snapshot>4096 then
        snapshot=nil
    end
    local parsed=snapshot and model.parse_last_reconciliation(snapshot)
    local current_hash
    if parsed then
        current_hash=strip(safe(adapter.network_hash),80)
    end
    local daemon=safe(adapter.daemon_status)
    if type(daemon)~="boolean" then daemon=nil end
    return model.inspect(saved,snapshot,current_hash,daemon)
end

-- Only for authenticated LuCI administrator GET handler.
-- The original reconciler publishes /tmp/8311-config.sh after matching
-- expected TC rules, but that file is historical, not proof of live TC.
function M.live_vlan()
    local ok,report=pcall(function()
        local fs=require "nixio.fs"
        local web=require "8311.webutil"
        local allowed={}
        for _,id in ipairs(NAME_MAP) do allowed[id]=true end

        local function bounded(argv,limit)
            local code,out,overflow=web.capture(argv,limit)
            if code==0 and not overflow and type(out)=="string" then
                return out,0
            end
            return nil,code
        end

        return M.capture({
            environment=function(id)
                if not allowed[id] then return nil end
                return bounded({"/usr/bin/timeout","-k","1","3",
                    "/usr/sbin/fwenv_get","--8311",id},160)
            end,
            last_receipt=function()
                local path="/tmp/8311-config.sh"
                local st=fs.lstat(path)
                if not st or st.type~="reg" or st.uid~=0 or
                   st.modedec~=600 or type(st.size)~="number" or
                   st.size<=0 or st.size>4096 then
                    return nil
                end
                -- A symlink or world-readable file is never trusted.
                return fs.readfile(path,4097)
            end,
            daemon_status=function()
                local output,code=bounded({"/usr/bin/timeout","-k","1","2",
                    "/bin/pidof","8311-vlansd.sh"},160)
                if output and output:match("%d") then return true end
                if code==1 then return false end
                return nil
            end,
            network_hash=function()
                local output=bounded({"/usr/bin/timeout","-k","1","5",
                    "/usr/sbin/8311-detect-config.sh","-H"},96)
                return output
            end,
        })
    end)
    if not ok or type(report)~="table" or report.schema~=1 then
        return nil,"read_only_vlan_probe_unavailable"
    end
    return report
end

return M

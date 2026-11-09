-- AoTT-8311 V3 firmware one-shot trial watchdog.
-- Local-only. Never depends on Internet, DNS, router reachability, or a remote
-- management session. An unconfirmed running firmware trial returns to the
-- committed bank after the bounded timeout.
local fs=require "nixio.fs"
local nixio=require "nixio"
local json=require "luci.jsonc"
local web=require "8311.webutil"

local M={}
local ROOT="/var/run/aott-firmware-trial"
local STATE=ROOT.."/state"
local CONFIRMED=ROOT.."/confirmed"
local WAIT_SECONDS=180
local STEP_SECONDS=2

local function valid_bank(value)
    return value=="A" or value=="B"
end

local function valid_boot_id(value)
    return type(value)=="string" and #value==36 and
        value:match("^[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+$")~=nil
end

local function valid_status(s)
    return type(s)=="table" and s.schema==1 and
        valid_bank(s.active) and valid_bank(s.committed) and
        (s.pending==nil or valid_bank(s.pending)) and
        type(s.running_trial)=="boolean" and s.boot_contract==true and
        s.running_trial==(s.active~=s.committed)
end

local function state_text(boot_id,active,committed)
    if not valid_boot_id(boot_id) or not valid_bank(active) or not valid_bank(committed) then
        return nil
    end
    return table.concat({
        "schema=1",
        "boot_id="..boot_id,
        "active="..active,
        "committed="..committed,
        ""
    },"\n")
end

local function parse_state(data)
    if type(data)~="string" or #data>160 or data:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil
    end
    local out={}
    for line in (data.."\n"):gmatch("(.-)\n") do
        if line~="" then
            local k,v=line:match("^([a-z_]+)=([^=\r\n]+)$")
            if not k or out[k]~=nil then return nil end
            out[k]=v
        end
    end
    if out.schema~="1" or not valid_boot_id(out.boot_id) or
       not valid_bank(out.active) or not valid_bank(out.committed) then
        return nil
    end
    return out
end

local function same_state(a,b)
    return type(a)=="table" and type(b)=="table" and
        a.boot_id==b.boot_id and a.active==b.active and a.committed==b.committed
end

local function production_provider()
    local P={}
    function P.bank_status()
        local code,out,overflow=web.capture({"/usr/sbin/8311-bankctl.sh","status"},32768)
        if code~=0 or overflow or type(out)~="string" then
            return nil,"firmware_trial_bank_status_unavailable"
        end
        local parsed=json.parse(out)
        if not valid_status(parsed) then return nil,"firmware_trial_bank_status_invalid" end
        return parsed
    end
    function P.boot_id()
        local value=fs.readfile("/proc/sys/kernel/random/boot_id",80)
        if type(value)~="string" then return nil,"firmware_trial_boot_id_unavailable" end
        value=value:gsub("[\r\n]+$","")
        if not valid_boot_id(value) then return nil,"firmware_trial_boot_id_invalid" end
        return value
    end
    function P.prepare_root()
        local parent=fs.lstat("/var/run")
        if not parent or parent.type~="dir" or parent.uid~=0 or parent.gid~=0 or
           (parent.modedec~=755 and parent.modedec~=750 and parent.modedec~=700) then
            return nil,"firmware_trial_runtime_parent_unsafe"
        end
        local st=fs.lstat(ROOT)
        if not st then
            if not fs.mkdir(ROOT,700) then return nil,"firmware_trial_runtime_create_failed" end
            st=fs.lstat(ROOT)
        end
        if not st or st.type~="dir" or st.uid~=0 or st.gid~=0 or st.modedec~=700 then
            return nil,"firmware_trial_runtime_unsafe"
        end
        return true
    end
    local function atomic_write(path,data)
        local tmp=path..".new."..tostring(nixio.getpid())
        if fs.lstat(tmp) then return nil,"firmware_trial_stage_exists" end
        local fd=nixio.open(tmp,nixio.open_flags("wronly","creat","excl"),600)
        if not fd then return nil,"firmware_trial_stage_create_failed" end
        local wrote=fd:writeall(data)
        local synced=wrote==#data and fd:sync()
        local closed=fd:close()
        if not synced or not closed then fs.unlink(tmp); return nil,"firmware_trial_stage_write_failed" end
        local st=fs.lstat(tmp)
        if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or st.modedec~=600 or
           st.nlink~=1 or st.size~=#data then
            fs.unlink(tmp); return nil,"firmware_trial_stage_unsafe"
        end
        if not fs.rename(tmp,path) then fs.unlink(tmp); return nil,"firmware_trial_stage_rename_failed" end
        return true
    end
    function P.write_state(record)
        local data=state_text(record.boot_id,record.active,record.committed)
        if not data then return nil,"firmware_trial_state_invalid" end
        return atomic_write(STATE,data)
    end
    function P.write_confirmed(record)
        local data=state_text(record.boot_id,record.active,record.committed)
        if not data then return nil,"firmware_trial_confirm_invalid" end
        return atomic_write(CONFIRMED,data)
    end
    function P.read_confirmed()
        local st=fs.lstat(CONFIRMED)
        if not st then return nil,"absent" end
        if st.type~="reg" or st.uid~=0 or st.gid~=0 or st.modedec~=600 or
           st.nlink~=1 or type(st.size)~="number" or st.size>160 then
            return nil,"firmware_trial_confirm_unsafe"
        end
        local row=parse_state(fs.readfile(CONFIRMED,161))
        if not row then return nil,"firmware_trial_confirm_invalid" end
        return row
    end
    function P.monotonic()
        local value=fs.readfile("/proc/uptime",64)
        if type(value)~="string" then return nil,"firmware_trial_uptime_unavailable" end
        local first=value:match("^([0-9]+%.?[0-9]*)")
        local seconds=tonumber(first)
        if not seconds or seconds<0 then return nil,"firmware_trial_uptime_invalid" end
        return seconds
    end
    function P.sleep(seconds)
        seconds=tonumber(seconds)
        if not seconds or seconds<=0 then return true end
        nixio.nanosleep(seconds,0)
        return true
    end
    function P.rollback()
        local code,_,overflow=web.capture({"/usr/sbin/8311-bankctl.sh","rollback"},4096)
        return code==0 and not overflow
    end
    return P
end

local function current_record(provider,status)
    local id,why=provider.boot_id()
    if not id then return nil,why end
    return {boot_id=id,active=status.active,committed=status.committed}
end

function M.confirm(provider)
    provider=provider or production_provider()
    local status,why=provider.bank_status()
    if not status then return nil,why end
    if not status.running_trial then
        return nil,"firmware_trial_not_running"
    end
    local record,record_why=current_record(provider,status)
    if not record then return nil,record_why end
    local ok,root_why=provider.prepare_root()
    if not ok then return nil,root_why end
    local wrote,write_why=provider.write_confirmed(record)
    if not wrote then return nil,write_why end
    return {status="FIRMWARE_TRIAL_WATCHDOG_CONFIRMED",confirmed=true,
            active=status.active,committed=status.committed}
end

function M.run(provider,wait_seconds)
    provider=provider or production_provider()
    wait_seconds=wait_seconds or WAIT_SECONDS
    if type(wait_seconds)~="number" or wait_seconds<2 or
       wait_seconds~=math.floor(wait_seconds) or wait_seconds%STEP_SECONDS~=0 then
        return nil,"firmware_trial_watchdog_timeout_invalid"
    end
    local status,why=provider.bank_status()
    if not status then return nil,why end
    if not status.running_trial then
        return {status="NO_RUNNING_FIRMWARE_TRIAL",watched=false}
    end
    local record,record_why=current_record(provider,status)
    if not record then return nil,record_why end
    local ok,root_why=provider.prepare_root()
    if not ok then return nil,root_why end
    local wrote,write_why=provider.write_state(record)
    if not wrote then return nil,write_why end

    local started,start_why=provider.monotonic()
    if not started then return nil,start_why end
    local deadline=started+wait_seconds
    while true do
        local now,now_why=provider.monotonic()
        if not now then return nil,now_why end
        if now>=deadline then break end

        local confirmed,confirm_why=provider.read_confirmed()
        if confirmed and same_state(confirmed,record) then
            return {status="FIRMWARE_TRIAL_WATCHDOG_CONFIRMED",watched=true,confirmed=true}
        elseif confirm_why and confirm_why~="absent" then
            return nil,confirm_why
        end

        local current,current_why=provider.bank_status()
        if not current then return nil,current_why end
        if not current.running_trial then
            return {status="FIRMWARE_TRIAL_ENDED",watched=true,confirmed=false}
        end
        local current_record_value,current_record_why=current_record(provider,current)
        if not current_record_value then return nil,current_record_why end
        if not same_state(current_record_value,record) then
            return {status="FIRMWARE_TRIAL_STATE_CHANGED",watched=true,confirmed=false}
        end

        now,now_why=provider.monotonic()
        if not now then return nil,now_why end
        local remaining=deadline-now
        if remaining>0 then
            provider.sleep(math.min(STEP_SECONDS,remaining))
        end
    end

    local confirmed,confirm_why=provider.read_confirmed()
    if confirmed and same_state(confirmed,record) then
        return {status="FIRMWARE_TRIAL_WATCHDOG_CONFIRMED",watched=true,confirmed=true}
    elseif confirm_why and confirm_why~="absent" then
        return nil,confirm_why
    end
    local current,current_why=provider.bank_status()
    if not current then return nil,current_why end
    if not current.running_trial then
        return {status="FIRMWARE_TRIAL_ENDED",watched=true,confirmed=false}
    end
    local final_record,final_why=current_record(provider,current)
    if not final_record then return nil,final_why end
    if not same_state(final_record,record) then
        return {status="FIRMWARE_TRIAL_STATE_CHANGED",watched=true,confirmed=false}
    end
    if provider.rollback()~=true then
        return nil,"firmware_trial_watchdog_rollback_failed"
    end
    return {status="FIRMWARE_TRIAL_WATCHDOG_ROLLBACK_REQUESTED",watched=true,
            confirmed=false,rollback_requested=true}
end

M.ROOT=ROOT
M.WAIT_SECONDS=WAIT_SECONDS
M.STEP_SECONDS=STEP_SECONDS
M.production_provider=production_provider
return M

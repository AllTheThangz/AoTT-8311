-- AoTT-8311 V3 persistent one-boot configuration recovery store.
local nixio=require "nixio"
local fs=require "nixio.fs"
local json=require "luci.jsonc"
local M={}
local ROOT="/ptconf/8311/aott-recovery/v1/boot-config"
local PLAN=ROOT.."/plan.json"
local MAX=8192
local FIELDS={bootdelay=true,uart_select=true,failsafe_delay=true,persist_root=true}
local PHASE={preparing=true,prepared=true,trial_running=true,rollback_restored=true}

local function dir_ok(st,mode)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and st.modedec==mode
end
local function file_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.modedec==600 and st.nlink==1 and type(st.size)=="number" and st.size>=1 and st.size<=MAX
end
local function sync_dir(path)
    local fd=nixio.open(path,nixio.open_flags("rdonly"))
    if not fd then return false end
    local ok=fd:sync()==true
    local closed=fd:close()
    return ok and closed~=false
end
local function ensure_dir(path,mode)
    local st=fs.lstat(path)
    if not st then
        if not fs.mkdir(path,mode) then return false end
        st=fs.lstat(path)
    end
    return dir_ok(st,mode)
end
local function ensure_tree()
    local a=fs.lstat("/ptconf")
    local b=fs.lstat("/ptconf/8311")
    if not a or not b or a.type~="dir" or b.type~="dir" or a.uid~=0 or b.uid~=0 then
        return nil,"boot_config_ancestor_unavailable"
    end
    if not ensure_dir("/ptconf/8311/aott-recovery",700) or
       not ensure_dir("/ptconf/8311/aott-recovery/v1",700) or
       not ensure_dir(ROOT,700) then
        return nil,"boot_config_recovery_directory_unsafe"
    end
    return true
end
local function value_record(row)
    return type(row)=="table" and getmetatable(row)==nil and
        ((row.present==false and row.value==nil) or
         (row.present==true and type(row.value)=="string" and #row.value<=2048 and
          not row.value:find("[%z\1-\31\127]")))
end
local function plan_ok(p)
    if type(p)~="table" or getmetatable(p)~=nil or p.schema~=1 or
       type(p.job_id)~="string" or #p.job_id~=32 or p.job_id:find("[^0-9a-f]") or
       not PHASE[p.phase] or type(p.before)~="table" or type(p.candidate)~="table" or
       not value_record(p.bootcmd_before) then return false end
    for key in pairs(p.before) do if not FIELDS[key] then return false end end
    for key in pairs(p.candidate) do if not FIELDS[key] then return false end end
    local n=0
    for key,row in pairs(p.candidate) do
        n=n+1
        if not value_record(row) or not value_record(p.before[key]) then return false end
    end
    if n<1 or n>4 then return false end
    if p.boot_id~=nil and
       (type(p.boot_id)~="string" or #p.boot_id~=36 or p.boot_id:find("[^0-9a-f-]")) then
        return false
    end
    return true
end
local function write(plan)
    if not plan_ok(plan) then return nil,"boot_config_plan_invalid" end
    local ok,why=ensure_tree()
    if not ok then return nil,why end
    local data=json.stringify(plan).."\n"
    if #data>MAX then return nil,"boot_config_plan_too_large" end
    local stage=PLAN..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"boot_config_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"boot_config_stage_create_failed" end
    local wrote=fd:writeall(data)
    local synced=wrote==#data and fd:sync()==true
    local closed=fd:close()
    if not synced or not closed then fs.unlink(stage);return nil,"boot_config_stage_write_failed" end
    if fs.rename(stage,PLAN)~=true or not sync_dir(ROOT) then
        fs.unlink(stage);return nil,"boot_config_plan_replace_failed"
    end
    local check=M.read()
    if not check or check.job_id~=plan.job_id or check.phase~=plan.phase then
        return nil,"boot_config_plan_readback_failed"
    end
    return true
end

function M.read()
    local st=fs.lstat(PLAN)
    if not st then return {pending=false} end
    if not file_ok(st) then return nil,"boot_config_plan_unsafe" end
    local raw=fs.readfile(PLAN,MAX+1)
    if type(raw)~="string" or #raw~=st.size then return nil,"boot_config_plan_read_failed" end
    local ok,p=pcall(json.parse,raw)
    raw=nil
    if not ok or not plan_ok(p) then return nil,"boot_config_plan_invalid" end
    p.pending=true
    return p
end

function M.arm(plan)
    local current,why=M.read()
    if not current then return nil,why end
    if current.pending then return nil,"boot_config_transaction_already_pending" end
    plan.schema=1
    -- The initial durable record must never imply that a partially
    -- completed (or interrupted) candidate was accepted for the next boot.
    -- Only the staging transaction can promote it to "prepared" after
    -- all candidate fields have been independently read back.
    plan.phase="preparing"
    plan.boot_id=nil
    local ok,ewhy=write(plan)
    if not ok then return nil,ewhy end
    return {status="BOOT_CONFIG_RECOVERY_ARMED",job_id=plan.job_id}
end

function M.phase(job,phase,boot_id)
    local p,why=M.read()
    if not p then return nil,why end
    if not p.pending or p.job_id~=job or not PHASE[phase] then
        return nil,"boot_config_plan_state_mismatch"
    end
    p.phase=phase;p.boot_id=boot_id
    local ok,ewhy=write(p)
    if not ok then return nil,ewhy end
    return true
end

function M.clear(job)
    local p,why=M.read()
    if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"boot_config_plan_state_mismatch" end
    local st=fs.lstat(PLAN)
    if not file_ok(st) or fs.unlink(PLAN)~=true or not sync_dir(ROOT) then
        return nil,"boot_config_plan_clear_failed"
    end
    return {status="BOOT_CONFIG_RECOVERY_CLEARED"}
end

M.ROOT=ROOT
M.PLAN=PLAN
M.fields=FIELDS
return M

-- AoTT-8311 V3 persistent PON/OMCI rollback store.
-- Subscriber configuration backups are root-only and never returned by APIs.
local nixio=require "nixio"
local fs=require "nixio.fs"
local json=require "luci.jsonc"
local web=require "8311.webutil"
local M={}
local ROOT="/ptconf/8311/aott-recovery/v1/pon-config"
local MIBDIR=ROOT.."/mibs"
local PLAN=ROOT.."/plan.json"
local CONFIRM=ROOT.."/confirmed"
local ENV=ROOT.."/environment.before"
local GPON=ROOT.."/gpon.before"
local OMCI=ROOT.."/omci.before"
local NETWORK=ROOT.."/network.before"
local MAX_ENV=32768
local MAX_UCI=131072
local MAX_MIB=131072
local MAX_PLAN=16384
local MAX_MIBS=32

local function dir_ok(st,mode)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and st.modedec==mode
end
local function file_ok(st,max,mode)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.nlink==1 and type(st.size)=="number" and st.size>=1 and st.size<=max and
        (mode==nil or st.modedec==mode)
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
local function tree()
    local a,b=fs.lstat("/ptconf"),fs.lstat("/ptconf/8311")
    if not a or not b or a.type~="dir" or b.type~="dir" or a.uid~=0 or b.uid~=0 then
        return nil,"pon_recovery_ancestor_unavailable"
    end
    for _,p in ipairs({
        "/ptconf/8311/aott-recovery",
        "/ptconf/8311/aott-recovery/v1",
        ROOT,MIBDIR,
    }) do
        if not ensure_dir(p,700) then return nil,"pon_recovery_directory_unsafe" end
    end
    return true
end
local function atomic(path,data,max,mode)
    if type(data)~="string" or #data<1 or #data>max then
        return nil,"pon_recovery_content_invalid"
    end
    local stage=path..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"pon_recovery_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"pon_recovery_stage_create_failed" end
    local wrote=fd:writeall(data)
    local synced=wrote==#data and fd:sync()==true
    local closed=fd:close()
    if not synced or not closed then fs.unlink(stage);return nil,"pon_recovery_stage_write_failed" end
    if fs.rename(stage,path)~=true then fs.unlink(stage);return nil,"pon_recovery_replace_failed" end
    if mode and fs.chmod(path,mode)~=true then return nil,"pon_recovery_mode_restore_failed" end
    if not sync_dir(path:match("^(.*)/[^/]+$")) then return nil,"pon_recovery_directory_sync_failed" end
    return true
end
local function digest(path)
    local code,out,overflow=web.capture({"/usr/bin/sha256sum",path},256)
    if code~=0 or overflow or type(out)~="string" then return nil end
    local h=out:match("^([0-9a-f]+)%s")
    return h and #h==64 and h or nil
end
local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function mib_entries()
    local entries={}
    for path in fs.glob("/etc/mibs/*.ini") do
        if type(path)~="string" or not path:match("^/etc/mibs/[A-Za-z0-9_.-]+%.ini$") then
            return nil,"pon_mib_path_unqualified"
        end
        local st=fs.lstat(path)
        if not file_ok(st,MAX_MIB) or st.modedec%2==1 or math.floor(st.modedec/2)%2==1 then
            return nil,"pon_mib_metadata_unqualified"
        end
        entries[#entries+1]={path=path,mode=st.modedec,size=st.size}
        if #entries>MAX_MIBS then return nil,"pon_mib_count_exceeded" end
    end
    table.sort(entries,function(a,b)return a.path<b.path end)
    if #entries<1 then return nil,"pon_mib_profiles_unavailable" end
    return entries
end
local function cleanup_files()
    for _,p in ipairs({PLAN,CONFIRM,ENV,GPON,OMCI,NETWORK}) do
        local st=fs.lstat(p)
        if st then
            local maximum=(p==PLAN and MAX_PLAN) or (p==CONFIRM and 256) or (p==ENV and MAX_ENV) or MAX_UCI
            if not file_ok(st,maximum,600) then
                return false
            end
            if fs.unlink(p)~=true then return false end
        end
    end
    local st=fs.lstat(MIBDIR)
    if st and not dir_ok(st,700) then return false end
    for p in fs.glob(MIBDIR.."/*") do
        local fst=fs.lstat(p)
        if not file_ok(fst,MAX_MIB,600) or fs.unlink(p)~=true then return false end
    end
    return sync_dir(ROOT) and sync_dir(MIBDIR)
end
local function read_plan()
    local st=fs.lstat(PLAN)
    if not st then return {pending=false} end
    if not file_ok(st,MAX_PLAN,600) then return nil,"pon_recovery_plan_unsafe" end
    local raw=fs.readfile(PLAN,MAX_PLAN+1)
    local ok,p=pcall(json.parse,raw or "")
    if not ok or type(p)~="table" or p.schema~=1 or not valid_job(p.job_id) or
       type(p.phase)~="string" or type(p.mibs)~="table" or #p.mibs<1 or #p.mibs>MAX_MIBS then
        return nil,"pon_recovery_plan_invalid"
    end
    local allowed={armed=true,trial_running=true}
    if not allowed[p.phase] then return nil,"pon_recovery_plan_invalid" end
    for i,e in ipairs(p.mibs) do
        if type(e)~="table" or type(e.path)~="string" or
           not e.path:match("^/etc/mibs/[A-Za-z0-9_.-]+%.ini$") or
           e.file~=("mib-"..string.format("%02d",i)..".before") or
           type(e.mode)~="number" or type(e.sha256)~="string" or #e.sha256~=64 then
            return nil,"pon_recovery_plan_invalid"
        end
    end
    p.pending=true
    return p
end

function M.arm(job,environment,gpon,omci,network)
    if not valid_job(job) then return nil,"pon_recovery_job_invalid" end
    for _,x in ipairs({
        {environment,MAX_ENV},{gpon,MAX_UCI},{omci,MAX_UCI},{network,MAX_UCI},
    }) do
        if type(x[1])~="string" or #x[1]<1 or #x[1]>x[2] then
            return nil,"pon_recovery_snapshot_invalid"
        end
    end
    local ok,why=tree();if not ok then return nil,why end
    local pending,pwhy=read_plan()
    if not pending then return nil,pwhy end
    if pending.pending then return nil,"pon_recovery_already_pending" end
    if not cleanup_files() then return nil,"pon_recovery_stale_cleanup_failed" end
    local entries,ewhy=mib_entries();if not entries then return nil,ewhy end
    local files={{ENV,environment,MAX_ENV},{GPON,gpon,MAX_UCI},
                 {OMCI,omci,MAX_UCI},{NETWORK,network,MAX_UCI}}
    for _,e in ipairs(files) do
        local wrote,wwhy=atomic(e[1],e[2],e[3])
        if not wrote then return nil,wwhy end
    end
    local index={}
    for i,e in ipairs(entries) do
        local data=fs.readfile(e.path,MAX_MIB+1)
        if type(data)~="string" or #data~=e.size then return nil,"pon_mib_backup_read_failed" end
        local name="mib-"..string.format("%02d",i)..".before"
        local path=MIBDIR.."/"..name
        local wrote,wwhy=atomic(path,data,MAX_MIB)
        if not wrote then return nil,wwhy end
        local h=digest(path);if not h then return nil,"pon_mib_backup_digest_failed" end
        index[#index+1]={path=e.path,file=name,mode=e.mode,sha256=h}
    end
    local plan={schema=1,job_id=job,phase="armed",mibs=index}
    local payload=json.stringify(plan).."\n"
    local wrote,wwhy=atomic(PLAN,payload,MAX_PLAN)
    if not wrote then return nil,wwhy end
    local check=read_plan()
    if not check or not check.pending or check.job_id~=job then
        return nil,"pon_recovery_arm_readback_failed"
    end
    return {status="PON_RECOVERY_ARMED",job_id=job,
            contains_configuration_values=false}
end

function M.pending()
    return read_plan()
end

function M.phase(job,phase)
    if phase~="armed" and phase~="trial_running" then return nil,"pon_recovery_phase_invalid" end
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"pon_recovery_job_mismatch" end
    p.phase=phase;p.pending=nil
    local wrote,wwhy=atomic(PLAN,json.stringify(p).."\n",MAX_PLAN)
    if not wrote then return nil,wwhy end
    return true
end

function M.load(job)
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"pon_recovery_job_mismatch" end
    local function read(path,max)
        local st=fs.lstat(path)
        if not file_ok(st,max,600) then return nil end
        local data=fs.readfile(path,max+1)
        return type(data)=="string" and #data==st.size and data or nil
    end
    local out={environment=read(ENV,MAX_ENV),gpon=read(GPON,MAX_UCI),
               omci=read(OMCI,MAX_UCI),network=read(NETWORK,MAX_UCI),
               mibs=p.mibs}
    if not out.environment or not out.gpon or not out.omci or not out.network then
        return nil,"pon_recovery_backup_read_failed"
    end
    return out
end

function M.restore_mibs(job)
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"pon_recovery_job_mismatch" end
    for _,e in ipairs(p.mibs) do
        local backup=MIBDIR.."/"..e.file
        local st=fs.lstat(backup)
        if not file_ok(st,MAX_MIB,600) or digest(backup)~=e.sha256 then
            return nil,"pon_mib_backup_invalid"
        end
        local data=fs.readfile(backup,MAX_MIB+1)
        local current=fs.lstat(e.path)
        if not current or current.type~="reg" or current.uid~=0 or current.gid~=0 or current.nlink~=1 then
            return nil,"pon_mib_restore_target_unsafe"
        end
        local wrote,wwhy=atomic(e.path,data,MAX_MIB,e.mode)
        if not wrote then return nil,wwhy end
        if digest(e.path)~=e.sha256 then return nil,"pon_mib_restore_readback_mismatch" end
    end
    return true
end

function M.confirm(job)
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job or p.phase~="trial_running" then
        return nil,"pon_recovery_confirmation_state_mismatch"
    end
    local existing=fs.lstat(CONFIRM)
    local data="AOTT-PON-CONFIRMED-1\njob="..job.."\n"
    if existing then
        if not file_ok(existing,256,600) then return nil,"pon_confirmation_unsafe" end
        return fs.readfile(CONFIRM,257)==data and
            {status="PON_CONFIRMATION_RECORDED",job_id=job} or
            nil,"pon_confirmation_job_mismatch"
    end
    local ok,ewhy=atomic(CONFIRM,data,256)
    if not ok then return nil,ewhy end
    return {status="PON_CONFIRMATION_RECORDED",job_id=job}
end

function M.confirmed(job)
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"pon_recovery_job_mismatch" end
    local st=fs.lstat(CONFIRM)
    if not st then return false end
    if not file_ok(st,256,600) then return nil,"pon_confirmation_unsafe" end
    return fs.readfile(CONFIRM,257)==("AOTT-PON-CONFIRMED-1\njob="..job.."\n")
end

function M.clear(job)
    local p,why=read_plan();if not p then return nil,why end
    if not p.pending or p.job_id~=job then return nil,"pon_recovery_job_mismatch" end
    if not cleanup_files() then return nil,"pon_recovery_cleanup_failed" end
    return {status="PON_RECOVERY_CLEARED",contains_configuration_values=false}
end

M.ROOT=ROOT
return M

-- C-014 integrated apply/confirm/recover transaction for SYNTHETIC files only.
-- Uses the existing native planner and staging guard. Never reloads a service,
-- writes /etc/config, touches a boot bank, or accepts a production directory.
local M={}
local HELD={}
local ERROR={}
local PACKAGES={"network","firewall"}
local ALL={"network","firewall","environment","cache"}
local SOURCE_APPLY={"environment","cache","network","firewall"}
local function units(j)return j.source_bundle and ALL or PACKAGES end
local function scope(j)return j.source_bundle and "uci_and_startup_sources"or "uci_only"end
local function stop(code) error({tag=ERROR,code=code},0) end
local function error_code(e)
    if type(e)=="table" and rawget(e,"tag")==ERROR then return rawget(e,"code") end
    return "transaction_internal_error"
end
local function plain(v) return type(v)=="table" and getmetatable(v)==nil end
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~="table" then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local function hex(s,n) return type(s)=="string" and #s==n and s:match("^[a-f0-9]+$") end
local function suffix(path)
    if type(path)~="string" then return nil end
    local s=path:match("^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$")
    return s and #s==16 and s or nil
end
local function dir_ok(s)
    return s and s.type=="dir" and s.uid==0 and s.gid==0 and s.modedec==700
end
local function file_ok(s,max)
    return s and s.type=="reg" and s.uid==0 and s.gid==0 and s.modedec==600 and
        s.nlink==1 and type(s.size)=="number" and s.size>=0 and s.size<=max
end
local function same(a,b)
    return a and b and a.ino==b.ino and a["dev"]==b["dev"]
end
local function optional(c,path)
    local s,e=c.fs.lstat(path)
    if s then return s end
    if e~=2 then stop("transaction_path_unavailable") end
end
local function close(fd)
    if not fd then return true end
    local ok,v=pcall(function()return fd:close()end)
    return ok and v==true
end
local function check(c)
    if c.environment_lease then
        local ok,why=require('8311.environment_lease').verify(c.environment_lease)
        if not ok then stop(why)end
    end
    local native=c.fs.lstat(c.root.."/native.environment")
    if (c.native_mark and (not native or not same(native,c.native_mark) or not file_ok(native,64)))or
       (not c.native_mark and native)then stop("transaction_native_binding_changed")end
    if c.n.getpid()~=c.pid then stop("transaction_process_changed") end
    for path,original in pairs(c.dirs) do
        local current=c.fs.lstat(path)
        if not dir_ok(current) or not same(current,original) then stop("transaction_directory_changed") end
    end
    local visible=c.fs.lstat(c.root.."/transaction.lock")
    if not file_ok(visible,0) or not same(visible,c.lock) or not same(c.fd:stat(),c.lock) then
        stop("transaction_lock_changed")
    end
end
local function read_path(c,path,max,may_missing)
    local before=optional(c,path)
    if not before and may_missing then return nil end
    if not file_ok(before,max) then stop("unsafe_transaction_file") end
    local fd=c.n.open(path,c.n.open_flags("rdonly"))
    if not fd then stop("transaction_read_failed") end
    local ok,data=pcall(function()
        local current=fd:stat()
        if not file_ok(current,max) or not same(current,before) or current.size~=before.size then
            stop("transaction_file_changed")
        end
        local chunks,bytes={},0
        while true do
            local part=fd:read(math.min(4096,max+1-bytes))
            if type(part)~="string" then stop("transaction_read_failed") end
            if part=="" then break end
            bytes=bytes+#part;if bytes>max then stop("transaction_file_too_large") end
            chunks[#chunks+1]=part
        end
        local after=c.fs.lstat(path)
        if not file_ok(after,max) or not same(after,before) or after.size~=before.size or bytes~=before.size then
            stop("transaction_file_changed")
        end
        return table.concat(chunks)
    end)
    local closed=close(fd)
    if not ok then stop(error_code(data)) end
    if not closed then stop("transaction_close_failed") end
    return data
end
local function allowed(c,name)
    if not c.allowed[name] then stop("transaction_filename_refused") end
    return c.root.."/"..name
end
local function read(c,name,may_missing)
    check(c)
    local bytes=read_path(c,allowed(c,name),65536,may_missing)
    check(c);return bytes
end
local function sync_dir(c,path)
    local fd=c.n.open(path,c.n.open_flags("rdonly"))
    if not fd then stop("transaction_directory_open_failed") end
    local ok,v=pcall(function()
        local s=fd:stat()
        if not dir_ok(s) or not same(s,c.dirs[path]) then stop("transaction_directory_changed") end
        return fd:sync()
    end)
    local closed=close(fd)
    if not ok or v~=true or not closed then stop("transaction_directory_sync_failed") end
end
local function write(c,name,bytes)
    if type(bytes)~="string" or #bytes==0 or #bytes>65536 then stop("transaction_write_size_invalid") end
    check(c)
    local final=allowed(c,name);local temporary=final..".new"
    local old=optional(c,final)
    if old and not file_ok(old,65536) then stop("unsafe_transaction_file") end
    local parent=name:match("^active/") and c.root.."/active" or c.root
    local stale=optional(c,temporary)
    if stale then
        -- Only fixed, disposable replacement scratch files are discarded.
        -- Neither a source backup nor active configuration is ever a scratch.
        if not file_ok(stale,65536) then stop("unsafe_transaction_scratch") end
        if c.fs.unlink(temporary)~=true then stop("transaction_scratch_remove_failed") end
        sync_dir(c,parent)
    end
    local fd=c.n.open(temporary,c.n.open_flags("wronly","creat","excl"),600)
    if not fd then stop("transaction_write_open_failed") end
    local ok,v=pcall(function()
        local opened=fd:stat()
        if not file_ok(opened,65536) or not same(opened,c.fs.lstat(temporary)) then
            stop("transaction_scratch_changed")
        end
        if fd:writeall(bytes)~=#bytes or fd:sync()~=true then stop("transaction_write_sync_failed") end
        local after=fd:stat()
        if not file_ok(after,65536) or after.size~=#bytes or not same(after,opened) or
           not same(after,c.fs.lstat(temporary)) then stop("transaction_scratch_changed") end
        return true
    end)
    local closed=close(fd)
    if not ok then stop(error_code(v)) end
    if not closed then stop("transaction_write_close_failed") end
    check(c)
    if old then
        local current=c.fs.lstat(final)
        if not file_ok(current,65536) or not same(current,old) then stop("transaction_destination_changed") end
    elseif optional(c,final) then stop("transaction_destination_changed") end
    if c.fs.rename(temporary,final)~=true then stop("transaction_replace_failed") end
    sync_dir(c,parent)
    if read(c,name)~=bytes then stop("transaction_write_readback_failed") end
end
local function digest(c,name)
    local raw=read(c,name)
    local path=allowed(c,name)
    local code,text,overflow=c.web.capture({"/usr/bin/timeout","-k","1","3","/usr/bin/sha256sum",path},512)
    local hash=type(text)=="string" and text:match("^([a-f0-9]+) ")
    if code~=0 or overflow~=false or not hex(hash,64) then stop("transaction_digest_unavailable") end
    if read(c,name)~=raw then stop("transaction_hash_read_changed") end
    return hash,raw
end
local function clock(c)
    local t=c.n.sysinfo()
    local now=type(t)=="table" and t.uptime
    local boot=c.fs.readfile("/proc/sys/kernel/random/boot_id",64)
    if type(now)~="number" or now~=math.floor(now) or now<0 or now>9007199254740000 or
       type(boot)~="string" or #boot~=37 or not boot:match("^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+\n$") then
        stop("transaction_clock_unavailable")
    end
    return now,boot:sub(1,36)
end
local function encode(j)
    local rows={j.native_env and "AOTT-C014-TXN-3"or(j.source_bundle and "AOTT-C014-TXN-2"or "AOTT-C014-TXN-1"),j.phase,j.id,j.boot,
        tostring(j.started),tostring(j.deadline)}
    for _,p in ipairs(units(j))do rows[#rows+1]=j.before[p]end
    for _,p in ipairs(units(j))do rows[#rows+1]=j.after[p]end
    return table.concat(rows,"\n").."\n"
end
local function decode_journal(raw)
    if type(raw)~="string"or #raw>2048 then stop("transaction_journal_invalid")end
    local lines={};for v in raw:gmatch("([^\n]*)\n")do lines[#lines+1]=v end
    local native=lines[1]=="AOTT-C014-TXN-3"
    local version=native or lines[1]=="AOTT-C014-TXN-2"
    local selected=version and ALL or PACKAGES
    if (not version and lines[1]~="AOTT-C014-TXN-1")or #lines~=6+2*#selected or
       not ({pending=true,rolling_back=true,rolled_back=true,confirmed=true})[lines[2]]or
       not hex(lines[3],32)or #lines[4]~=36 or
       not lines[4]:match("^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+$")then
        stop("transaction_journal_invalid")end
    for i=5,6 do if not lines[i]:match("^%d+$")or #lines[i]>16 then stop("transaction_journal_invalid")end end
    local j={source_bundle=version,native_env=native,phase=lines[2],id=lines[3],boot=lines[4],started=tonumber(lines[5]),
        deadline=tonumber(lines[6]),before={},after={}}
    for i,p in ipairs(selected)do
        local before,after=lines[6+i],lines[6+#selected+i]
        if not hex(before,64)or not hex(after,64)then stop("transaction_journal_invalid")end
        j.before[p]=before;j.after[p]=after
    end
    if j.deadline<=j.started or j.deadline-j.started>300 or encode(j)~=raw then stop("transaction_journal_invalid")end
    return j
end
local function source_scope(c)
    local environment=optional(c,c.root.."/"..c.active.environment)
    local cache=optional(c,c.root.."/"..c.active.cache)
    if (environment==nil)~=(cache==nil)then stop("transaction_startup_scope_incomplete")end
    return environment~=nil
end
local function native_scope(c)
    local raw=read_path(c,c.root.."/native.environment",64,true)
    if raw and raw~="AOTT-NATIVE-ENV-FIXTURE-1\n"then stop("transaction_native_binding_invalid")end
    return raw~=nil
end
local function journal(c,optional_read)
    local raw=read(c,"transaction.state",optional_read)
    if not raw then return nil end
    local j=decode_journal(raw)
    if j.source_bundle~=source_scope(c)then stop("transaction_startup_scope_changed")end
    if j.native_env~=native_scope(c)then stop("transaction_native_scope_changed")end
    return j
end
-- Independent worker may inspect the atomic journal while the caller owns
-- transaction.lock. This never reads package contents or changes any files.
function M.recovery_offer(root,mode)
    if mode~="offline_synthetic" or not suffix(root) then return nil,"transaction_directory_not_authorized" end
    local ok,result=pcall(function()
        local n,fs=require "nixio",require "nixio.fs"
        local parent=fs.lstat(root)
        if not dir_ok(parent) then stop("unsafe_transaction_directory") end
        local raw=read_path({n=n,fs=fs},root.."/transaction.state",2048,true)
        if not raw then stop("transaction_not_armed") end
        local j=decode_journal(raw)
        local after=fs.lstat(root)
        if not dir_ok(after) or not same(parent,after) then stop("transaction_directory_changed") end
        return {phase=j.phase,transaction_id=j.id,boot=j.boot,started=j.started,deadline=j.deadline}
    end)
    if not ok then return nil,error_code(result) end
    return result
end
local function raw_snapshot(c,files)
    local core=require "8311.vlan_transition";local state={}
    local s=suffix(c.root)
    for _,p in ipairs(PACKAGES) do
        local name="aott_c014_"..s.."_"..p
        local parsed=core.parse_export("package "..name.."\n"..files[p],name)
        if not parsed then stop("transaction_package_parse_failed") end
        state[p]=parsed
    end
    return state
end
local function native_evidence(c,previous,candidate)
    local codec=require '8311.startup_state'
    local before=codec.evidence(previous.environment,previous.cache,raw_snapshot(c,previous).network)
    local after=codec.evidence(candidate.environment,candidate.cache,raw_snapshot(c,candidate).network)
    if not before or not after then stop("transaction_native_records_invalid")end
    return before.environment,after.environment
end
local function native_inspect(c,previous,candidate)
    local before,after=native_evidence(c,previous,candidate)
    local result,why=require('8311.native_environment_guard').inspect(c.root,before,after,'offline_synthetic')
    if not result then stop(why)end
    return result
end
local function native_change(c,previous,candidate,direction,boundary)
    local before,after=native_evidence(c,previous,candidate)
    local result,why=require('8311.native_environment_guard').change(c.root,before,after,direction,boundary,'offline_synthetic')
    if not result then stop(why)end
    return result
end
local function inspect(c,j)
    local values={before={},after={},active={}}
    local retained={}
    for _,pkg in ipairs(units(j)) do
        local h,raw=digest(c,"previous."..pkg)
        if h~=j.before[pkg] then stop("transaction_backup_mismatch") end
        values.before[pkg]=raw
        retained["previous_"..pkg]={sha256=h,bytes=#raw}
        h,raw=digest(c,"candidate."..pkg)
        if h~=j.after[pkg] then stop("transaction_candidate_mismatch") end
        values.after[pkg]=raw
        retained["candidate_"..pkg]={sha256=h,bytes=#raw}
        h,raw=digest(c,c.active[pkg])
        if h~=j.before[pkg] and h~=j.after[pkg] then stop("transaction_unknown_active_content") end
        values.active[pkg]=h
    end
    local storage=require "8311.recovery_storage"
    local ok=storage.verify(suffix(c.root),read(c,"retained.state"),retained,scope(j))
    if not ok then stop("transaction_retention_not_verified")end
    if j.source_bundle then
        for _,set in ipairs({values.before,values.after})do
            if not require('8311.startup_state').verify(set.environment,set.cache,raw_snapshot(c,set).network)then
                stop("transaction_retained_source_disagreement")end
        end
    end
    if j.native_env then values.native=native_inspect(c,values.before,values.after)end
    return values
end
local function receipt(j,status)
    return {status=status,transaction_id=j.id,phase=j.phase,source_only_not_deployed=true,
        no_real_network_apply=true,physical_power_loss_unqualified=true,contains_configuration_values=false,
        startup_sources_included=j.source_bundle==true,active_artifacts=#units(j),native_environment_coordinated=j.native_env==true}
end
local function rollback(c,j)
    local v=inspect(c,j)
    if j.phase=="confirmed" then
        if j.native_env and not v.native.after then stop("confirmed_native_environment_changed")end
        for _,p in ipairs(units(j)) do if v.active[p]~=j.after[p] then stop("confirmed_state_changed") end end
        return receipt(j,"SOURCE_TXN_CONFIRMED")
    elseif j.phase=="rolled_back" then
        if j.native_env and not v.native.before then stop("restored_native_environment_changed")end
        for _,p in ipairs(units(j)) do if v.active[p]~=j.before[p] then stop("rolled_back_state_changed") end end
        return receipt(j,"SOURCE_TXN_ROLLED_BACK")
    end
    if j.phase~="rolling_back" then j.phase="rolling_back";write(c,"transaction.state",encode(j)) end
    if j.native_env then
        native_change(c,v.before,v.after,'restore',function()check(c);return true end)
    end
    for _,p in ipairs(units(j)) do
        if v.active[p]~=j.before[p] then write(c,c.active[p],v.before[p]) end
    end
    for _,p in ipairs(units(j)) do if digest(c,c.active[p])~=j.before[p] then stop("rollback_readback_failed") end end
    j.phase="rolled_back";write(c,"transaction.state",encode(j))
    return receipt(j,"SOURCE_TXN_ROLLED_BACK")
end
local function expired(c,j)
    local now,boot=clock(c)
    return boot~=j.boot or now<j.started or now>=j.deadline
end
local function in_lock(root,mode,fn)
    local s=suffix(root)
    if mode~="offline_synthetic" or not s then return nil,"transaction_directory_not_authorized" end
    if HELD[root] then return nil,"transaction_already_owned_in_process" end
    local c,fd
    local ok,result=pcall(function()
        local n,fs=require "nixio",require "nixio.fs"
        local parent,active=fs.lstat(root),fs.lstat(root.."/active")
        if not dir_ok(parent) or not dir_ok(active) then stop("unsafe_transaction_directory") end
        c={root=root,n=n,fs=fs,web=require "8311.webutil",pid=n.getpid(),
            dirs={[root]=parent,[root.."/active"]=active},allowed={['transaction.state']=true,['retained.state']=true},active={},
            native_mark=optional({fs=fs},root.."/native.environment")}
        for _,p in ipairs(ALL) do
            c.active[p]="active/aott_c014_"..s.."_"..p
            c.allowed[c.active[p]]=true;c.allowed['previous.'..p]=true;c.allowed['candidate.'..p]=true
        end
        local path=root.."/transaction.lock";local before=optional(c,path)
        if before and not file_ok(before,0) then stop("unsafe_transaction_lock") end
        fd=n.open(path,before and n.open_flags("rdwr") or n.open_flags("rdwr","creat","excl"),600)
        if not fd then stop("transaction_lock_open_failed") end
        c.fd=fd;c.lock=fd:stat()
        if not file_ok(c.lock,0) or (before and not same(before,c.lock)) then stop("transaction_lock_changed") end
        check(c)
        local locked,errno=fd:lock("tlock")
        if locked~=true then
            if errno==11 or errno==13 then stop("transaction_busy") end
            stop("transaction_lock_failed")
        end
        HELD[root]=true
        if not before then if fd:sync()~=true then stop("transaction_lock_sync_failed") end;sync_dir(c,root) end
        check(c)
        if c.native_mark then
            local lease,why=require('8311.environment_lease').acquire(root,mode)
            if not lease then stop(why)end
            c.environment_lease=lease
            check(c)
        end
        return fn(c)
    end)
    -- Release in reverse acquisition order, after all synchronous native
    -- commands and complete UCI/startup-record verification have finished.
    local lease_closed=true
    if c and c.environment_lease then
        lease_closed=require('8311.environment_lease').close(c.environment_lease)==true
    end
    local closed=close(fd)
    if closed then HELD[root]=nil else HELD[root]=true;return nil,"transaction_lock_release_unverified" end
    if not lease_closed then return nil,"environment_lease_release_unverified"end
    if not ok then return nil,error_code(result) end
    return result
end
function M.preview(root,mode)
    return in_lock(root,mode,function(c)
        if journal(c,true) then stop("transaction_already_started") end
        local bundle=source_scope(c);local native=native_scope(c);local revision,raw={},{}
        if native and not bundle then stop("transaction_native_requires_source_bundle")end
        for _,p in ipairs(bundle and ALL or PACKAGES)do
            local h,bytes=digest(c,c.active[p]);revision[#revision+1]=h;raw[p]=bytes
        end
        if bundle and not require('8311.startup_state').verify(raw.environment,raw.cache,raw_snapshot(c,raw).network)then
            stop("transaction_startup_source_disagreement")end
        if native and not native_inspect(c,raw,raw).before then stop("transaction_native_preview_mismatch")end
        return {status="SOURCE_TXN_PREVIEW",review_revision=table.concat(revision),source_only_not_deployed=true,
                scope=native and "uci_startup_and_native_fixture"or(bundle and "uci_and_startup_sources"or "uci_only")}
    end)
end
function M.begin(root,stage_dir,adapter,request,mode)
    return in_lock(root,mode,function(c)
        local bundle=source_scope(c);local native=native_scope(c);local selected=bundle and ALL or PACKAGES
        if native and not bundle then stop("transaction_native_requires_source_bundle")end
        local storage_scope=bundle and "uci_and_startup_sources"or "uci_only"
        local request_scope=native and "uci_startup_and_native_fixture"or storage_scope
        if not plain(request) or request.operator_confirmed~=true or not hex(request.review_revision,bundle and 256 or 128) or
           type(request.ttl_seconds)~="number" or request.ttl_seconds~=math.floor(request.ttl_seconds) or
           request.ttl_seconds<1 or request.ttl_seconds>300 then stop("transaction_request_invalid") end
        if (bundle and request.scope~=request_scope)or (request.scope~=nil and request.scope~=request_scope)then
            stop("transaction_scope_not_confirmed")end
        local keys={operator_confirmed=true,review_revision=true,ttl_seconds=true,vlan=true,parent=true,zone=true,scope=true}
        for k in pairs(request) do if not keys[k] then stop("transaction_request_invalid") end end
        if journal(c,true) or optional(c,root.."/transaction.state.new") then stop("transaction_already_started") end
        if optional(c,root.."/retained.state") or optional(c,root.."/retained.state.new") then
            stop("transaction_workspace_not_empty") end
        for _,p in ipairs(ALL) do
            for _,prefix in ipairs({"previous.","candidate."}) do
                if optional(c,root.."/"..prefix..p) or optional(c,root.."/"..prefix..p..".new") then
                    stop("transaction_workspace_not_empty")
                end
            end
        end
        if not plain(adapter) or adapter.disposable_fixture~=true or adapter.transaction_directory~=root or
           adapter.workspace_directory~=stage_dir or type(adapter.source_snapshot)~="function" or
           type(adapter.applied_readback)~="function" or type(adapter.activation_ready)~="function" then
            stop("transaction_adapter_not_qualified")
        end
        local storage=require "8311.recovery_storage"
        local capacity=storage.reserve(c.fs.statvfs(root))
        if not capacity then stop("transaction_recovery_storage_not_ready") end
        local admission=require "8311.recovery_admission"
        local recovery=admission.present(root,mode)
        if not recovery then stop("independent_recovery_worker_unavailable") end
        local before,hashes,revision={},{},{}
        for _,p in ipairs(selected)do
            hashes[p],before[p]=digest(c,c.active[p]);revision[#revision+1]=hashes[p]
        end
        if table.concat(revision)~=request.review_revision then stop("transaction_stale_preview")end
        local source=raw_snapshot(c,before)
        if bundle and not require('8311.startup_state').verify(before.environment,before.cache,source.network)then
            stop("transaction_startup_source_disagreement")end
        if not equal(adapter.source_snapshot(),source) then stop("transaction_source_snapshot_mismatch") end
        local core=require "8311.vlan_transition";local guard=require "8311.vlan_stage_guard"
        local handle=guard.acquire(stage_dir,mode)
        if not handle then stop("transaction_stage_owner_unavailable") end
        local staged,outcome=pcall(function()
            if not equal(adapter.snapshot(),source) then stop("transaction_stale_candidate") end
            local plan=core.prepare(source,request.vlan,request.parent,request.zone)
            if not plan then stop("transaction_plan_rejected") end
            local projected=core.fixture_projection(plan,mode)
            if native then
                local codec=require '8311.startup_state'
                local next_sources=codec.plan(before.environment,before.cache,source.network,projected.after.network,mode)
                if not next_sources then stop("transaction_startup_plan_rejected")end
                local b=codec.evidence(before.environment,before.cache,source.network)
                local a=codec.evidence(next_sources.environment,next_sources.cache,projected.after.network)
                local ready,why=require('8311.native_environment_guard').inspect(root,b.environment,a.environment,mode)
                if not ready then stop(why)end
                if not ready.before then stop("transaction_native_stale_preview")end
            end
            for _,p in ipairs(selected) do write(c,"previous."..p,before[p]) end
            local result=guard.stage(handle,plan,adapter,mode)
            if not result or result.status~="SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED" then stop("transaction_stage_failed") end
            local after={}
            for _,p in ipairs(PACKAGES) do
                if not guard.status(handle) then stop("transaction_stage_owner_lost") end
                after[p]=read_path(c,stage_dir.."/candidate/aott_c014_"..suffix(root).."_"..p,65536,false)
                if not guard.status(handle) then stop("transaction_stage_owner_lost") end
            end
            if not equal(raw_snapshot(c,after),projected.after) then stop("transaction_candidate_bytes_mismatch") end
            if bundle then
                local planned=require('8311.startup_state').plan(before.environment,before.cache,
                    source.network,projected.after.network,mode)
                if not planned then stop("transaction_startup_plan_rejected")end
                after.environment=planned.environment;after.cache=planned.cache
            end
            local after_hash={}
            for _,p in ipairs(selected) do
                write(c,"candidate."..p,after[p]);after_hash[p]=digest(c,"candidate."..p)
                if digest(c,c.active[p])~=hashes[p] then stop("transaction_source_changed_during_stage") end
            end
            return {bytes=after,hashes=after_hash,expected=projected.after}
        end)
        local released=guard.close(handle)
        if not released then stop("transaction_stage_release_failed") end
        if not staged then stop(error_code(outcome)) end
        -- Bind all four retained files, exact lengths and content hashes to
        -- this workspace before the recovery decision can become pending.
        local retained={}
        for _,pkg in ipairs(selected) do
            local h,raw=digest(c,"previous."..pkg)
            retained["previous_"..pkg]={sha256=h,bytes=#raw}
            h,raw=digest(c,"candidate."..pkg)
            retained["candidate_"..pkg]={sha256=h,bytes=#raw}
        end
        local sealed=storage.encode(suffix(root),retained,storage_scope)
        if not sealed then stop("transaction_retention_not_verified") end
        write(c,"retained.state",sealed)
        if not storage.verify(suffix(root),read(c,"retained.state"),retained,storage_scope) then
            stop("transaction_retention_not_verified") end
        local now,boot=clock(c);local id=require('luci.sys').uniqueid(16)
        if not hex(id,32) then stop("transaction_identifier_unavailable") end
        local j={source_bundle=bundle,native_env=native,phase="pending",id=id,boot=boot,started=now,deadline=now+request.ttl_seconds,
            before=hashes,after=outcome.hashes}
        -- The recovery record is durable BEFORE either candidate is activated.
        write(c,"transaction.state",encode(j));inspect(c,j)
        local applied=pcall(function()
            if admission.arm(root,recovery,j,mode)~=true then stop("recovery_worker_not_armed") end
            if native then
                native_change(c,before,outcome.bytes,'apply',function()
                    check(c);return admission.verify(root,recovery,mode)==true
                end)
            end
            for _,p in ipairs(bundle and SOURCE_APPLY or PACKAGES) do
                if admission.verify(root,recovery,mode)~=true then stop("recovery_worker_lost") end
                write(c,c.active[p],outcome.bytes[p])
            end
            for _,p in ipairs(selected)do if digest(c,c.active[p])~=j.after[p]then stop("apply_readback_failed")end end
            local applied_state=inspect(c,j)
            if native and not applied_state.native.after then stop("apply_native_readback_failed")end
            if not equal(adapter.applied_readback(),outcome.expected) or adapter.activation_ready()~=true then
                stop("apply_acceptance_failed")
            end
            check(c)
            if native and not native_inspect(c,before,outcome.bytes).after then stop("apply_native_readback_failed")end
            if admission.verify(root,recovery,mode)~=true then stop("recovery_worker_lost") end
        end)
        if not applied then
            local r=rollback(c,j);r.apply_accepted=false;return r
        end
        if expired(c,j) then return rollback(c,j) end
        return receipt(j,"SOURCE_TXN_PENDING_CONFIRMATION")
    end)
end
function M.recover(root,mode,only_if_due)
    return in_lock(root,mode,function(c)
        local j=journal(c,true)
        if not j then stop("transaction_not_armed") end
        if j.phase=="pending" and only_if_due==true and not expired(c,j) then
            inspect(c,j);return receipt(j,"SOURCE_TXN_PENDING_CONFIRMATION")
        end
        return rollback(c,j)
    end)
end
function M.confirm(root,id,health,mode)
    return in_lock(root,mode,function(c)
        local j=journal(c)
        if not hex(id,32) or id~=j.id then stop("transaction_confirmation_id_mismatch") end
        if j.phase~="pending" then stop("transaction_not_pending_confirmation") end
        if expired(c,j) then return rollback(c,j) end
        local current=inspect(c,j)
        if j.native_env and not current.native.after then stop("transaction_native_not_fully_applied")end
        for _,p in ipairs(units(j)) do if current.active[p]~=j.after[p] then stop("transaction_not_fully_applied") end end
        if not plain(health) or health.disposable_fixture~=true or health.transaction_directory~=root or
           health.operator_confirmed~=true or type(health.inspect)~="function" then
            stop("confirmation_adapter_not_qualified")
        end
        local admission=require "8311.recovery_admission"
        local recovery=admission.present(root,mode)
        if not recovery or admission.arm(root,recovery,j,mode)~=true then
            local r=rollback(c,j);r.confirmation_accepted=false;return r
        end
        local ok,facts=pcall(health.inspect,j.id)
        if not ok or not plain(facts) or facts.transaction_id~=j.id or facts.synthetic_only~=true or
           facts.management_reachable~=true or facts.forwarding_healthy~=true or facts.recovery_ready~=true then
            local r=rollback(c,j);r.confirmation_accepted=false;return r
        end
        current=inspect(c,j)
        if j.native_env and not current.native.after then stop("transaction_native_changed_during_confirmation")end
        for _,p in ipairs(units(j)) do if current.active[p]~=j.after[p] then stop("transaction_changed_during_confirmation") end end
        if expired(c,j) then return rollback(c,j) end
        if admission.verify(root,recovery,mode)~=true then
            local r=rollback(c,j);r.confirmation_accepted=false;return r
        end
        j.phase="confirmed";write(c,"transaction.state",encode(j))
        return receipt(j,"SOURCE_TXN_CONFIRMED")
    end)
end
return M

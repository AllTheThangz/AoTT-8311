-- Native independent recovery-worker admission. SYNTHETIC workspaces only.
-- Kernel ownership plus bounded heartbeat, process incarnation and a fresh
-- transaction-specific acknowledgement. No GUI, network or service startup.
local M={}
local OWNERS={}
local TOKENS=setmetatable({}, {__mode="k"})
local PROOFS=setmetatable({}, {__mode="k"})
local ERROR={}
local FILES={['recovery.ready']=true,['recovery.request']=true,['recovery.ack']=true}
local function fail(code) error({tag=ERROR,code=code},0) end
local function reason(e)
    if type(e)=="table" and rawget(e,"tag")==ERROR then return rawget(e,"code") end
    return "recovery_admission_internal_error"
end
local function safe(fn,...)
    local ok,v=pcall(fn,...)
    if not ok then return nil,reason(v) end
    return v
end
local function permitted(root,mode)
    if type(root)~="string" or mode~="offline_synthetic" then return false end
    local s=root:match("^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$")
    return s and #s==16
end
local function same(a,b) return a and b and a.ino==b.ino and a["dev"]==b["dev"] end
local function dir_ok(s) return s and s.type=="dir" and s.uid==0 and s.gid==0 and s.modedec==700 end
local function file_ok(s,max)
    return s and s.type=="reg" and s.uid==0 and s.gid==0 and s.modedec==600 and s.nlink==1 and
        type(s.size)=="number" and s.size>=0 and s.size<=max
end
local function close(fd)
    if not fd then return true end
    local ok,v=pcall(function()return fd:close()end);return ok and v==true
end
local function context(root,mode)
    if not permitted(root,mode) then fail("recovery_directory_not_authorized") end
    local n,fs=require "nixio",require "nixio.fs"
    local parent=fs.lstat(root)
    if not dir_ok(parent) then fail("unsafe_recovery_directory") end
    return {root=root,n=n,fs=fs,parent=parent,pid=n.getpid()}
end
local function parent(c)
    local now=c.fs.lstat(c.root)
    if not dir_ok(now) or not same(now,c.parent) then fail("recovery_directory_changed") end
end
local function optional(c,path)
    local s,e=c.fs.lstat(path)
    if s then return s end
    if e~=2 then fail("recovery_path_unavailable") end
end
local function time(c)
    local now=c.n.sysinfo().uptime
    local boot=c.fs.readfile('/proc/sys/kernel/random/boot_id',64)
    if type(now)~="number" or now~=math.floor(now) or now<0 or
       type(boot)~="string" or #boot~=37 or
       not boot:match('^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+\n$') then
        fail("recovery_clock_unavailable")
    end
    return now,boot:sub(1,36)
end
local function incarnation(c,pid)
    if type(pid)~="string" or not pid:match('^[1-9]%d*$') or #pid>10 then fail("recovery_process_invalid") end
    -- Use the explicit thread-group leader path. QEMU's self-stat view can
    -- describe its later-created emulation thread rather than the leader.
    local raw=c.fs.readfile('/proc/'..pid..'/task/'..pid..'/stat',4096)
    local tail=type(raw)=="string" and raw:match('^%d+ %(.+%) (.+)$')
    if not tail then fail("recovery_process_unavailable") end
    local fields={};for value in tail:gmatch('%S+') do fields[#fields+1]=value end
    if #fields<20 or fields[1]=='Z' or fields[1]=='X' or fields[1]=='T' or fields[1]=='t' or
       not fields[20]:match('^%d+$') then fail("recovery_process_not_running") end
    return fields[20]
end
local function read_once(c,name,allow_missing)
    if not FILES[name] then fail("recovery_filename_refused") end
    parent(c)
    local path=c.root..'/'..name;local before=optional(c,path)
    if not before and allow_missing then return nil end
    if not file_ok(before,1024) then fail("unsafe_recovery_metadata") end
    local fd=c.n.open(path,c.n.open_flags('rdonly'))
    if not fd then fail("recovery_metadata_open_failed") end
    local ok,data=pcall(function()
        local opened=fd:stat()
        if not file_ok(opened,1024) or not same(before,opened) then fail("recovery_metadata_changed") end
        local raw=fd:read(1025)
        local after=c.fs.lstat(path)
        if type(raw)~='string' or #raw~=opened.size or not file_ok(after,1024) or
           not same(after,opened) or after.size~=opened.size then fail("recovery_metadata_changed") end
        parent(c);return raw
    end)
    local done=close(fd)
    if not ok then fail(reason(data)) end
    if not done then fail("recovery_metadata_close_failed") end
    return data
end
local function read(c,name,allow_missing)
    -- Readiness, requests and acknowledgements are atomically replaced by
    -- another cooperating process. Retry only an observed replacement, not
    -- a malformed record, unsafe inode, permission failure or missing owner.
    for attempt=1,3 do
        local ok,value=pcall(read_once,c,name,allow_missing)
        if ok then return value end
        if reason(value)~="recovery_metadata_changed" or attempt==3 then fail(reason(value)) end
        c.n.nanosleep(0,5000000)
    end
end
local function sync(c)
    local fd=c.n.open(c.root,c.n.open_flags('rdonly'))
    if not fd then fail('recovery_directory_open_failed') end
    local ok,v=pcall(function()
        if not dir_ok(fd:stat()) or not same(fd:stat(),c.parent) then fail('recovery_directory_changed') end
        return fd:sync()
    end)
    local done=close(fd)
    if not ok or v~=true or not done then fail('recovery_directory_sync_failed') end
end
local function write(c,name,bytes)
    if not FILES[name] or type(bytes)~='string' or #bytes>1024 then fail('recovery_write_invalid') end
    parent(c);local path=c.root..'/'..name;local temp=path..'.new'
    local before=optional(c,path);if before and not file_ok(before,1024) then fail('unsafe_recovery_metadata') end
    local stale=optional(c,temp)
    if stale then
        if not file_ok(stale,1024) then fail('unsafe_recovery_scratch') end
        if c.fs.unlink(temp)~=true then fail('recovery_scratch_remove_failed') end
    end
    local fd=c.n.open(temp,c.n.open_flags('wronly','creat','excl'),600)
    if not fd then fail('recovery_write_open_failed') end
    local ok,v=pcall(function()
        local st=fd:stat()
        if not file_ok(st,1024) or not same(st,c.fs.lstat(temp)) then fail('recovery_metadata_changed') end
        if fd:writeall(bytes)~=#bytes or fd:sync()~=true then fail('recovery_write_sync_failed') end
        if not same(st,fd:stat()) or not same(st,c.fs.lstat(temp)) then fail('recovery_metadata_changed') end
        return true
    end)
    local done=close(fd)
    if not ok then fail(reason(v)) end
    if not done then fail('recovery_metadata_close_failed') end
    parent(c)
    if before then
        if not same(before,c.fs.lstat(path)) then fail('recovery_metadata_changed') end
    elseif optional(c,path) then fail('recovery_metadata_changed') end
    if c.fs.rename(temp,path)~=true then fail('recovery_metadata_replace_failed') end
    sync(c)
    if read(c,name)~=bytes then fail('recovery_metadata_readback_failed') end
end
local function hex(s) return type(s)=='string' and #s==32 and s:match('^[a-f0-9]+$') end
local function integer(s)
    return type(s)=='string' and #s<=12 and s:match('^%d+$') and tostring(tonumber(s))==s
end
local function unpack_record(raw,kind,count)
    if type(raw)~='string' or #raw>1024 then fail('recovery_record_invalid') end
    local values={};for v in raw:gmatch('([^\n]*)\n') do values[#values+1]=v end
    if #values~=count or values[1]~='AOTT-RECOVERY-'..kind..'-1' or
       table.concat(values,'\n')..'\n'~=raw then fail('recovery_record_invalid') end
    return values
end
local function ready_record(raw)
    local v=unpack_record(raw,'READY',8)
    if not hex(v[2]) or not integer(v[3]) or not integer(v[4]) or #v[5]~=36 or
       not v[5]:match('^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+$') or
       not integer(v[6]) or not integer(v[7]) or not integer(v[8]) then fail('recovery_record_invalid') end
    local r={epoch=v[2],pid=v[3],start=v[4],boot=v[5],tick=tonumber(v[6]),until_time=tonumber(v[7]),began=tonumber(v[8])}
    if r.until_time<=r.began or r.until_time-r.began>600 or r.tick<r.began or r.tick>=r.until_time then
        fail('recovery_record_invalid') end
    return r
end
local function request_record(raw)
    local v=unpack_record(raw,'REQUEST',6)
    if not hex(v[2]) or not hex(v[3]) or not integer(v[4]) or #v[5]~=36 or not hex(v[6]) then fail('recovery_record_invalid') end
    return {epoch=v[2],id=v[3],deadline=tonumber(v[4]),boot=v[5],challenge=v[6]}
end
local function ack_record(raw)
    local v=unpack_record(raw,'ACK',6)
    if not hex(v[2]) or not hex(v[3]) or not integer(v[4]) or not integer(v[5]) or not hex(v[6]) then fail('recovery_record_invalid') end
    return {epoch=v[2],id=v[3],deadline=tonumber(v[4]),tick=tonumber(v[5]),challenge=v[6]}
end
local function owner_check(c)
    if c.n.getpid()~=c.pid or OWNERS[c.root]~=c.handle then fail('recovery_owner_invalid') end
    parent(c)
    local visible=c.fs.lstat(c.root..'/recovery.lock')
    if not file_ok(visible,0) or not same(visible,c.lock) or not same(c.fd:stat(),c.lock) then
        fail('recovery_lock_changed') end
end
local function probe(c)
    -- Never open/close a second fd when this process owns the POSIX lock.
    if OWNERS[c.root] then fail('recovery_worker_not_independent') end
    parent(c);local path=c.root..'/recovery.lock';local before=optional(c,path)
    if not file_ok(before,0) then fail('recovery_worker_missing') end
    local fd=c.n.open(path,c.n.open_flags('rdwr'))
    if not fd then fail('recovery_lock_probe_failed') end
    local ok,v=pcall(function()
        if not file_ok(fd:stat(),0) or not same(fd:stat(),before) then fail('recovery_lock_changed') end
        local acquired,errno=fd:lock('tlock')
        parent(c)
        if not same(before,c.fs.lstat(path)) then fail('recovery_lock_changed') end
        if acquired==true then fail('recovery_worker_missing') end
        if acquired~=false or (errno~=11 and errno~=13) then fail('recovery_lock_probe_failed') end
        return before
    end)
    local done=close(fd)
    if not ok then fail(reason(v)) end
    if not done then fail('recovery_lock_probe_failed') end
    return v
end
local function observe(c)
    local lock=probe(c)
    local raw=read(c,'recovery.ready');local r=ready_record(raw)
    local now,boot=time(c)
    if r.pid==tostring(c.pid) then fail('recovery_worker_not_independent') end
    if r.boot~=boot or now<r.tick or now-r.tick>3 or now>=r.until_time then fail('recovery_worker_stale') end
    if incarnation(c,r.pid)~=r.start then fail('recovery_process_changed') end
    if not same(lock,probe(c)) then fail('recovery_lock_changed') end
    return r,lock
end
local function observed(c)
    -- Atomic heartbeat replacement may intersect a read. Retry only the
    -- explicitly detected metadata swap, never invalid contents/permissions.
    for attempt=1,3 do
        local ok,a,b=pcall(observe,c)
        if ok then return a,b end
        if reason(a)~='recovery_metadata_changed' or attempt==3 then fail(reason(a)) end
        c.n.nanosleep(0,5000000)
    end
end
function M.present(root,mode)
    return safe(function()
        local c=context(root,mode);local r,lock=observed(c)
        local h={};PROOFS[h]={root=root,parent=c.parent,epoch=r.epoch,pid=r.pid,start=r.start,boot=r.boot,lock=lock}
        return h
    end)
end
local function verified(root,h,mode,require_ack)
    local p=type(h)=='table' and PROOFS[h]
    if not p or p.root~=root then fail('invalid_recovery_proof') end
    local c=context(root,mode)
    if not same(c.parent,p.parent) then fail('recovery_directory_changed') end
    local r,lock=observed(c)
    if r.epoch~=p.epoch or r.pid~=p.pid or r.start~=p.start or r.boot~=p.boot or not same(lock,p.lock) then
        fail('recovery_worker_changed') end
    if require_ack then
        if not p.id then fail('recovery_not_armed') end
        local a=ack_record(read(c,'recovery.ack'))
        if a.epoch~=p.epoch or a.id~=p.id or a.deadline~=p.deadline or a.challenge~=p.challenge or a.tick<p.armed_at or
           a.tick>r.tick or r.until_time<p.deadline+2 then fail('recovery_ack_mismatch') end
        if not same(lock,probe(c)) then fail('recovery_lock_changed') end
    end
    return c,r,p
end
-- Supervision must attest its own unreaped child, not an unrelated owner.
-- This discloses no process metadata and never changes ownership or the proof.
function M.matches_process(root,h,pid,start,mode)
    return safe(function()
        if type(pid)~='number' or pid<1 or pid~=math.floor(pid) or
           type(start)~='string' or not start:match('^%d+$') then fail('recovery_process_invalid') end
        local c,r,p=verified(root,h,mode,false)
        if p.pid~=tostring(pid) or p.start~=start then fail('recovery_process_mismatch') end
        return true
    end)
end
function M.verify(root,h,mode)
    return safe(function()verified(root,h,mode,true);return true end)
end
function M.arm(root,h,j,mode)
    return safe(function()
        local c,r,p=verified(root,h,mode,false)
        if type(j)~='table' or not hex(j.id) or j.boot~=r.boot or type(j.deadline)~='number' or
           j.deadline~=math.floor(j.deadline) or r.until_time<j.deadline+2 then fail('recovery_coverage_insufficient') end
        local now=time(c)
        local challenge=require('luci.sys').uniqueid(16)
        if not hex(challenge) then fail('recovery_challenge_unavailable') end
        p.id=j.id;p.deadline=j.deadline;p.armed_at=now;p.challenge=challenge
        write(c,'recovery.request',table.concat({'AOTT-RECOVERY-REQUEST-1',p.epoch,j.id,tostring(j.deadline),j.boot,challenge,''},'\n'))
        for _=1,30 do
            verified(root,h,mode,false)
            local raw=read(c,'recovery.ack',true)
            if raw then
                local a=ack_record(raw)
                if a.epoch==p.epoch and a.id==j.id and a.deadline==j.deadline and a.challenge==challenge and a.tick>=now then
                    verified(root,h,mode,true);return true
                end
            end
            c.n.nanosleep(0,100000000)
        end
        fail('recovery_ack_timeout')
    end)
end
function M.acquire(root,budget,mode)
    if not permitted(root,mode) then return nil,'recovery_directory_not_authorized' end
    if OWNERS[root] then return nil,'recovery_worker_already_owned' end
    if type(budget)~='number' or budget~=math.floor(budget) or budget<5 or budget>600 then
        return nil,'recovery_budget_invalid' end
    local fd
    local ok,c=pcall(function()
        local c=context(root,mode);local path=root..'/recovery.lock';local old=optional(c,path)
        if old and not file_ok(old,0) then fail('unsafe_recovery_lock') end
        fd=c.n.open(path,old and c.n.open_flags('rdwr') or c.n.open_flags('rdwr','creat','excl'),600)
        if not fd then fail('recovery_lock_open_failed') end
        local st=fd:stat()
        if not file_ok(st,0) or not same(st,c.fs.lstat(path)) or (old and not same(old,st)) then fail('recovery_lock_changed') end
        local acquired=fd:lock('tlock')
        if acquired~=true then fail('recovery_worker_already_running') end
        local now,boot=time(c)
        local epoch=require('luci.sys').uniqueid(16)
        if not hex(epoch) then fail('recovery_epoch_unavailable') end
        c.fd=fd;c.lock=st;c.started=now;c.until_time=now+budget;c.boot=boot;c.epoch=epoch
        c.start=incarnation(c,tostring(c.pid));c.last_tick=nil
        return c
    end)
    if not ok then
        if not close(fd) then OWNERS[root]={quarantined=true};return nil,'recovery_lock_release_unverified' end
        return nil,reason(c)
    end
    local h={};c.handle=h;OWNERS[root]=h;TOKENS[h]=c
    return h
end
function M.pulse(handle,mode)
    return safe(function()
        local c=type(handle)=='table' and TOKENS[handle]
        if not c or mode~='offline_synthetic' then fail('invalid_recovery_owner') end
        owner_check(c)
        local now,boot=time(c)
        if boot~=c.boot or now<c.started or now>=c.until_time then fail('recovery_worker_budget_ended') end
        if c.last_tick~=now then
            write(c,'recovery.ready',table.concat({'AOTT-RECOVERY-READY-1',c.epoch,tostring(c.pid),c.start,
                c.boot,tostring(now),tostring(c.until_time),tostring(c.started),''},'\n'))
            c.last_tick=now
        end
        local request=read(c,'recovery.request',true)
        if request then
            local r=request_record(request)
            if r.epoch==c.epoch then
                local j=require('8311.vlan_transaction').recovery_offer(c.root,mode)
                if j and j.phase=='pending' and j.transaction_id==r.id and j.boot==r.boot and
                   j.deadline==r.deadline and c.until_time>=r.deadline+2 then
                    local ack=table.concat({'AOTT-RECOVERY-ACK-1',c.epoch,r.id,tostring(r.deadline),tostring(now),r.challenge,''},'\n')
                    -- A new admission/confirmation request needs a fresh
                    -- challenge response, even for the same transaction ID.
                    if c.acked~=r.challenge then write(c,'recovery.ack',ack);c.acked=r.challenge end
                end
            end
        end
        owner_check(c)
        return {status='SOURCE_RECOVERY_WORKER_READY',source_only_not_deployed=true}
    end)
end
function M.close(handle)
    local c=type(handle)=='table' and TOKENS[handle]
    if not c or OWNERS[c.root]~=handle or c.pid~=c.n.getpid() then return nil,'invalid_recovery_owner' end
    if not close(c.fd) then return nil,'recovery_lock_release_unverified' end
    TOKENS[handle]=nil;OWNERS[c.root]=nil
    -- Stale metadata is harmless without the same live kernel owner/process.
    return {status='SOURCE_RECOVERY_WORKER_RELEASED',lock_never_unlinked=true}
end
local function step(handle,mode)
    local c=type(handle)=='table' and TOKENS[handle]
    if not c then return nil,'invalid_recovery_owner' end
    local alive,why=M.pulse(handle,mode)
    if not alive then return nil,why end
    local tx=require('8311.vlan_transaction')
    local j,err=tx.recovery_offer(c.root,mode)
    if not j then
        if err=='transaction_not_armed' or err=='transaction_file_changed' then
            -- No state is accepted from an intersected atomic replacement.
            -- Retry on the next bounded loop step, not with unchecked data.
            return {status='SOURCE_RECOVERY_WAITING'}
        end
        return nil,err
    end
    if j.phase=='confirmed' or j.phase=='rolled_back' then
        -- The transaction owner already wrote a terminal decision. Do not
        -- contend for its lock solely to issue another success receipt.
        return {status='SOURCE_RECOVERY_TERMINAL_OBSERVED',phase=j.phase,source_only_not_deployed=true}
    end
    local now,boot=time(c)
    if j.phase~='pending' or j.boot~=boot or now<j.started or now>=j.deadline then
        local r,e=tx.recover(c.root,mode,true)
        if not r and (e=='transaction_busy'or e=='environment_lease_busy') then return {status='SOURCE_RECOVERY_WAITING'} end
        return r,e
    end
    return {status='SOURCE_RECOVERY_WAITING'}
end
function M.step(handle,mode)
    local ok,a,b=pcall(step,handle,mode)
    if not ok then return nil,reason(a) end
    return a,b
end
return M

-- Bounded native recovery supervision. OFFLINE SYNTHETIC workspaces only.
-- Forks the existing admission/recovery worker, never a caller-supplied command.
-- A stable owner lock and retained launch budget prevent duplicate supervisors
-- and unlimited automatic restarts. No live services, GUI routes or boot hooks.
local M={}
local HELD={}
local ERROR={}
local LOCK='recovery.supervisor.lock'
local STATE='recovery.supervisor.state'
local STOP='recovery.supervisor.stop'
local STOP_BYTES='AOTT-RECOVERY-SUPERVISOR-STOP-1\n'
local MAX_LAUNCHES=4
local function fail(code) error({tag=ERROR,code=code},0) end
local function reason(e)
    if type(e)=='table' and rawget(e,'tag')==ERROR then return rawget(e,'code') end
    return 'supervisor_internal_error'
end
local function permitted(root,mode)
    if mode~='offline_synthetic' or type(root)~='string' then return false end
    local s=root:match('^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$')
    return s and #s==16
end
local function same(a,b) return a and b and a.ino==b.ino and a['dev']==b['dev'] end
local function directory(s) return s and s.type=='dir' and s.uid==0 and s.gid==0 and s.modedec==700 end
local function regular(s,limit)
    return s and s.type=='reg' and s.uid==0 and s.gid==0 and s.modedec==600 and
        s.nlink==1 and type(s.size)=='number' and s.size>=0 and s.size<=limit
end
local function close(fd)
    if not fd then return true end
    local ok,v=pcall(function()return fd:close()end);return ok and v==true
end
local function context(root,mode)
    if not permitted(root,mode) then fail('supervisor_scope_refused') end
    local n,fs=require 'nixio',require 'nixio.fs'
    local parent=fs.lstat(root)
    if not directory(parent) then fail('unsafe_supervisor_directory') end
    return {root=root,n=n,fs=fs,parent=parent,pid=n.getpid()}
end
local function check(c)
    local p=c.fs.lstat(c.root)
    if not directory(p) or not same(p,c.parent) then fail('supervisor_directory_changed') end
    if c.fd then
        local opened=c.fd:stat();local visible=c.fs.lstat(c.root..'/'..LOCK)
        if c.n.getpid()~=c.pid or not regular(opened,0) or not regular(visible,0) or
           not same(opened,c.lock) or not same(visible,c.lock) then fail('supervisor_owner_changed') end
    end
end
local function optional(c,path)
    local st,e=c.fs.lstat(path)
    if st then return st end
    if e~=2 then fail('supervisor_path_unavailable') end
end
local function read(c,name,missing)
    if name~=STATE and name~=STOP then fail('supervisor_file_refused') end
    check(c);local path=c.root..'/'..name;local before=optional(c,path)
    if not before and missing then return nil end
    if not regular(before,512) then fail('unsafe_supervisor_file') end
    local fd=c.n.open(path,c.n.open_flags('rdonly'))
    if not fd then fail('supervisor_read_failed') end
    local ok,raw=pcall(function()
        local opened=fd:stat()
        if not regular(opened,512) or not same(opened,before) then fail('supervisor_file_changed') end
        local bytes=fd:read(513);local after=c.fs.lstat(path)
        if type(bytes)~='string' or #bytes~=opened.size or not regular(after,512) or
           not same(after,opened) or after.size~=opened.size then fail('supervisor_file_changed') end
        return bytes
    end)
    local done=close(fd)
    if not ok then fail(reason(raw)) end
    if not done then fail('supervisor_close_failed') end
    check(c);return raw
end
local function sync(c)
    local fd=c.n.open(c.root,c.n.open_flags('rdonly'))
    if not fd then fail('supervisor_directory_open_failed') end
    local ok,v=pcall(function()
        local st=fd:stat()
        if not directory(st) or not same(st,c.parent) then fail('supervisor_directory_changed') end
        return fd:sync()
    end)
    local done=close(fd)
    if not ok or not done or v~=true then fail('supervisor_directory_sync_failed') end
end
local function write(c,name,raw)
    if name~=STATE and name~=STOP then fail('supervisor_file_refused') end
    if type(raw)~='string' or #raw>512 then fail('supervisor_record_invalid') end
    check(c)
    if name==STATE and c.ledger and read(c,STATE)~=c.ledger then fail('supervisor_record_changed') end
    local final=c.root..'/'..name;local temporary=final..'.new'
    local prior=optional(c,final)
    if prior and not regular(prior,512) then fail('unsafe_supervisor_file') end
    -- A partial launch-budget update is not reset or guessed. Refusal needs
    -- explicit inspection, rather than recreating an unlimited restart budget.
    if optional(c,temporary) then fail('supervisor_interrupted_record') end
    local fd=c.n.open(temporary,c.n.open_flags('wronly','creat','excl'),600)
    if not fd then fail('supervisor_write_open_failed') end
    local ok,result=pcall(function()
        local st=fd:stat()
        if not regular(st,512) or not same(st,c.fs.lstat(temporary)) then fail('supervisor_file_changed') end
        if fd:writeall(raw)~=#raw or fd:sync()~=true then fail('supervisor_write_sync_failed') end
        local after=fd:stat()
        if not regular(after,512) or not same(st,after) or after.size~=#raw or not same(after,c.fs.lstat(temporary)) then
            fail('supervisor_file_changed') end
        return true
    end)
    local done=close(fd)
    if not ok then fail(reason(result)) end
    if not done then fail('supervisor_close_failed') end
    check(c)
    if prior then
        if not same(prior,c.fs.lstat(final)) then fail('supervisor_file_changed') end
    elseif optional(c,final) then fail('supervisor_file_changed') end
    if c.fs.rename(temporary,final)~=true then fail('supervisor_replace_failed') end
    sync(c)
    if read(c,name)~=raw then fail('supervisor_readback_failed') end
    if name==STATE then c.ledger=raw end
end
local function clock(c)
    local t=c.n.sysinfo().uptime
    local b=c.fs.readfile('/proc/sys/kernel/random/boot_id',64)
    if type(t)~='number' or t~=math.floor(t) or t<0 or type(b)~='string' or #b~=37 or
       not b:match('^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+\n$') then
        fail('supervisor_clock_unavailable') end
    return t,b:sub(1,36)
end
local function process(c,pid)
    if type(pid)~='number' or pid<1 or pid~=math.floor(pid) then return nil end
    local path='/proc/'..pid..'/task/'..pid..'/stat'
    local raw=c.fs.readfile(path,4096)
    local tail=type(raw)=='string' and raw:match('^%d+ %(.+%) (.+)$')
    if not tail then return nil end
    local f={};for v in tail:gmatch('%S+') do f[#f+1]=v end
    if #f<20 or not f[20]:match('^%d+$') then return nil end
    return {state=f[1],start=f[20]}
end
local function active(p)
    return p and p.state~='Z' and p.state~='X' and p.state~='T' and p.state~='t'
end
local function stop_requested(c)
    local raw=read(c,STOP,true)
    if raw==nil then return false end
    if raw~=STOP_BYTES then fail('supervisor_stop_invalid') end
    return true
end
local function encode(s)
    return table.concat({'AOTT-RECOVERY-SUPERVISOR-1',s.boot,tostring(s.started),tostring(s.until_time),
        tostring(s.launches),tostring(s.last_launch),s.phase,''},'\n')
end
local function decode(raw)
    local v={};for x in raw:gmatch('([^\n]*)\n') do v[#v+1]=x end
    if #v~=7 or v[1]~='AOTT-RECOVERY-SUPERVISOR-1' or #v[2]~=36 or
       not v[2]:match('^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+$') then fail('supervisor_record_invalid') end
    for i=3,6 do if #v[i]>12 or not v[i]:match('^%d+$') or tostring(tonumber(v[i]))~=v[i] then fail('supervisor_record_invalid') end end
    if not ({running=true,complete=true,stopped=true,exhausted=true,failed=true})[v[7]] then fail('supervisor_record_invalid') end
    local s={boot=v[2],started=tonumber(v[3]),until_time=tonumber(v[4]),launches=tonumber(v[5]),last_launch=tonumber(v[6]),phase=v[7]}
    if s.until_time<=s.started or s.until_time-s.started>600 or s.launches>MAX_LAUNCHES or
       s.last_launch<s.started or s.last_launch>s.until_time or encode(s)~=raw then fail('supervisor_record_invalid') end
    return s
end
local function drain(c)
    local tx=require '8311.vlan_transaction'
    local start=clock(c)
    for _=1,60 do
        check(c)
        local result,why=tx.recover(c.root,'offline_synthetic',false)
        if result then return true,result.phase end
        if why=='transaction_not_armed' then return true,'unarmed' end
        if why~='transaction_busy'and why~='environment_lease_busy' then return nil,'supervisor_recovery_refused' end
        if clock(c)-start>=5 then break end
        c.n.nanosleep(0,100000000)
    end
    return nil,'supervisor_recovery_busy'
end
local function worker(c,parent_id,parent_start,deadline)
    -- Child does not inherit ownership of the parent's POSIX lock. Closing its
    -- descriptor cannot release the parent's lock and prevents orphaned fds.
    local inherited=c.fd;c.fd=nil
    if not close(inherited) then return 70 end
    local p=process(c,parent_id)
    if c.n.getppid()~=parent_id or not active(p) or p.start~=parent_start then return 70 end
    local now=clock(c);local remaining=deadline-now
    if remaining<5 or remaining>600 then return 70 end
    local gate=require '8311.recovery_admission'
    local h=gate.acquire(c.root,remaining,'offline_synthetic')
    if not h then return 71 end
    local closed=false
    local function release()
        if not closed then closed=gate.close(h)~=nil end
        return closed
    end
    local ok,code=pcall(function()
        for _=1,6500 do
            check(c)
            local t=clock(c);local parent_state=process(c,parent_id)
            local gone=c.n.getppid()~=parent_id or not active(parent_state) or parent_state.start~=parent_start
            if gone or stop_requested(c) or t>=deadline then
                if not release() then return 72 end
                local done=drain(c)
                return done and 20 or 73
            end
            local result=gate.step(h,'offline_synthetic')
            if not result then return 74 end
            if result.phase=='confirmed' or result.phase=='rolled_back' then return 0 end
            c.n.nanosleep(0,100000000)
        end
        return 75
    end)
    local released=release()
    if not ok or not released then return 76 end
    return code
end
local function reaped(c)
    if not c.child then return true end
    local pid,kind,value=c.n.waitpid(c.child,'nohang')
    if pid==false then return false end
    if pid==c.child then c.child=nil;return true,kind,value end
    fail('supervisor_child_wait_unverified')
end
local function terminate_child(c)
    if not c.child or reaped(c) then return true end
    -- Only an unreaped direct child is signalled. Its PID cannot be recycled
    -- while waitpid still establishes that it is our unreaped child.
    if c.n.kill(c.child,15)~=true and not reaped(c) then fail('supervisor_child_signal_failed') end
    local until_time=clock(c)+1
    while c.child and clock(c)<until_time do
        if reaped(c) then return true end
        c.n.nanosleep(0,50000000)
    end
    if c.child then
        if reaped(c) then return true end
        if c.n.kill(c.child,9)~=true and not reaped(c) then fail('supervisor_child_signal_failed') end
        local pid=c.n.waitpid(c.child)
        if pid~=c.child then fail('supervisor_child_reap_failed') end
        c.child=nil
    end
    return true
end
local function summary(s,status,recovery)
    return {status=status,launches=s.launches,restarts=math.max(0,s.launches-1),phase=s.phase,
        recovery=recovery,source_only_not_deployed=true,no_live_service_change=true,
        physical_recovery_unqualified=true}
end
local function loop(c,budget)
    local now,boot=clock(c)
    local raw=read(c,STATE,true);local s
    if raw then
        s=decode(raw);c.ledger=raw
        if s.phase~='running' or s.boot~=boot or now<s.started or now>=s.until_time then fail('supervisor_session_not_resumable') end
    else
        s={boot=boot,started=now,until_time=now+budget,launches=0,last_launch=now,phase='running'}
        write(c,STATE,encode(s))
    end
    c.session=s
    local gate=require '8311.recovery_admission'
    local tx=require '8311.vlan_transaction'
    -- Do not claim, kill or replace an independently owned non-child worker.
    local other=gate.present(c.root,'offline_synthetic')
    if other then fail('supervisor_foreign_worker_present') end
    local parent_state=process(c,c.pid)
    if not active(parent_state) then fail('supervisor_parent_identity_unverified') end
    local parent_start=parent_state.start
    local health_deadline,last_good,seen_ready=nil,nil,false
    for _=1,6500 do
        check(c)
        if read(c,STATE)~=c.ledger then fail('supervisor_record_changed') end
        now,boot=clock(c)
        if boot~=s.boot or now<s.started then fail('supervisor_clock_changed') end
        local stopped=stop_requested(c)
        if stopped or now>=s.until_time then
            -- Worker sees the same stop marker. Give it a bounded opportunity
            -- to finish the existing recovery before escalation.
            if stopped and c.child then
                local grace=now+5
                while c.child and clock(c)<grace do
                    if reaped(c) then break end
                    c.n.nanosleep(0,100000000)
                end
            end
            terminate_child(c)
            local done,phase=drain(c)
            s.phase=done and 'stopped' or 'failed';write(c,STATE,encode(s))
            return summary(s,done and 'SOURCE_SUPERVISOR_STOPPED' or 'SOURCE_SUPERVISOR_RECOVERY_REQUIRED',phase)
        end
        if c.child then
            if reaped(c) then seen_ready=false
            else
                local identity=process(c,c.child)
                local proof=gate.present(c.root,'offline_synthetic')
                local healthy=active(identity) and proof and gate.matches_process(c.root,proof,c.child,identity.start,'offline_synthetic')==true
                if healthy then last_good=now;seen_ready=true
                elseif not active(identity) or (seen_ready and now-last_good>=1) or (not seen_ready and now>=health_deadline) then
                    terminate_child(c);seen_ready=false
                end
            end
        end
        if not c.child then
            local state,why=tx.recovery_offer(c.root,'offline_synthetic')
            if state and (state.phase=='confirmed' or state.phase=='rolled_back') then
                local verified,issue=tx.recover(c.root,'offline_synthetic',false)
                if verified then
                    s.phase='complete';write(c,STATE,encode(s))
                    return summary(s,'SOURCE_SUPERVISOR_COMPLETE',verified.phase)
                elseif issue~='transaction_busy'and issue~='environment_lease_busy' then fail('supervisor_terminal_state_unverified') end
                -- A caller may still hold the transaction lock after writing
                -- its terminal marker. Wait without spawning another worker.
            elseif not state and why~='transaction_not_armed' then fail('supervisor_journal_unverified')
            else
            if s.launches>=MAX_LAUNCHES or s.until_time-now<5 then
                local done,phase=drain(c)
                s.phase='exhausted';write(c,STATE,encode(s))
                return summary(s,done and 'SOURCE_SUPERVISOR_RESTART_LIMIT' or 'SOURCE_SUPERVISOR_RECOVERY_REQUIRED',phase)
            end
            local backoff=s.launches==0 and 0 or 2^(s.launches-1)
            if now>=s.last_launch+backoff then
                s.launches=s.launches+1;s.last_launch=now;write(c,STATE,encode(s))
                io.stdout:flush();io.stderr:flush()
                local child=c.n.fork()
                if type(child)~='number' or child<0 or child~=math.floor(child) then fail('supervisor_fork_failed') end
                if child==0 then
                    -- All worker output is deliberately suppressed; the parent
                    -- emits only a bounded result after final verification.
                    local null=c.n.open('/dev/null','w+')
                    if not null then os.exit(77) end
                    c.n.dup(null,c.n.stdin);c.n.dup(null,c.n.stdout);c.n.dup(null,c.n.stderr)
                    close(null);c.n.nice(10)
                    local ok,code=pcall(worker,c,c.pid,parent_start,s.until_time)
                    os.exit(ok and code or 78)
                end
                c.child=child;c.managed=true;health_deadline=now+3;last_good=now;seen_ready=false
            end
            end
        end
        c.n.nanosleep(0,100000000)
    end
    fail('supervisor_loop_limit')
end
function M.run(root,budget,mode)
    if not permitted(root,mode) then return nil,'supervisor_scope_refused' end
    if type(budget)~='number' or budget~=math.floor(budget) or budget<5 or budget>600 then return nil,'supervisor_budget_invalid' end
    if HELD[root] then return nil,'supervisor_already_owned_in_process' end
    local c,fd
    local ok,result=pcall(function()
        c=context(root,mode);local path=root..'/'..LOCK;local prior=optional(c,path)
        if prior and not regular(prior,0) then fail('unsafe_supervisor_lock') end
        fd=c.n.open(path,prior and c.n.open_flags('rdwr') or c.n.open_flags('rdwr','creat','excl'),600)
        if not fd then fail('supervisor_lock_open_failed') end
        c.fd=fd;c.lock=fd:stat()
        if not regular(c.lock,0) or (prior and not same(prior,c.lock)) then fail('supervisor_owner_changed') end
        check(c)
        if fd:lock('tlock')~=true then fail('supervisor_already_running') end
        HELD[root]=true;c.owns=true
        if not prior then if fd:sync()~=true then fail('supervisor_lock_sync_failed') end;sync(c) end
        if optional(c,root..'/'..STATE..'.new') then fail('supervisor_interrupted_record') end
        return loop(c,budget)
    end)
    if c and c.child then
        local stopped=pcall(terminate_child,c)
        if not stopped then ok=false;result={tag=ERROR,code='supervisor_child_cleanup_unverified'} end
    end
    if not ok and c and c.owns and c.managed and not c.child then
        -- After stopping our own worker, attempt verified restoration if the
        -- workspace/owner are still trusted. Do not touch a foreign worker's
        -- transaction or claim recovery succeeded when these checks refuse.
        pcall(drain,c)
    end
    local done=close(fd)
    if done then HELD[root]=nil else HELD[root]=true;return nil,'supervisor_release_unverified' end
    if not ok then return nil,reason(result) end
    return result
end
function M.request_stop(root,mode)
    local ok,v=pcall(function()
        local c=context(root,mode);local existing=read(c,STOP,true)
        if existing and existing~=STOP_BYTES then fail('supervisor_stop_invalid') end
        if not existing then write(c,STOP,STOP_BYTES) end
        return {status='SOURCE_SUPERVISOR_STOP_REQUESTED',source_only_not_deployed=true}
    end)
    if not ok then return nil,reason(v) end
    return v
end
return M

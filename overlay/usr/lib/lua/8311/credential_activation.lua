-- AoTT-8311 V3 secret-safe live root credential activation.
-- The hash never enters returned data, logs, command arguments or public files.
local nixio=require "nixio"
local fs=require "nixio.fs"
local guard=require "8311.root_credential_guard"
local M={}
local SHADOW="/etc/shadow"
local MAX=16384

local function shadow_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.modedec==600 and st.nlink==1 and type(st.size)=="number" and
        st.size>=1 and st.size<=MAX
end

local function usable(hash)
    if type(hash)~="string" or #hash<16 or #hash>255 or
       hash:find("[%z\1-\31\127:]") or hash:sub(1,1)~="$" then
        return nil,"credential_hash_invalid"
    end
    local ready,why=guard.classify(hash,nixio.crypt)
    if not ready then return nil,why or "credential_hash_invalid" end
    return true
end

local function read_shadow()
    local st=fs.lstat(SHADOW)
    if not shadow_ok(st) then return nil,"shadow_metadata_unsafe" end
    local raw=fs.readfile(SHADOW,MAX+1)
    if type(raw)~="string" or #raw~=st.size or raw:find("%z") then
        return nil,"shadow_read_failed"
    end
    local lines,count,old={},0,nil
    for line in (raw.."\n"):gmatch("(.-)\n") do
        if line~="" then
            local user,hash,rest=line:match("^([^:]+):([^:]*):(.*)$")
            if not user then return nil,"shadow_record_invalid" end
            if user=="root" then
                count=count+1
                old=hash
            end
            lines[#lines+1]={user=user,hash=hash,rest=rest}
        end
    end
    if count~=1 or type(old)~="string" then return nil,"root_shadow_record_not_unique" end
    return lines,old
end

local function write_shadow(hash)
    local ok,why=usable(hash)
    if not ok then return nil,why end
    local lines,old=read_shadow()
    if not lines then return nil,old end
    local out={}
    for _,row in ipairs(lines) do
        out[#out+1]=row.user..":"..(row.user=="root" and hash or row.hash)..":"..row.rest
    end
    local data=table.concat(out,"\n").."\n"
    if #data>MAX then return nil,"shadow_output_too_large" end
    local stage="/etc/.shadow.aott."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"shadow_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"shadow_stage_create_failed" end
    local wrote=fd:writeall(data)
    local synced=wrote==#data and fd:sync()==true
    local closed=fd:close()
    if not synced or not closed then
        fs.unlink(stage)
        return nil,"shadow_stage_write_failed"
    end
    local staged=fs.lstat(stage)
    if not shadow_ok(staged) or staged.size~=#data then
        fs.unlink(stage)
        return nil,"shadow_stage_metadata_invalid"
    end
    if fs.rename(stage,SHADOW)~=true then
        fs.unlink(stage)
        return nil,"shadow_replace_failed"
    end
    local dir=nixio.open("/etc",nixio.open_flags("rdonly"))
    local durable=dir and dir:sync()==true
    if dir then dir:close() end
    if not durable then return nil,"shadow_directory_sync_failed" end
    local entry=nixio.getsp and nixio.getsp("root")
    local live=entry and entry.pwdp
    entry=nil
    if live~=hash then
        live=nil
        return nil,"shadow_readback_mismatch"
    end
    live=nil
    return true,old
end

function M.apply(desired)
    local ok,why=usable(desired)
    if not ok then return nil,why end
    local _,before=read_shadow()
    if type(before)~="string" then return nil,"root_shadow_read_failed" end
    if before==desired then
        return {
            schema=1,success=true,changed=false,
            credential_verified=true,contains_credential_material=false,
            observed_source="root_shadow_exact_hash_match_redacted",
        }
    end
    local changed,write_why=write_shadow(desired)
    if not changed then
        local restored=write_shadow(before)
        if not restored then
            return nil,"credential_apply_failed_and_live_restore_unverified"
        end
        return nil,write_why or "credential_apply_failed"
    end
    return {
        schema=1,success=true,changed=true,
        credential_verified=true,contains_credential_material=false,
        observed_source="root_shadow_exact_hash_match_redacted",
    }
end

function M.restore(previous)
    local ok,why=write_shadow(previous)
    if not ok then return nil,why end
    return {
        schema=1,success=true,restored=true,
        contains_credential_material=false,
    }
end

return M

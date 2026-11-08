-- AoTT-8311 V3 first-GUI-login factory credential prompt.
-- Server-side only. Never exposes password hashes or password material.
local nixio=require "nixio"
local fs=require "nixio.fs"
local guard=require "8311.root_credential_guard"
local M={}
local ROOT="/ptconf/8311"
local ACK=ROOT.."/.factory-password-prompt-v1.ack"
local CONTENT="factory-password-prompt-v1\n"

local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and
        (st.modedec==700 or st.modedec==750 or st.modedec==755)
end
local function file_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.modedec==600 and st.nlink==1 and st.size==#CONTENT
end
local function credential_state()
    if type(nixio.crypt)~="function" then return nil,"credential_check_unavailable" end
    local entry
    if type(nixio.getsp)=="function" then entry=nixio.getsp("root") end
    if not entry and type(nixio.getpw)=="function" then entry=nixio.getpw("root") end
    local hash=entry and (entry.pwdp or entry.passwd)
    local ready,why=guard.classify(hash,nixio.crypt)
    hash=nil
    entry=nil
    if not ready then return nil,why end
    return why
end
local function acknowledged()
    local st=fs.lstat(ACK)
    if not st then return false end
    if not file_ok(st) then return false end
    local data=fs.readfile(ACK,#CONTENT+1)
    return data==CONTENT
end
function M.status()
    local state,why=credential_state()
    if not state then
        return {
            schema=1,prompt_required=false,acknowledged=false,
            credential_state="unavailable",reason=why or "credential_check_unavailable"
        }
    end
    local ack=acknowledged()
    return {
        schema=1,
        credential_state=state,
        acknowledged=ack,
        prompt_required=(state=="factory_default_root_password" and not ack)
    }
end
function M.acknowledge()
    local state,why=credential_state()
    if not state then return nil,why or "credential_check_unavailable" end
    if state~="factory_default_root_password" then
        return {status="factory_prompt_not_required",credential_state=state}
    end
    local parent=fs.lstat(ROOT)
    if not parent then
        if not fs.mkdir(ROOT,700) then return nil,"persistent_prompt_directory_create_failed" end
        parent=fs.lstat(ROOT)
    end
    if not dir_ok(parent) then return nil,"unsafe_persistent_prompt_directory" end
    local current=fs.lstat(ACK)
    if current then
        if acknowledged() then
            return {status="factory_prompt_already_acknowledged",credential_state=state}
        end
        return nil,"unsafe_factory_prompt_marker"
    end
    local stage=ACK..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"factory_prompt_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"factory_prompt_stage_create_failed" end
    local wrote=fd:writeall(CONTENT)
    local synced=wrote==#CONTENT and fd:sync()
    local closed=fd:close()
    if not synced or not closed then
        fs.unlink(stage)
        return nil,"factory_prompt_stage_write_failed"
    end
    local staged=fs.lstat(stage)
    if not file_ok(staged) then
        fs.unlink(stage)
        return nil,"factory_prompt_stage_unsafe"
    end
    if not fs.rename(stage,ACK) then
        fs.unlink(stage)
        return nil,"factory_prompt_marker_rename_failed"
    end
    local dirfd=nixio.open(ROOT,nixio.open_flags("rdonly"))
    local durable=dirfd and dirfd:sync()
    if dirfd then dirfd:close() end
    if not durable then return nil,"factory_prompt_directory_sync_failed" end
    if not acknowledged() then return nil,"factory_prompt_marker_readback_failed" end
    return {status="factory_prompt_acknowledged",credential_state=state}
end

M.ACK_PATH=ACK
return M

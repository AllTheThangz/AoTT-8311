-- AoTT-8311 V3 persistent HTTPS private-key permission hardening.
-- Fixed path only. Never reads key bytes and never changes certificate/UCI data.
local fs=require "nixio.fs"
local M={}
local KEY="/ptconf/8311/uhttpd/uhttpd.key"
local function safe(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.nlink==1 and type(st.modedec)=="number"
end
function M.evaluate(st)
    if not st then return {status="key_absent",change_required=false} end
    if not safe(st) then return nil,"unsafe_https_key_inode" end
    if st.modedec==600 or st.modedec==400 then
        return {status="key_permissions_restricted",change_required=false}
    end
    if st.modedec~=644 then return nil,"unsupported_https_key_mode" end
    return {status="key_permissions_overexposed",change_required=true}
end
function M.run()
    local before=fs.lstat(KEY)
    local assessment,why=M.evaluate(before)
    if not assessment then return nil,why end
    if not assessment.change_required then
        return {status=assessment.status,changed=false}
    end
    if fs.chmod(KEY,600)~=true then return nil,"https_key_chmod_failed" end
    local after=fs.lstat(KEY)
    if not safe(after) or after.dev~=before.dev or after.ino~=before.ino or
       after.modedec~=600 then return nil,"https_key_permission_readback_failed" end
    return {status="key_permissions_hardened",changed=true}
end
M.KEY=KEY
return M

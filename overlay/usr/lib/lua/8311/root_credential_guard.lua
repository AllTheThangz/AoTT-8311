-- AoTT-8311 V3 root-credential deployment guard.
-- Pure classification: no file, environment, network or firmware I/O.
local M={}

local function usable(hash)
    return type(hash)=="string" and #hash>=16 and #hash<=255 and
        hash:sub(1,1)=="$" and
        not hash:find("[%z\1-\31\127:]")
end

function M.classify(hash,crypt)
    if not usable(hash) then return nil,"credential_unusable" end
    if type(crypt)~="function" then return nil,"credential_check_unavailable" end
    local ok,derived=pcall(crypt,"root",hash)
    if not ok or type(derived)~="string" or derived=="" then
        return nil,"credential_check_unavailable"
    end
    if derived==hash then return nil,"known_factory_root_password" end
    return true,"unique_password_configured"
end

return M

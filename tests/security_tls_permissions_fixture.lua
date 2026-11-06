-- Isolated security-status regression. No production files, TLS keys or ONU I/O.
local health_path = assert(arg[1], "Provide the health.lua module path")
local mode, owner, kind = 644, 0, "reg"
local key_path = "/ptconf/8311/uhttpd/uhttpd.key"
local fs = {
    readfile = function(path)
        assert(path == "/etc/shadow")
        return "root:$6$synthetic_hash_value:20000:0:99999:7:::\n"
    end,
    stat = function(path)
        if path == "/root/.ssh/authorized_keys" then
            return {type = "reg", size = 10}
        end
        return nil
    end,
    lstat = function(path)
        assert(path == key_path, "Unexpected local file metadata query")
        if kind == "missing" then return nil end
        return {type=kind, uid=owner, modedec=mode, size=167}
    end
}
package.preload["nixio.fs"] = function() return fs end
package.preload["luci.util"] = function() return {} end
package.preload["8311.tools"] = function()
    return {is_finite=function(v) return type(v)=="number" end}
end
package.preload["8311.webutil"] = function()
    return {capture=function() return 0, "", false end}
end
package.preload["luci.model.uci"] = function()
    local function cursor()
        local u={}
        function u:foreach(cfg,typ,fn)
            if cfg=="dropbear" and typ=="dropbear" then
                return fn({PasswordAuth="0",RootPasswordAuth="0",
                    DirectInterface="lct"})
            end
            if cfg=="uhttpd" and typ=="uhttpd" then
                return fn({key=key_path,redirect_https="1",
                    listen_http={"0" .. ".0.0.0:80"},
                    listen_https={"0" .. ".0.0.0:443"}})
            end
        end
        function u:get(cfg,section,key)
            if cfg=="network" and section=="lct" then
                if key=="ipaddr" then return "192.0.2.1" end
                if key=="gateway" then return "192.0.2.20" end
            end
            return nil
        end
        return u
    end
    return {cursor=cursor}
end
local health=assert(loadfile(health_path))()
local function finding(data,code)
    for _,w in ipairs(data.warnings or {}) do
        if w.code==code then return w end
    end
end
local broad=health.security()
assert(broad.tls_private_key_permissions=="overexposed")
assert(finding(broad,"tls_key_file_permissions"))
assert(not finding(broad,"tls_key_file_integrity"))
assert(broad.authenticated_only==true)
assert(broad.note:find("No secrets"))
for _,v in pairs(broad) do
    assert(v~=key_path, "Private key path leaked in API")
end

mode=600
local restricted=health.security()
assert(restricted.tls_private_key_permissions=="restricted")
assert(not finding(restricted,"tls_key_file_permissions"))
assert(not finding(restricted,"tls_key_file_integrity"))

mode=400
assert(health.security().tls_private_key_permissions=="restricted")

mode=644;kind="lnk"
local symlink=health.security()
assert(symlink.tls_private_key_permissions=="unsafe")
assert(finding(symlink,"tls_key_file_integrity"))
kind="reg";owner=100
assert(health.security().tls_private_key_permissions=="unsafe")
owner=0;kind="missing"
assert(health.security().tls_private_key_permissions=="unsafe")

print("SECURITY_TLS_KEY_MODE_READONLY_FIXTURE_PASS")

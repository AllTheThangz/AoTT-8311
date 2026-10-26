-- AoTT-8311-v2r1: authenticated, read-only telemetry and security status.
-- No confidential configuration values or passwords are serialized.
local fs = require "nixio.fs"
local util = require "luci.util"
local uci_lib = require "luci.model.uci"
local tools = require "8311.tools"
local web = require "8311.webutil"
local M = {}

local allowed_mac = {
    RxGoodPkts=true, TxGoodPkts=true, RxGoodBytes=true, TxGoodBytes=true,
    RxFCSErrorPkts=true, RxDroppedPkts=true, TxDroppedPkts=true,
    TxAcmDroppedPkts=true, RxOverflowError=true, RxAlignErrorPkts=true,
    RxBadBytes=true, RxGoodPausePkts=true,
    TxPauseCount=true, MtuExceedDiscardPkts=true, RxExtendedVlanDiscardPkts=true
}

local function command(argv, maxbytes)
    local code, text, overflow = web.capture(argv, maxbytes or 16384)
    if code ~= 0 or overflow or not text or text == "" then return nil end
    return text
end

local function number(text)
    local x = tonumber(text)
    if not tools.is_finite(x) or x < 0 then return nil end
    return x
end

local function ethtool_mac()
    -- Spawned process is time-bounded, read-only, and output-size-bounded.
    local report = command({"/usr/bin/timeout", "-k", "1", "4",
                            "/usr/sbin/ethtool", "-S", "eth0_0"}, 16384)
    local counters = {}
    if not report then return nil end
    for line in (report .. "\n"):gmatch("(.-)\n") do
        local name, value = line:match("^%s*([%w_]+):%s*(%d+)%s*$")
        if name and allowed_mac[name] then
            local n = number(value)
            if n then counters[name] = n end
        end
    end
    if not counters.RxGoodPkts or not counters.TxGoodPkts then return nil end
    return counters
end

local function gem_status()
    local text = command({"/usr/bin/timeout", "-k", "1", "5",
                           "/usr/bin/pontop", "-g", "GEM/XGEM Port Status", "-b"}, 16384)
    local entries = {}
    if not text then return nil end
    for line in (text .. "\n"):gmatch("(.-)\n") do
        local index, gem, alloc, alloc_state, traffic, maximum, cipher, direction =
            line:match("^%s*(%d+)%s+(%d+)%s+(%S+)%s+(%S+)%s+(%S+)%s+(%d+)%s+(%S+)%s+(.+)%s*$")
        if index and gem then
            local ix, g, size = number(index), number(gem), number(maximum)
            if ix and ix < 256 and g and g <= 4095 and size and #entries < 32 then
                entries[#entries+1] = {
                    index=ix, gem_id=g, alloc_id=number(alloc),
                    allocation=alloc_state:sub(1,24),
                    service=traffic:sub(1,24), max_payload_bytes=size,
                    encryption_label=cipher:sub(1,24),
                    direction=((direction or ""):match("^%s*(.-)%s*$") or ""):sub(1,24)
                }
            end
        end
    end
    if #entries == 0 then return nil end
    return entries
end

local function gem_counters()
    local text = command({"/usr/bin/timeout", "-k", "1", "5",
                           "/usr/bin/pontop", "-g", "GEM/XGEM Port Counters", "-b"}, 16384)
    if not text then return nil end
    local records = {}
    for line in (text .. "\n"):gmatch("(.-)\n") do
        local ix, id, tx_packets, tx_bytes, rx_packets, rx_bytes, key_errors =
            line:match("^%s*(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%s*$")
        if ix then
            local gem = number(id)
            if gem and gem <= 4095 and not records[gem] then
                records[gem] = {
                    us_packets=number(tx_packets), us_bytes=number(tx_bytes),
                    ds_packets=number(rx_packets), ds_bytes=number(rx_bytes),
                    key_errors=number(key_errors)
                }
            end
        end
    end
    return records
end

local function uptime()
    local s = fs.readfile("/proc/uptime", 48)
    return s and number(s:match("^(%d+%.?%d*)"))
end

local function eth_speed()
    local s = fs.readfile("/sys/class/net/eth0_0/speed", 32)
    return s and number(s:match("(%d+)"))
end

function M.performance()
    local snapshot = {
        schema=1,
        device="LL-XS1010 / PRX126-SFP-PON",
        sampled_at=os.time(),
        uptime_seconds=uptime(),
        optics=tools.metrics(),
        eth_speed_mbps=eth_speed(),
        counters=ethtool_mac(),
        gem_ports=gem_status(),
        source="live read-only ONU counters"
    }
    local by_gem = gem_counters()
    for _, item in ipairs(snapshot.gem_ports or {}) do
        item.counters = by_gem and by_gem[item.gem_id] or nil
    end
    -- The optical line terminal provisions GEM/T-CONT bandwidth and encryption.
    -- Do not infer ISP entitlement or packet-level encryption from this field.
    snapshot.interpretation = {
        rates_require_two_samples=true,
        no_counter_reset_imputation=true,
        gem_encryption_olt_controlled=true,
        o5_is_not_wan_proof=true
    }
    return snapshot
end

local function nonblank(x)
    return type(x) == "string" and #x > 0
end

local function aggregate_section(uci, cfg, kind)
    local items = {}
    uci:foreach(cfg, kind, function(section)
        if #items < 6 then items[#items+1] = section end
    end)
    return items
end

local function switch(v)
    if v == "1" or v == "on" then return "enabled" end
    if v == "0" or v == "off" then return "disabled" end
    return "unknown"
end

local function safe_list(item, name)
    local raw = item and item[name]
    local output = {}
    if type(raw) == "string" then raw = {raw} end
    if type(raw) == "table" then
        for _, v in ipairs(raw) do
            if type(v) == "string" and #v <= 85 and #output < 8 then
                output[#output+1] = v
            end
        end
    end
    return output
end

local function root_password_status()
    local shadow = fs.readfile("/etc/shadow", 32768)
    if not shadow then return "unknown" end
    local entry = shadow:match("^root:([^:\n]*)") or shadow:match("\nroot:([^:\n]*)")
    shadow = nil
    if entry == nil then return "unknown" end
    if entry == "" then return "not_set" end
    if entry:sub(1,1) == "!" or entry:sub(1,1) == "*" then return "locked" end
    if entry:sub(1,1) == "$" then return "configured" end
    return "unknown"
end

local function persisted_hash_status()
    -- The secret never appears in stdout, a Lua table, logs, or HTTP.
    -- Executed shell is a constant literal, not composed from request data.
    local code = web.capture({"/bin/sh","-c",
        'v=$(fwenv_get --8311 root_pwhash 2>/dev/null) || exit 3; ' ..
        '[ -n "$v" ] || exit 1; ' ..
        '/usr/libexec/8311-root-hash-valid "$v" >/dev/null 2>&1 || exit 2'},128)
    if code == 0 then return "configured" end
    if code == 1 then return "not_set" end
    if code == 2 then return "invalid" end
    return "unknown"
end

function M.security()
    local u = uci_lib.cursor()
    local dropbear = aggregate_section(u,"dropbear","dropbear")[1]
    local webserver = aggregate_section(u,"uhttpd","uhttpd")[1]
    local management_ip = u:get("network","lct","ipaddr")
    local management_gateway = u:get("network","lct","gateway")
    if not nonblank(management_ip) then management_ip = "unknown" end
    if not nonblank(management_gateway) then management_gateway = "none" end
    local ssh_password = switch(dropbear and dropbear.PasswordAuth)
    local ssh_root_password = switch(dropbear and dropbear.RootPasswordAuth)
    local password = root_password_status()
    local persisted = persisted_hash_status()
    local keys = fs.stat("/etc/dropbear/authorized_keys")
              or fs.stat("/root/.ssh/authorized_keys")
    local authenticated_keys = keys and keys.type == "reg" and keys.size and keys.size > 0 or false
    local https_redirect = switch(webserver and webserver.redirect_https)
    local listeners_http = safe_list(webserver, "listen_http")
    local listeners_https = safe_list(webserver, "listen_https")

    local warnings = {}
    local function warn(severity, code, message)
        warnings[#warnings+1] = {severity=severity,code=code,message=message}
    end
    if password == "not_set" then
        warn("critical","blank_root_password",
             "Root password is empty; blank-password RPC login may be accepted from reachable networks.")
    end
    if password == "not_set" and persisted == "configured" then
        warn("critical","persisted_live_mismatch",
             "A valid saved password hash exists but the running root account is blank. " ..
             "Investigate startup application before trusting persistence; do not restore an unknown credential automatically.")
    end
    if ssh_root_password ~= "disabled" and ssh_password ~= "disabled" then
        warn("warning","ssh_password_login",
             "SSH password authentication is allowed. Verify key recovery before disabling it.")
    end
    if management_ip == management_gateway then
        warn("warning","self_gateway",
             "Management default gateway equals the ONU address; test routing before changing it.")
    end
    if persisted ~= "configured" then
        warn("warning","password_persistence",
             "Durable password-hash status is not verified. Confirm persistence before bank switching.")
    end
    if https_redirect ~= "enabled" then
        warn("warning","http_redirect",
             "HTTP-to-HTTPS redirect is not verified as enabled.")
    end

    return {
        schema=1, sampled_at=os.time(),
        authenticated_only=true,
        root_password=password,
        root_password_persistence=persisted,
        ssh_password_authentication=ssh_password,
        ssh_root_password_authentication=ssh_root_password,
        ssh_authorized_keys_present=not not authenticated_keys,
        ssh_direct_interface=dropbear and dropbear.DirectInterface or "unknown",
        http_redirect=https_redirect,
        http_listeners=listeners_http,
        https_listeners=listeners_https,
        management_address=management_ip,
        management_gateway=management_gateway,
        warnings=warnings,
        note="Read-only configuration report. No secrets or key material are included."
    }
end

return M

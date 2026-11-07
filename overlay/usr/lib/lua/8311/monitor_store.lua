-- AoTT v2r8: small durable record on the vendor's persistent ptconf volume.
-- No daemon, polling, shell evaluation or plaintext collector credential.
local fs = require "nixio.fs"
local nixio = require "nixio"
local json = require "luci.jsonc"

local M = {
    root = "/ptconf/8311-monitoring",
    mounts_file = "/proc/mounts",
}
local names = {
    "log_remote", "log_ip", "log_port", "log_proto",
    "aott_metrics", "aott_metrics_client", "aott_metrics_sha256"
}

local function valid_ipv4(value)
    if type(value) ~= "string" or
        not value:match("^%d+%.%d+%.%d+%.%d+$") then return false end
    local parts = {}
    for part in value:gmatch("%d+") do
        if #part > 3 or (#part > 1 and part:sub(1,1) == "0") then
            return false
        end
        local n = tonumber(part)
        if not n or n > 255 then return false end
        parts[#parts+1] = n
    end
    return #parts == 4 and parts[1] > 0 and parts[1] < 224
end

local function valid_host(value)
    if type(value) ~= "string" or #value > 253 then return false end
    if value == "" then return true end
    if value:find("[^A-Za-z0-9.%-]") or value:find("..", 1, true) or
        value:sub(1,1) == "." or value:sub(-1) == "." then return false end
    local count = 0
    for label in value:gmatch("[^.]+") do
        count = count + 1
        if #label > 63 or label:sub(1,1) == "-" or
           label:sub(-1) == "-" then return false end
    end
    if count < 1 then return false end
    if value:match("^[%d.]+$") then return valid_ipv4(value) end
    return true
end

function M.valid(record)
    if type(record) ~= "table" or record.schema ~= 1 then return false end
    local count = 0
    for key in pairs(record) do
        if key ~= "schema" then
            local found = false
            for _, allowed in ipairs(names) do
                if key == allowed then found = true; break end
            end
            if not found or type(record[key]) ~= "string" then return false end
        end
        count = count + 1
    end
    if count ~= #names + 1 then return false end
    if record.log_remote ~= "0" and record.log_remote ~= "1" then return false end
    if record.aott_metrics ~= "0" and record.aott_metrics ~= "1" then
        return false
    end
    if not valid_host(record.log_ip) or
       (record.log_remote == "1" and record.log_ip == "") then return false end
    if #record.log_port > 5 or
       not record.log_port:match("^%d+$") or
       tonumber(record.log_port) < 1 or tonumber(record.log_port) > 65535 then
        return false
    end
    if record.log_proto ~= "udp" and record.log_proto ~= "tcp" then return false end
    local client, digest = record.aott_metrics_client, record.aott_metrics_sha256
    if client ~= "" and not valid_ipv4(client) then return false end
    if digest ~= "" and (#digest ~= 64 or digest:find("[^0-9a-f]")) then
        return false
    end
    if record.aott_metrics == "1" and (client == "" or digest == "") then
        return false
    end
    return true
end

function M.canonical(record)
    if not M.valid(record) then return nil, "Invalid persistent record" end
    local fields = {'{"schema":1'}
    -- Values are validated to a restricted ASCII set without quotes or escapes.
    for _, key in ipairs(names) do
        fields[#fields+1] = ',"' .. key .. '":"' .. record[key] .. '"'
    end
    fields[#fields+1] = "}\n"
    local output = table.concat(fields)
    if #output > 2048 then return nil, "Persistent record too large" end
    return output
end

function M.mounted()
    local mounts = fs.readfile(M.mounts_file, 32768)
    if type(mounts) ~= "string" then return false end
    for line in mounts:gmatch("[^\n]+") do
        local src, target, typ = line:match("^(%S+)%s+(%S+)%s+(%S+)")
        if target == "/ptconf" and typ == "ubifs" and
           type(src) == "string" and src:match("^ubi%d+:ptconf$") then
            return true
        end
    end
    return false
end

local function verify_dir(create)
    if not M.mounted() then return nil, "Persistent volume unavailable" end
    local stat = fs.lstat(M.root)
    if not stat and create then
        if not fs.mkdir(M.root, 700) then
            return nil, "Persistent directory unavailable"
        end
        stat = fs.lstat(M.root)
    end
    if not stat or stat.type ~= "dir" or stat.uid ~= 0 or
       stat.modedec ~= 700 then
        return nil, "Unsafe persistent directory"
    end
    return true
end

local function verify_file(path)
    local stat = fs.lstat(path)
    if not stat or stat.type ~= "reg" or stat.uid ~= 0 or
       stat.nlink ~= 1 or stat.modedec ~= 600 or
       stat.size < 4 or stat.size > 2048 then
        return nil, "Unsafe or unavailable persistent record"
    end
    return stat
end

function M.read()
    local ok, why = verify_dir(false)
    if not ok then return nil, why end
    local path = M.root .. "/config.json"
    local stat, err = verify_file(path)
    if not stat then return nil, err end
    local bytes = fs.readfile(path, 2049)
    if type(bytes) ~= "string" or #bytes ~= stat.size then
        return nil, "Persistent record read failed"
    end
    local success, record = pcall(json.parse, bytes)
    if not success or type(record) ~= "table" then
        return nil, "Persistent record invalid"
    end
    local canonical = M.canonical(record)
    if not canonical or canonical ~= bytes then
        return nil, "Persistent record noncanonical"
    end
    return record
end

local function equal(a, b)
    if not M.valid(a) or not M.valid(b) then return false end
    for _, key in ipairs(names) do
        if a[key] ~= b[key] then return false end
    end
    return true
end

function M.write(record)
    local bytes, err = M.canonical(record)
    if not bytes then return nil, err end
    local ok, why = verify_dir(true)
    if not ok then return nil, why end
    local existing = M.read()
    if existing and M.canonical(existing) == bytes then return true end
    local final = M.root .. "/config.json"
    local exists = fs.lstat(final)
    if exists then
        local good, whybad = verify_file(final)
        if not good then return nil, whybad end
    end
    local tempfile, fd
    for _=1,4 do
        local random = fs.readfile("/dev/urandom", 12)
        if type(random) ~= "string" or #random ~= 12 then break end
        tempfile = M.root .. "/.candidate." .. nixio.bin.hexlify(random)
        fd = nixio.open(tempfile, nixio.open_flags("wronly","creat","excl"), "0600")
        if fd then break end
    end
    if not fd then return nil, "Cannot allocate persistent temporary file" end
    local n = fd:write(bytes)
    local synced = n == #bytes and fd:sync()
    local closed = fd:close()
    if not synced or not closed then
        fs.unlink(tempfile)
        return nil, "Persistent record could not be synchronized"
    end
    local changed = fs.rename(tempfile, final)
    if not changed then
        fs.unlink(tempfile)
        return nil, "Persistent record rename failed"
    end
    local dirfd = nixio.open(M.root, nixio.open_flags("rdonly"))
    local durable = dirfd and dirfd:sync()
    if dirfd then dirfd:close() end
    if not durable then return nil, "Persistent directory sync failed" end
    local readback = M.read()
    if not readback or not equal(record, readback) then
        return nil, "Persistent record readback failed"
    end
    return true
end

function M.from_snapshot(snapshot)
    if type(snapshot) ~= "table" then return nil end
    local raw = snapshot.original or {}
    local record = {schema=1,
        log_remote=snapshot.log_remote,
        log_ip=snapshot.log_ip,
        log_port=snapshot.log_port,
        log_proto=snapshot.log_proto,
        aott_metrics=snapshot.aott_metrics,
        aott_metrics_client=snapshot.aott_metrics_client,
        aott_metrics_sha256=raw.aott_metrics_sha256 or ""}
    if not M.valid(record) then return nil end
    return record
end

-- UI classification only. This does NOT grant metrics access or permit a
-- write: all authentication and durable/active consistency gates stay intact.
-- A clean first installation has no record directory, verified ptconf UBIFS,
-- and no non-default live logging or collector setting. A missing record
-- inside an existing directory, an unmounted volume, a symlink, or any
-- configured/mismatched credential must remain an actionable warning.
function M.initial_unconfigured(live)
    if type(live) ~= "table" or not M.mounted() or
       fs.lstat(M.root) ~= nil then return false end
    local defaults = {
        log_remote="0", log_ip="", log_port="514", log_proto="udp",
        aott_metrics="0", aott_metrics_client="", aott_metrics_sha256=""
    }
    for _,key in ipairs(names) do
        if live[key] ~= nil and live[key] ~= defaults[key] then
            return false
        end
    end
    return true
end

function M.same_live(live)
    local durable = M.read()
    if not durable or type(live) ~= "table" then return false end
    local candidate = {schema=1}
    local defaults = {
        log_remote="0", log_ip="", log_port="514", log_proto="udp",
        aott_metrics="0", aott_metrics_client="", aott_metrics_sha256=""
    }
    for _, key in ipairs(names) do
        local value = live[key]
        if value == nil then value = defaults[key] end
        if type(value) ~= "string" then return false end
        candidate[key] = value
    end
    -- The inherited OpenWrt logger enables forwarding by default if a
    -- destination exists and log_remote was omitted.
    if live.log_remote == nil and candidate.log_ip ~= "" then
        candidate.log_remote = "1"
    end
    return equal(durable, candidate)
end

return M

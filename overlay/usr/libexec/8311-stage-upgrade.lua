#!/usr/bin/lua
-- Strict, bounded staging for the legacy 8311 five-file upgrade format.
-- Never runs an archive's upgrade.sh and never extracts an archive pathname.
local archive, directory, expected = arg[1], arg[2], tonumber(arg[3])
local limits = { control=4096, ["upgrade.sh"]=65536,
    ["kernel.bin"]=8388608, ["bootcore.bin"]=8388608, ["rootfs.img"]=33554432 }
local seen, total = {}, 0
local function fail(message) error(message, 0) end
local function run()
    if not archive or not directory or not expected or expected < 1024 or
       expected > 134217728 or expected % 512 ~= 0 then fail("Invalid archive size") end
    local input = assert(io.open(archive, "rb"))
    if input:seek("end") ~= expected or input:seek("set", 0) ~= 0 then fail("Archive changed or is not seekable") end
    local function read(n)
        local data = input:read(n)
        if not data or #data ~= n then fail("Truncated archive") end
        total = total + n
        if total > expected then fail("Archive exceeds its size bound") end
        return data
    end
    local function octal(value)
        -- Base-256, negative, malformed, or unbounded numeric fields are unsupported.
        if not value:match("^[0-7]+[%z ]*$") and not value:match("^ *[0-7]+[%z ]*$") then
            fail("Invalid tar numeric field")
        end
        local digits = value:match("[0-7]+")
        local n = tonumber(digits, 8)
        if not n or n > 134217728 then fail("Tar numeric field exceeds limit") end
        return n
    end
    local zero = string.rep("\0", 512)
    while true do
        local header = read(512)
        if header == zero then
            if read(512) ~= zero then fail("Missing second tar end block") end
            while total < expected do
                if read(math.min(65536, expected-total)):find("[^%z]") then fail("Trailing archive data") end
            end
            if input:read(1) ~= nil then fail("Archive grew while staging") end
            assert(input:close())
            break
        end
        local magic = header:sub(258,265)
        if magic ~= "ustar\0" .. "00" and magic ~= "ustar  \0" then fail("Unsupported tar format") end
        local stored = octal(header:sub(149,156))
        local checksum = 8 * 32
        for i=1,512 do if i < 149 or i > 156 then checksum = checksum + header:byte(i) end end
        if checksum ~= stored then fail("Bad tar header checksum") end
        local name = header:sub(1,100):match("^([^%z]*)")
        local kind = header:sub(157,157)
        if (kind ~= "0" and kind ~= "\0") or not limits[name] or seen[name] then
            fail("Unknown, duplicate, or non-regular member")
        end
        -- POSIX prefix and link fields must be empty, including padding.
        if header:sub(158,257):find("[^%z]") or header:sub(346,500):find("[^%z]") then
            fail("Archive paths, links and extension headers are unsupported")
        end
        local size = octal(header:sub(125,136))
        if size < 1 or size > limits[name] then fail("Member size outside limit: " .. name) end
        seen[name] = true
        local output
        if name ~= "upgrade.sh" then output = assert(io.open(directory .. "/" .. name, "wb")) end
        local remaining = size
        while remaining > 0 do
            local data = read(math.min(65536, remaining))
            if name == "control" and data:find("[^\10\32-\126]") then fail("Invalid control text") end
            if output then assert(output:write(data)) end
            remaining = remaining - #data
        end
        if output then assert(output:close()) end
        local padding = (512 - size % 512) % 512
        if padding > 0 and read(padding):find("[^%z]") then fail("Nonzero member padding") end
    end
    for _,name in ipairs({"control", "kernel.bin", "bootcore.bin", "rootfs.img"}) do
        if not seen[name] then fail("Missing member: " .. name) end
    end
end
local ok, message = pcall(run)
if not ok then io.stderr:write("Upgrade archive rejected: ", tostring(message), "\n"); os.exit(1) end

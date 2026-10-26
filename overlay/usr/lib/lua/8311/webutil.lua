-- Bounded local I/O shared by the 8311 management handlers.
local fs = require "nixio.fs"
local nixio = require "nixio"
local sys = require "luci.sys"
local json = require "luci.jsonc"
local M = {}

function M.capture(argv, limit)
	local chunks, size, overflow = {}, 0, false
	local function collect(data)
		data = data or ""; size = size + #data
		if size <= (limit or 65536) then chunks[#chunks+1] = data else overflow = true end
	end
	local result = sys.process.exec(argv, collect, collect)
	if not result then return nil, "Unable to start command" end
	return result.code, table.concat(chunks), overflow
end

function M.private_dir(prefix)
	for _ = 1, 4 do
		local id = sys.uniqueid(16)
		if type(id) ~= "string" or not id:match("^[a-f0-9]+$") or #id ~= 32 then
			return nil, "Random identifier unavailable"
		end
		local path = prefix .. id
		if fs.mkdir(path, 700) then return path, id end
	end
	return nil, "Unable to allocate private directory"
end

function M.write(path, data, mode)
	local file, err = io.open(path, "wb")
	if not file then return nil, "Unable to open temporary file" end
	local wrote = file:write(data)
	local closed = file:close()
	if not wrote or not closed or not fs.chmod(path, mode or 600) then
		fs.unlink(path); return nil, "Unable to complete file write"
	end
	return true
end

function M.digest(path)
	local code, text, overflow = M.capture({"/usr/bin/sha256sum", path}, 512)
	local digest = text and text:match("^([a-f0-9]+) ")
	if code ~= 0 or overflow or not digest or #digest ~= 64 then
		return nil, "Unable to verify SHA-256 digest"
	end
	return digest
end

function M.digest_text(data)
	local dir, err = M.private_dir("/tmp/8311-digest-")
	if not dir then return nil, err end
	local path = dir .. "/data"
	local ok, why = M.write(path, data)
	local digest
	if ok then digest, why = M.digest(path) end
	local cleaned = (not fs.lstat(path) or fs.unlink(path)) and fs.rmdir(dir)
	if not cleaned then return nil, "Unable to remove temporary digest file" end
	return digest, why
end

function M.read_json(path, maximum)
	local st = fs.lstat(path)
	if not st or st.type ~= "reg" or st.uid ~= 0 or st.nlink ~= 1 or st.size > (maximum or 65536) then return nil end
	local data = fs.readfile(path, (maximum or 65536)+1)
	if not data or #data ~= st.size then return nil end
	local value = json.parse(data)
	return type(value) == "table" and value or nil
end

function M.reply(http, code, record)
	http.status(code, code < 400 and "OK" or "Request failed")
	http.prepare_content("application/json")
	http.header("Cache-Control", "no-store")
	http.write_json(record)
end

-- Fcntl locking is used only for this module's private upload-store metadata.
-- Environment and hook execution use their separate shared flock contracts.
function M.lock(path)
	local stat = fs.lstat(path)
	if stat and (stat.type ~= "reg" or stat.uid ~= 0 or stat.modedec ~= 600 or stat.nlink ~= 1) then return nil, "Unsafe operation lock" end
	local flags = stat and nixio.open_flags("rdwr") or nixio.open_flags("rdwr", "creat", "excl")
	local fd = nixio.open(path, flags, 600)
	if not fd then return nil, "Unable to open operation lock" end
	local now, held = fs.lstat(path), fd:stat()
	if not now or not held or now.ino ~= held.ino or now.dev ~= held.dev then fd:close(); return nil, "Operation lock changed" end
	if not fd:lock("tlock") then fd:close(); return nil, "Another operation is in progress" end
	return fd
end

return M

local fs = require "nixio.fs"
local web = require "8311.webutil"
local json = require "luci.jsonc"
local M = { maximum=24*1024*1024, budget=64*1024*1024 }
local root = "/tmp/8311-web-uploads"
local lifetime = 3600

local function id_ok(id) return type(id) == "string" and #id == 32 and id:match("^[a-f0-9]+$") end
local function ensure_root()
	local stat = fs.lstat(root)
	if not stat then
		if not fs.mkdir(root, 700) then return nil, "Unable to create upload store" end
	elseif stat.type ~= "dir" or stat.uid ~= 0 or stat.modedec ~= 700 then return nil, "Invalid upload store" end
	return true
end

local function remove(id)
	local dir = root .. "/" .. id
	for _, name in ipairs({"partial", "firmware.tar", "metadata.json"}) do
		local path = dir .. "/" .. name
		if fs.lstat(path) and not fs.unlink(path) then return nil, "Unable to remove upload file" end
	end
	if not fs.rmdir(dir) then return nil, "Unable to remove upload directory" end
	return true
end

local function metadata(id)
	if not id_ok(id) then return nil end
	local dir = root .. "/" .. id
	local stat = fs.lstat(dir)
	if not stat or stat.type ~= "dir" or stat.uid ~= 0 or stat.modedec ~= 700 then return nil end
	local record = web.read_json(dir .. "/metadata.json", 4096)
	if type(record) ~= "table" or record.id ~= id or record.schema ~= 1 then return nil end
	return record
end

function M.get(id, owner)
	local store = fs.lstat(root)
	if not store or store.type ~= "dir" or store.uid ~= 0 or store.modedec ~= 700 then return nil, "Invalid upload store" end
	local record = metadata(id)
	if not record or type(owner) ~= "string" or record.owner ~= owner or record.state ~= "complete" then
		return nil, "Upload is missing or belongs to another session"
	end
	local path = root .. "/" .. id .. "/firmware.tar"
	local stat = fs.lstat(path)
	if not stat or stat.type ~= "reg" or stat.uid ~= 0 or stat.nlink ~= 1 or stat.modedec ~= 400 or
	   type(record.size) ~= "number" or stat.size ~= record.size or record.size < 1 or record.size > M.maximum or
	   type(record.sha256) ~= "string" or #record.sha256 ~= 64 or not record.sha256:match("^[a-f0-9]+$") then
		return nil, "Upload identity or size check failed"
	end
	return {upload_id=id,path=path,sha256=record.sha256,size=record.size,filename=record.filename,created=record.created}
end

function M.list(owner)
	local records = {}
	for id in fs.dir(root) or function() end do
		if id_ok(id) then
			local record = M.get(id, owner)
			if record then record.path=nil; records[#records+1]=record end
		end
	end
	table.sort(records, function(a,b) return a.created > b.created end)
	return records
end

function M.discard(id, owner)
	local ok, err = ensure_root(); if not ok then return nil, err end
	local lock, why = web.lock(root .. "/store.lock"); if not lock then return nil, why end
	local record, error = M.get(id, owner)
	if not record then lock:close(); return nil, error end
	local removed, problem = remove(id)
	lock:close()
	return removed, problem
end

function M.receive(http, owner)
	if type(owner) ~= "string" or owner == "" then return nil, "Authenticated session required", 403 end
	if not (http.getenv("CONTENT_TYPE") or ""):match("^multipart/form%-data[; ]") then
		return nil, "Use a multipart firmware upload", 415
	end
	local ok, err = ensure_root(); if not ok then return nil, err, 507 end
	local lock, why = web.lock(root .. "/store.lock"); if not lock then return nil, why, 409 end
	local used, count = 0, 0
	for id in fs.dir(root) or function() end do
		if id_ok(id) then
			local record = metadata(id)
			if record and type(record.created) == "number" and os.time()-record.created > lifetime then
				local removed = remove(id)
				if removed then record = nil end
			end
			if record then used=used+(tonumber(record.size) or M.maximum); count=count+1
			elseif fs.lstat(root .. "/" .. id) then used=used+M.maximum; count=count+1 end
		end
	end
	local memory = fs.readfile("/proc/meminfo") or ""
	local available = tonumber(memory:match("MemAvailable:%s+(%d+)"))
	if used+M.maximum > M.budget or count >= 8 or not available or available*1024 < M.maximum+32*1024*1024 then
		lock:close(); return nil, "Upload byte budget is exhausted; discard an old upload or retry later", 507
	end
	local dir, id = web.private_dir(root .. "/")
	if not dir then lock:close(); return nil, id, 507 end
	local record = {schema=1,id=id,owner=owner,created=os.time(),size=M.maximum,state="receiving"}
	local saved, error = web.write(dir .. "/metadata.json", json.stringify(record), 600)
	if not saved then fs.rmdir(dir); lock:close(); return nil, error, 507 end
	local handle, field, complete, bytes, failure, failure_code = nil, nil, false, 0, nil, nil
	local function reject(message, code)
		failure, failure_code = message, code; return false, message
	end
	if not http.setbodylimit(M.maximum + 65536) then
		remove(id); lock:close(); return nil, "Upload body was already parsed", 400
	end
	http.setfilehandler(function(meta, chunk, eof)
		if failure then return false, failure end
		if not meta or meta.name ~= "firmware_file" or type(meta.file) ~= "string" then return reject("Unexpected upload part") end
		if field and (field ~= meta or complete) then return reject("Only one firmware file is allowed") end
		if not field then
			field = meta
			record.filename = meta.file:gsub("[%z\1-\31\127/\\]", "_"):sub(1,128)
			handle = io.open(dir .. "/partial", "wb")
			if not handle then return reject("Unable to open upload file", 507) end
		end
		if chunk and #chunk > 0 then
			bytes=bytes+#chunk
			if bytes > M.maximum then return reject("Firmware file exceeds 24 MiB", 413) end
			if not handle:write(chunk) then return reject("Upload write failed", 507) end
		end
		if eof then
			local closed = handle:close(); handle=nil
			if not closed then return reject("Upload close failed", 507) end
			complete=true
		end
		return true
	end)
	local values = http.formvalue()
	local parse_error, parse_code = http.inputerror()
	if handle then handle:close(); handle=nil end
	if type(values) == "table" then
		for name in pairs(values) do if name ~= "firmware_file" then failure="Unexpected multipart field" end end
	end
	if parse_error or failure or not complete or bytes == 0 then
		local cleaned, cleanup_error = remove(id); lock:close()
		return nil, (failure or parse_error or "Incomplete or empty upload") .. (not cleaned and ("; cleanup failed: " .. cleanup_error) or ""), failure_code or (parse_error and parse_code) or 400
	end
	if not fs.chmod(dir .. "/partial", 400) or not fs.rename(dir .. "/partial", dir .. "/firmware.tar") then
		remove(id); lock:close(); return nil, "Unable to seal firmware upload", 507
	end
	local digest, digest_error = web.digest(dir .. "/firmware.tar")
	if not digest then remove(id); lock:close(); return nil, digest_error, 507 end
	record.sha256, record.size, record.state = digest, bytes, "complete"
	local wrote, write_error = web.write(dir .. "/metadata.json", json.stringify(record), 600)
	if not wrote then remove(id); lock:close(); return nil, write_error, 507 end
	lock:close()
	local result, get_error = M.get(id, owner)
	if not result then return nil, get_error, 502 end
	result.path=nil
	return result
end

return M

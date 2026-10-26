-- Session-owned, bounded background jobs. All executable paths are fixed here.
local nixio = require "nixio"
local fs = require "nixio.fs"
local json = require "luci.jsonc"
require "nixio.util"
local M = {}
local ROOT = "/tmp/8311-web-jobs"
local UPLOADS = "/tmp/8311-web-uploads"
local WORKER = "/usr/libexec/8311-job-worker"
local MAX_UPLOAD, MAX_ARCHIVE = 24 * 1024 * 1024, 32 * 1024 * 1024
local MAX_BYTES, MAX_JOBS, TTL = 96 * 1024 * 1024, 12, 7200
local OUTPUT_LIMIT = 8192
local kinds = { firmware_validate=true, firmware_install=true, bank_operation=true, support=true }
local bank_actions = {verify="check-json", trial="trial", commit="commit", cancel_trial="cancel-trial", return_saved="rollback", reboot="reboot"}
local terminal = { succeeded=true, failed=true, cancelled=true }

local function ident(s)
	return type(s) == "string" and #s == 32 and not s:find("[^0-9a-f]")
end

local function owner_ok(s)
	return type(s) == "string" and #s >= 16 and #s <= 128 and not s:find("[^%w_-]")
end

local function private(path, kind, mode)
	local st = fs.lstat(path)
	return st and st.type == kind and st.uid == 0 and st.modedec == mode
		and (kind ~= "reg" or st.nlink == 1) and st
end

local function directory(path, create)
	if not fs.lstat(path) and create then fs.mkdir(path, 700) end
	return private(path, "dir", 700)
end

local function read_json(path, limit)
	local st = private(path, "reg", 600)
	if not st or st.size > (limit or 16384) then return nil end
	local data = fs.readfile(path, (limit or 16384) + 1)
	if not data or #data ~= st.size then return nil end
	local ok, value = pcall(json.parse, data)
	return ok and type(value) == "table" and value or nil
end

local function atomic(path, value)
	local name = path .. ".new." .. tostring(nixio.getpid())
	local f = nixio.open(name, nixio.open_flags("wronly", "creat", "excl"), 600)
	if not f then return nil, "Cannot create private job record" end
	local data = json.stringify(value) .. "\n"
	local count = f:writeall(data)
	local closed = f:close()
	if count ~= #data or not closed or not fs.rename(name, path) then
		fs.unlink(name)
		return nil, "Cannot write complete job record"
	end
	return true
end

local function lock_store()
	if not directory(ROOT, true) then return nil, "Unsafe job store" end
	local path = ROOT .. "/store.lock"
	local st = fs.lstat(path)
	if st and not private(path, "reg", 600) then return nil, "Unsafe job lock" end
	local flags = st and nixio.open_flags("rdwr") or nixio.open_flags("rdwr", "creat", "excl")
	local fd = nixio.open(path, flags, 600)
	if not fd then return nil, "Cannot open job lock" end
	local now, held = private(path, "reg", 600), fd:stat()
	if not now or now.ino ~= held.ino or now.dev ~= held.dev or not fd:lock("tlock") then
		fd:close()
		return nil, "Another job request is in progress; retry shortly"
	end
	return fd
end

local function token()
	local bytes = fs.readfile("/dev/urandom", 16)
	return bytes and #bytes == 16 and nixio.bin.hexlify(bytes) or nil
end

local function proc_identity(pid)
	if type(pid) ~= "number" or pid < 1 or pid ~= math.floor(pid) then return nil end
	local leader = tostring(pid)
	local s = fs.readfile("/proc/" .. leader .. "/task/" .. leader .. "/stat", 4096)
	local rest = s and s:match("^%d+ %(.+%) (.+)$")
	if not rest then return nil end
	local fields = {}
	for word in rest:gmatch("%S+") do fields[#fields+1] = word end
	if fields[1] == "Z" or fields[1] == "X" then return nil end
	return fields[20]
end

-- Stream and discard excess output while retaining only a bounded tail.
-- No shell parses argv, and command completion always has a checked status.
local function run(argv, callback)
	local input, output = nixio.pipe()
	if not input then return 127, "Cannot create command pipe" end
	local pid = nixio.fork()
	if not pid then input:close(); output:close(); return 127, "Cannot fork command" end
	if pid == 0 then
		input:close()
		local null = nixio.open("/dev/null", "r")
		if not null or not nixio.dup(null, nixio.stdin)
			or not nixio.dup(output, nixio.stdout) or not nixio.dup(output, nixio.stderr) then os.exit(127) end
		null:close(); output:close()
		nixio.exec(unpack(argv))
		os.exit(127)
	end
	output:close()
	local tail = ""
	while true do
		local chunk, errno = input:read(4096)
		if not chunk then
			if errno ~= nixio.const.EINTR then break end
		elseif #chunk == 0 then break
		else
			tail = (tail .. chunk):sub(-OUTPUT_LIMIT)
			if callback then callback(tail) end
		end
	end
	input:close()
	local waited, why, code
	repeat waited, why, code = nixio.waitpid(pid) until waited or why ~= nixio.const.EINTR
	if not waited or why ~= "exited" then return 128, tail end
	return code, tail
end

local function digest(path)
	local code, out = run({"/usr/bin/sha256sum", path})
	local value = out and out:match("^([0-9a-f]+)%s")
	return code == 0 and value and #value == 64 and value or nil
end

local function enough_space(bytes)
	local mem = fs.readfile("/proc/meminfo", 8192) or ""
	local kb = tonumber(mem:match("MemAvailable:%s*(%d+)"))
	if not kb then kb = tonumber(mem:match("MemFree:%s*(%d+)")) end
	if not kb or kb * 1024 < bytes + 32 * 1024 * 1024 then return false end
	local disk = fs.statvfs(ROOT)
	if not disk then return false end
	-- This firmware's ramfs reports zero blocks; use the RAM check above.
	if disk.blocks > 0 and disk.bavail * disk.frsize < bytes + 8 * 1024 * 1024 then return false end
	return true
end

local function load_job(id, owner)
	if not ident(id) or not owner_ok(owner) or not directory(ROOT) then return nil, "Job not found" end
	local dir = ROOT .. "/" .. id
	if not directory(dir) then return nil, "Job not found" end
	local request = read_json(dir .. "/request.json")
	local record = read_json(dir .. "/status.json")
	if not request or request.id ~= id or request.owner ~= owner or not kinds[request.kind]
		or not record or record.id ~= id or record.kind ~= request.kind then return nil, "Job not found" end
	return record, request, dir
end

local function public(record, dir)
	local result = {}
	for _, key in ipairs({"id", "kind", "state", "exitcode", "output", "error", "partial", "created", "updated", "download_ready"}) do
		result[key] = record[key]
	end
	result.output = tostring(result.output or ""):sub(-OUTPUT_LIMIT)
	if not terminal[result.state] then
		if record.pid and proc_identity(record.pid) ~= record.pid_start then
			-- The worker can commit its final record and exit between our
			-- first status read and the process check. Re-read before failure.
			local latest = read_json(dir .. "/status.json")
			if latest and latest.id == record.id and latest.kind == record.kind
				and terminal[latest.state] then return public(latest, dir) end
			result.state, result.error = "failed", "Job worker stopped unexpectedly. Check bank status before retrying firmware work."
		elseif not record.pid and os.time() - (record.created or 0) > 30 then
			result.state, result.error = "failed", "Job worker did not start. Check bank status before retrying firmware work."
		elseif result.kind == "support" and private(dir .. "/cancel", "reg", 600) then
			result.state = "cancel_requested"
		end
	end
	return result
end

function M.get(id, owner)
	local record, request, dir = load_job(id, owner)
	if not record then return nil, request end
	return public(record, dir)
end

local function inventory()
	local count, bytes, active_firmware, active_support, pending_bytes = 0, 0, false, false, 0
	for id in fs.dir(ROOT) do
		if ident(id) and directory(ROOT .. "/" .. id) then
			local dir = ROOT .. "/" .. id
			local record = read_json(dir .. "/status.json")
			-- Interrupted operations remain for investigation, never auto-delete.
			if record and terminal[record.state] and os.time() - (record.updated or 0) > TTL then
				fs.remover(dir)
			else
				count = count + 1
				for name in fs.dir(dir) do
					local st = fs.lstat(dir .. "/" .. name)
					if st and st.type == "reg" then bytes = bytes + st.size end
				end
				if not record or not terminal[record.state] then
					if record and record.kind == "support" then
						active_support = true
						local st = fs.lstat(dir .. "/support.tar.gz")
						local remaining = math.max(0, MAX_ARCHIVE - (st and st.type == "reg" and st.size or 0))
						bytes, pending_bytes = bytes + remaining, pending_bytes + remaining
					else active_firmware = true end
				end
			end
		end
	end
	return count, bytes, active_firmware, active_support, pending_bytes
end

local function copy_upload(args, owner, dest)
	if type(args) ~= "table" or not ident(args.upload_id) or type(args.sha256) ~= "string"
		or #args.sha256 ~= 64 or args.sha256:find("[^0-9a-f]")
		or type(args.size) ~= "number" or args.size ~= math.floor(args.size)
		or args.size < 1024 or args.size > MAX_UPLOAD then return nil, "Invalid upload identity" end
	local parent = UPLOADS .. "/" .. args.upload_id
	local path = parent .. "/firmware.tar"
	if args.path ~= path or not directory(UPLOADS) or not directory(parent) then return nil, "Unsafe upload path" end
	local metadata = read_json(parent .. "/metadata.json")
	local st = private(path, "reg", 400)
	if not metadata or metadata.schema ~= 1 or metadata.id ~= args.upload_id or metadata.owner ~= owner
		or metadata.size ~= args.size or metadata.sha256 ~= args.sha256 or not st or st.size ~= args.size then
		return nil, "Upload ownership or identity changed"
	end
	local input = nixio.open(path, "r")
	if not input then return nil, "Upload is no longer available" end
	local opened = input:stat()
	if opened.ino ~= st.ino or opened.dev ~= st.dev or opened.type ~= "reg" then input:close(); return nil, "Upload changed" end
	local output = nixio.open(dest, nixio.open_flags("wronly", "creat", "excl"), 600)
	if not output then input:close(); return nil, "Cannot reserve job input" end
	local total, good = 0, true
	while true do
		local chunk = input:read(65536)
		if not chunk then good = false; break end
		if #chunk == 0 then break end
		total = total + #chunk
		if total > args.size or output:writeall(chunk) ~= #chunk then good = false; break end
	end
	input:close()
	if not output:close() then good = false end
	if not good or total ~= args.size or not fs.chmod(dest, 400) or digest(dest) ~= args.sha256 then
		fs.unlink(dest)
		return nil, "The copied upload failed its size or checksum verification"
	end
	return {upload_id=args.upload_id, sha256=args.sha256, size=args.size}
end

local function launch(id)
	local pid = nixio.fork()
	if not pid then return nil, "Cannot launch job worker" end
	if pid == 0 then
		if not nixio.setsid() then os.exit(127) end
		local child = nixio.fork()
		if not child then os.exit(127) end
		if child > 0 then os.exit(0) end
		local null = nixio.open("/dev/null", nixio.open_flags("rdwr"))
		if not null or not nixio.dup(null, nixio.stdin) or not nixio.dup(null, nixio.stdout)
			or not nixio.dup(null, nixio.stderr) then os.exit(127) end
		null:close()
		nixio.exec("/bin/busybox", "ash", WORKER, id)
		os.exit(127)
	end
	local waited, why, code
	repeat waited, why, code = nixio.waitpid(pid) until waited or why ~= nixio.const.EINTR
	if not waited then return nil, "Worker launch state is uncertain; inspect the job before retrying", true end
	if why ~= "exited" then return nil, "Worker launch state is uncertain; inspect the job before retrying", true end
	if code ~= 0 then return nil, "Cannot detach job worker" end
	return true
end

function M.start(kind, args, owner)
	if not kinds[kind] or not owner_ok(owner) or type(args) ~= "table" then return nil, "Invalid job request" end
	if kind == "support" and args.full ~= nil and type(args.full) ~= "boolean" then return nil, "Invalid diagnostics mode" end
	if kind == "bank_operation" then
		if not bank_actions[args.action] then return nil, "Invalid bank action" end
		if args.action == "verify" or args.action == "trial" then
			if args.bank ~= "A" and args.bank ~= "B" then return nil, "Select bank A or B" end
		elseif args.bank ~= nil then return nil, "This action uses the current bank state" end
	end
	local lock, err = lock_store()
	if not lock then return nil, err end
	local dir
	local function abort(message)
		if dir then fs.remover(dir) end
		lock:close()
		return nil, message
	end
	local count, bytes, firmware_busy, support_busy, pending_bytes = inventory()
	if count >= MAX_JOBS then return abort("Job history is full; completed jobs expire after two hours") end
	if (kind == "support" and support_busy) or (kind ~= "support" and firmware_busy) then
		return abort("A job of this type is already active; wait for its result")
	end
	local reserve = kind == "support" and MAX_ARCHIVE or (kind == "bank_operation" and 65536 or args.size)
	if type(reserve) ~= "number" or reserve < 1024 or reserve > MAX_ARCHIVE then return abort("Invalid job size") end
	if bytes + reserve + 65536 > MAX_BYTES or not enough_space(reserve * 3 + pending_bytes) then return abort("Insufficient temporary memory for this job") end
	local id = token()
	if not id then return abort("Cannot generate a private job identifier") end
	dir = ROOT .. "/" .. id
	if not fs.mkdir(dir, 700) then dir = nil; return abort("Cannot create job directory") end
	local request_args
	if kind == "support" then request_args = {full=args.full == true}
	elseif kind == "bank_operation" then request_args = {action=args.action, bank=args.bank}
	else
		request_args, err = copy_upload(args, owner, dir .. "/firmware.tar")
		if not request_args then return abort(err) end
	end
	local now = os.time()
	local request = {schema=1, id=id, owner=owner, kind=kind, args=request_args}
	local record = {id=id, kind=kind, state="queued", created=now, updated=now, output="", download_ready=false}
	if not atomic(dir .. "/request.json", request) or not atomic(dir .. "/status.json", record) then
		return abort("Cannot commit job request")
	end
	lock:close()
	local ok, uncertain
	ok, err, uncertain = launch(id)
	if not ok then
		-- An ambiguous wait result must never remove input beneath a worker.
		if uncertain then return M.get(id, owner) end
		record.state, record.error, record.updated = "failed", err, os.time()
		atomic(dir .. "/status.json", record)
		fs.unlink(dir .. "/firmware.tar")
		return nil, err
	end
	return M.get(id, owner)
end

function M.cancel(id, owner)
	local record, request, dir = load_job(id, owner)
	if not record then return nil, request end
	if request.kind ~= "support" then return nil, "Firmware jobs cannot be cancelled while flash operations may be running" end
	if terminal[record.state] then return public(record, dir) end
	if not private(dir .. "/cancel", "reg", 600) and not atomic(dir .. "/cancel", {cancel=true}) then
		return nil, "Cannot request cancellation"
	end
	return public(record, dir)
end

function M.download(id, owner)
	local record, request, dir = load_job(id, owner)
	if not record then return nil, request end
	local path = dir .. "/support.tar.gz"
	local st = private(path, "reg", 600)
	if request.kind ~= "support" or record.state ~= "succeeded" or not record.download_ready
		or not st or st.size == 0 or st.size > MAX_ARCHIVE or st.size ~= record.download_size
		or digest(path) ~= record.download_sha256 then return nil, "No verified diagnostics archive is available" end
	return path
end

-- Worker entry point is called only by the fixed launcher after detachment.
function M.worker(id)
	if not ident(id) or not directory(ROOT) then return 1 end
	local dir = ROOT .. "/" .. id
	if not directory(dir) then return 1 end
	local request = read_json(dir .. "/request.json")
	local record = read_json(dir .. "/status.json")
	if not request or request.id ~= id or not kinds[request.kind] or not owner_ok(request.owner)
		or not record or record.id ~= id or record.state ~= "queued" or record.kind ~= request.kind then return 1 end
	local guard = nixio.open(dir .. "/worker.lock", nixio.open_flags("rdwr", "creat", "excl"), 600)
	if not guard then return 1 end
	record.state, record.pid = "running", nixio.getpid()
	record.pid_start, record.updated = proc_identity(record.pid), os.time()
	if not record.pid_start or not atomic(dir .. "/status.json", record) then guard:close(); return 1 end
	local argv, outpath = {}, dir .. "/support.tar.gz"
	local rc, output
	if request.kind == "support" then
		argv = {"/usr/sbin/8311-support.sh", "--output", outpath, "--cancel-file", dir .. "/cancel"}
		if request.args.full then argv[#argv+1] = "--full" end
	elseif request.kind == "bank_operation" and bank_actions[request.args.action] then
		argv = {"/usr/sbin/8311-bankctl.sh", bank_actions[request.args.action]}
		if request.args.action == "verify" or request.args.action == "trial" then
			if request.args.bank ~= "A" and request.args.bank ~= "B" then rc, output = 1, "Invalid private bank request"
			else argv[#argv+1] = request.args.bank end
		elseif request.args.bank ~= nil then rc, output = 1, "Invalid private bank request" end
	elseif private(dir .. "/firmware.tar", "reg", 400)
		and private(dir .. "/firmware.tar", "reg", 400).size == request.args.size
		and digest(dir .. "/firmware.tar") == request.args.sha256 then
		if request.kind == "firmware_validate" then
			argv = {"/usr/sbin/8311-firmware-upgrade.sh", "--validate", dir .. "/firmware.tar"}
		else
			argv = {"/usr/sbin/8311-firmware-upgrade.sh", "--yes", "--install", "--trial", dir .. "/firmware.tar"}
		end
	else rc, output = 1, "Private firmware input failed verification" end
	local function update(tail)
		record.output = tail
		if os.time() > record.updated then record.updated = os.time(); atomic(dir .. "/status.json", record) end
	end
	if request.kind == "support" and private(dir .. "/cancel", "reg", 600) then rc, output = 130, "Diagnostics cancelled" end
	if not rc then rc, output = run(argv, update) end
	record.output, record.exitcode, record.updated = output, rc, os.time()
	if request.kind == "support" and private(dir .. "/cancel", "reg", 600) then
		fs.unlink(outpath)
		record.state, record.exitcode = "cancelled", 130
	elseif request.kind == "support" and (rc == 0 or rc == 2) then
		local st = private(outpath, "reg", 600)
		local hash = st and st.size > 0 and st.size <= MAX_ARCHIVE and digest(outpath)
		if hash then
			record.state, record.partial, record.download_ready = "succeeded", rc == 2, true
			record.download_size, record.download_sha256 = st.size, hash
		else
			record.state, record.error = "failed", "Collector did not produce a verified archive"
			fs.unlink(outpath)
		end
	else
		record.state = rc == 0 and "succeeded" or "failed"
		if rc ~= 0 then record.error = "Command failed; review its output and current device state" end
	end
	fs.unlink(dir .. "/firmware.tar")
	local saved = atomic(dir .. "/status.json", record)
	guard:close()
	return saved and 0 or 1
end

return M

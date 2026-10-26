local fs = require "nixio.fs"
local web = require "8311.webutil"
local M = { limit=16384 }
local path = "/ptconf/8311/vlan_fixes_hook.sh"

function M.read()
	local stat = fs.lstat(path)
	if stat and (stat.type ~= "reg" or stat.size > M.limit) then
		return nil, "Hook is not a regular file within the 16 KiB editor limit"
	end
	local content = stat and fs.readfile(path) or ""
	if type(content) ~= "string" then return nil, "Unable to read hook" end
	local revision, why = web.digest_text(content)
	if not revision then return nil, why end
	return {content=content,revision=revision,exists=stat ~= nil,previous_available=fs.lstat(path .. ".previous") ~= nil}
end

-- Caller holds /tmp/8311-fix-vlans.lock, the same flock as the hook runner.
function M.save(form)
	if type(form) ~= "table" or type(form.content) ~= "string" or type(form.revision) ~= "string" then
		return {success=false,error="Missing or duplicate hook fields",http_status=400}
	end
	for name, value in pairs(form) do
		if (name ~= "content" and name ~= "revision" and name ~= "token") or type(value) ~= "string" then
			return {success=false,error="Invalid hook request",http_status=400}
		end
	end
	if #form.content > M.limit or form.content:find("%z") then
		return {success=false,error="Hook exceeds 16 KiB or contains NUL bytes",http_status=413}
	end
	local current, err = M.read()
	if not current then return {success=false,error=err,http_status=503} end
	if form.revision ~= current.revision then return {success=false,error="Hook changed since it was opened. Reload before saving.",http_status=409} end
	local dir, why = web.private_dir("/ptconf/8311/.hook-save-")
	if not dir then return {success=false,error=why,http_status=507} end
	local new = dir .. "/hook"
	local previous = dir .. "/previous"
	local function fail(message, code)
		fs.unlink(new); fs.unlink(previous); fs.rmdir(dir)
		return {success=false,error=message,http_status=code or 507}
	end
	if form.content ~= "" then
		local ok, error = web.write(new, form.content, 755)
		if not ok then return fail(error) end
		local code, output = web.capture({"/bin/sh", "-n", new}, 2048)
		if code ~= 0 then return fail("Shell syntax check failed: " .. (output or "unknown error"), 422) end
	end
	if current.exists then
		local ok, error = web.write(previous, current.content, 600)
		if not ok then return fail("Unable to keep previous hook: " .. error) end
		if not fs.rename(previous, path .. ".previous") then return fail("Unable to save previous hook") end
	end
	if form.content == "" then
		if current.exists and not fs.unlink(path) then return fail("Unable to delete hook") end
	elseif not fs.rename(new, path) then return fail("Unable to atomically replace hook") end
	fs.rmdir(dir)
	local final, error = M.read()
	if not final or final.content ~= form.content then return {success=false,error=error or "Hook readback mismatch",http_status=502} end
	return {success=true,revision=final.revision,previous_available=final.previous_available,http_status=200}
end

return M

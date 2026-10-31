-- Server-owned schema validation, revision checks and checked persistence.
local tools = require "8311.tools"
local web = require "8311.webutil"
local fs = require "nixio.fs"
local base64 = require "base64"
local json = require "luci.jsonc"
local M = {}
local secret = { gpon_sn=true, reg_id_hex=true, loid=true, lpwd=true, root_pwhash=true }
local boot_path = "/tmp/8311-config-at-boot.json"

local function flat(schema)
	local all = {}
	for _, cat in ipairs(schema) do
		for _, item in ipairs(cat.items) do all[#all+1] = item end
	end
	return all
end

local function key(item) return (item.base and "" or "8311_") .. item.id end
local function canonical(items, values)
	local parts = {}
	for _, item in ipairs(items) do
		local value = values[key(item)] or ""
		parts[#parts+1] = item.id .. ":" .. #value .. ":" .. value .. ":" .. tostring(item.default or "")
	end
	return table.concat(parts, "\n")
end

local function decoded(item, value)
	if item.base64 and value ~= "" then
		local ok, result = pcall(base64.dec, value)
		-- The stock decoder discards junk and incomplete final bytes. Refuse a
		-- corrupt stored value instead of presenting it as an editable empty one.
		if not ok or type(result) ~= "string" or base64.enc(result) ~= value then return nil end
		return result
	end
	return value
end

local function effective(item, value)
	if item.type == "checkbox" or item.type == "checkbox_onoff" then
		return (value == "1" or value == "on" or (value == "" and item.default)) and "1" or "0"
	end
	if value == "" and item.default ~= nil then return tostring(item.default) end
	return value
end

local function display(item, value)
	if secret[item.id] and value ~= "" then return "[hidden]" end
	if value == "" then return "(default / unset)" end
	return value
end

-- Keep the saved gateway intact. Historical builds can rely on a
-- self-address default route for remote management; it must not disappear
-- when an administrator saves an unrelated setting.

function M.snapshot(schema)
	local values, err = tools.fwenv_read_all()
	if not values then return nil, err end
	local items = flat(schema)
	-- An unset gateway is no route. Do not let the GUI fill it with the
	-- device's own IP, including when another management IP is pending.
	for _, item in ipairs(items) do
		if item.id == "gateway" then item.default = "" end
	end
	local revision, why = web.digest_text(canonical(items, values))
	if not revision then return nil, why end
	local boot = web.read_json(boot_path, 131072)
	if boot then
		if boot.schema ~= 1 or type(boot.values) ~= "table" then boot = nil else
			for name, value in pairs(boot.values) do
				if type(name) ~= "string" or type(value) ~= "string" then boot = nil; break end
			end
		end
	end
	local pending = {}
	for _, item in ipairs(items) do
		item.raw = values[key(item)] or ""
		item.value = decoded(item, item.raw)
		if item.value == nil then return nil, "Stored setting cannot be decoded: " .. item.id end
		item.secret = secret[item.id] or false
		item.stored_invalid, item.stored_error = false, nil
		if item.value ~= "" then
			if item.type == "checkbox" then
				item.stored_invalid = item.value ~= "0" and item.value ~= "1"
			elseif item.type == "checkbox_onoff" then
				item.stored_invalid = item.value ~= "off" and item.value ~= "on"
			elseif item.type == "select" or item.type == "select_named" then
				item.stored_invalid = true
				for _, option in ipairs(item.options or {}) do
					if (type(option) == "table" and option.value or option) == item.value then item.stored_invalid = false end
				end
			end
		end
		if item.stored_invalid then item.stored_error = "Unsupported saved value; choose a supported value explicitly before saving" end
		if boot and type(boot.values) == "table" then
			local at_boot = decoded(item, boot.values[key(item)] or "")
			if at_boot == nil then
				boot, pending = nil, {}
			elseif at_boot ~= item.value then
				pending[#pending+1] = {id=item.id, name=item.name, running=display(item, at_boot), saved=display(item, item.value)}
			end
		end
	end
	return {schema=schema, items=items, values=values, revision=revision,
		boot_known=boot ~= nil, pending=pending}
end

local function ipv4(value)
	local numbers = {}; local a,b,c,d = value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
	if not a then return nil end
	for _, s in ipairs({a,b,c,d}) do
		if #s > 3 or tonumber(s) > 255 or (#s > 1 and s:sub(1,1) == "0") then return nil end
		numbers[#numbers+1] = tonumber(s)
	end
	return numbers[1]*16777216 + numbers[2]*65536 + numbers[3]*256 + numbers[4]
end

local function host(value)
	if #value > 253 or value:find("[^A-Za-z0-9.-]") then return false end
	for label in (value .. "."):gmatch("(.-)%.") do
		if #label < 1 or #label > 63 or label:sub(1,1) == "-" or label:sub(-1) == "-" then return false end
	end
	return true
end

-- Formats verified through the stock nixio.crypt binding. Restrict salt and
-- digest alphabets so no shadow-field separator or sed replacement syntax can
-- reach the startup consumer. The rounds ceiling is a deliberate GUI bound.
local function root_hash(value)
	local algorithm, body = value:match("^%$([156])%$(.+)$")
	if not algorithm then return false end
	if body:sub(1,7) == "rounds=" then
		if algorithm == "1" then return false end
		local rounds, rest = body:match("^rounds=([1-9]%d*)%$(.+)$")
		if not rounds or #rounds > 7 or tonumber(rounds) < 1000 or tonumber(rounds) > 1000000 then return false end
		body = rest
	end
	local salt, digest = body:match("^([A-Za-z0-9./]*)%$([A-Za-z0-9./]+)$")
	if not salt or #salt > (algorithm == "1" and 8 or 16) then return false end
	return #digest == ({['1']=22, ['5']=43, ['6']=86})[algorithm]
end
M.root_hash = root_hash

local patterns = {
	gpon_sn=function(v) return #v == 12 and v:sub(1,4):match("^[A-Za-z0-9]+$") and v:sub(5):match("^[A-F0-9]+$") end,
	vendor_id=function(v) return #v == 4 and v:match("^[A-Za-z0-9]+$") end,
	omcc_version=function(v) return v:match("^0x8[2-9A-F]$") or v:match("^0x[9AB][0-9A-F]$") end,
	reg_id_hex=function(v) return #v % 2 == 0 and v:match("^[A-Fa-f0-9]+$") end,
	iphost_mac=function(v) return v:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") end,
	lct_mac=function(v) return v:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") end,
	sfp_oui=function(v) return v:match("^[A-F0-9][A-F0-9]:[A-F0-9][A-F0-9]:[A-F0-9][A-F0-9]$") end,
	sfp_date=function(v) return #v >= 6 and #v <= 8 and v:sub(1,6):match("^%d%d%d%d%d%d$") end,
	root_pwhash=root_hash,
	ipaddr=ipv4, netmask=ipv4, gateway=ipv4, dns_server=ipv4, ping_ip=ipv4
}

function M.validate(item, value)
	if type(value) ~= "string" then return "Missing or duplicate field" end
	if #value > (tonumber(item.maxlength) or 255) then return "Value is too long" end
	if value:find("[%z\1-\31\127]") then return "Control characters are not allowed" end
	if value == "" then
		if item.required then return "This field is required" end
		if item.type == "checkbox" or item.type == "checkbox_onoff" then return "Choose enabled or disabled" end
		return nil
	end
	if item.type == "checkbox" or item.type == "checkbox_onoff" then
		if value ~= "0" and value ~= "1" then return "Choose enabled or disabled" end
	elseif item.type == "number" then
		if not value:match("^%d+$") or #value > 10 then return "Enter a whole number" end
		local number = tonumber(value)
		if (item.min and number < item.min) or (item.max and number > item.max) then return "Value is outside the allowed range" end
	elseif item.type == "select" or item.type == "select_named" then
		local allowed = false
		for _, option in ipairs(item.options or {}) do
			if (type(option) == "table" and option.value or option) == value then allowed = true end
		end
		if not allowed then return "Choose a supported value" end
	elseif item.type ~= "text" and item.type ~= "password" then
		return "Unsupported setting type"
	end
	if item.pattern and (not patterns[item.id] or not patterns[item.id](value)) then return "Value does not match the required format" end
	if item.id == "hostname" and not host(value) then return "Enter a valid hostname" end
	if (item.id == "hw_ver" or item.id == "equipment_id") and value:find('[\\"]') then
		return "Double quote and backslash are not supported in OMCI MIB string fields"
	end
	if item.id == "ntp_servers" then
		local count = 0
		for server in value:gmatch("%S+") do
			count = count + 1
			if not host(server) or count > 8 then return "Use up to eight hostnames or IPv4 addresses" end
		end
		if count == 0 then return "Enter a server or clear this field" end
	end
	if item.id == "ethtool_speed" then
		local parts = {}; for p in value:gmatch("%S+") do parts[#parts+1] = p end
		local allowed = {speed={['10']=true,['100']=true,['1000']=true,['2500']=true,['5000']=true,['10000']=true}, duplex={half=true,full=true}, autoneg={on=true,off=true}}
		local seen = {}
		if #parts % 2 ~= 0 then return "Use speed, duplex and autoneg name/value pairs" end
		for i=1,#parts,2 do
			local name, setting = parts[i], parts[i+1]
			if seen[name] or not allowed[name] or not allowed[name][setting] then return "Unsupported speed setting" end
			seen[name] = true
		end
	end
	if item.id == "fw_match_b64" then
		local code = web.capture({"/usr/bin/pcre2grep", "-e", value, "/dev/null"}, 1024)
		if code ~= 0 and code ~= 1 then return "Firmware match is not a valid PCRE pattern" end
	end
	return nil
end

function M.prepare(snapshot, form)
	local errors, known, changes, diff = {}, {token=true,complete=true,revision=true,mode=true}, {}, {}
	local proposed = {}
	if type(form) ~= "table" then return nil, {request="Invalid form"}, 400 end
	if form.complete ~= "8311-v1" then errors.request = "Incomplete form; reload the Configuration page" end
	if type(form.revision) ~= "string" or form.revision ~= snapshot.revision then
		return nil, {revision="Configuration changed since this page was loaded. Reload and review your changes again."}, 409
	end
	if form.mode ~= "preview" and form.mode ~= "apply" then errors.mode = "Invalid save mode" end
	for _, item in ipairs(snapshot.items) do
		known[item.id] = true
		local value = form[item.id]
		local error = M.validate(item, value)
		if error then errors[item.id] = error else
			-- Lua validates numbers as decimal, while some shell consumers parse a
			-- leading zero as octal. Preview and persist the same canonical value.
			if item.type == "number" and value ~= "" then value = string.format("%.0f", tonumber(value)) end
			proposed[item.id] = effective(item, value)
			if item.type == "checkbox" or item.type == "checkbox_onoff" then
				if item.value == "" and value == effective(item, "") then value = ""
				elseif item.type == "checkbox_onoff" then value = value == "1" and "on" or "off" end
			elseif item.id ~= "gateway" and item.value == "" and item.default ~= nil and value == tostring(item.default) then value = "" end
			-- Never rewrite the gateway unless it was actually edited.
			if value ~= item.value then
				changes[#changes+1] = {item=item, value=value, raw=item.base64 and value ~= "" and base64.enc(value) or value}
				diff[#diff+1] = {id=item.id,name=item.name,before=display(item,item.value),after=display(item,value),applies=item.id == "lang" and "Web interface after save" or "Next startup; live consumers may also re-read it"}
			end
		end
	end
	for name, value in pairs(form) do
		if not known[name] then errors.request = "Unknown form field" end
		if type(value) ~= "string" then errors[name] = "Duplicate or invalid field" end
	end
	local v = proposed
	-- Blank means no gateway for a fresh configuration. Saved legacy
	-- self-address routes remain visible and unchanged unless edited.
	if v.fix_vlans == "1" and v.internet_vlan ~= "" and v.services_vlan ~= "" and
	   tonumber(v.internet_vlan) and tonumber(v.internet_vlan) == tonumber(v.services_vlan) then
		errors.services_vlan = "Internet and Services VLANs must differ while automatic VLAN fixes are enabled"
	end
	if v.mib_file and v.mib_file ~= "" and v.pon_slot and v.pon_slot ~= "" then
		local code = web.capture({"/usr/libexec/8311-mib-edit.lua", "check-slot", v.mib_file, v.pon_slot}, 2048)
		if code ~= 0 then
			errors.pon_slot = "The selected MIB profile cannot safely apply this UNI slot; use a compatible MIB or leave its native slot mapping unchanged"
		end
	end
	if v.ipaddr and v.netmask then
		local ip, mask = ipv4(v.ipaddr), ipv4(v.netmask)
		if ip and mask then
			local span = 4294967296 - mask
			local power = 1; while power < span do power = power * 2 end
			if power ~= span or span < 4 or span > 16777216 then
				errors.netmask = "Use a contiguous /8 to /30 subnet mask"
			elseif ip % span == 0 or ip % span == span-1 then
				errors.ipaddr = "Use a host address, not the network or broadcast address"
			elseif v.gateway and v.gateway ~= "" then
				local gateway = ipv4(v.gateway)
				local original_ip = snapshot.values["8311_ipaddr"] or ""
				if original_ip == "" then original_ip = "192.168.11.1" end
				local original_gateway = snapshot.values["8311_gateway"] or ""
				local legacy_unchanged = original_gateway ~= ""
					and original_gateway == original_ip and v.gateway == original_gateway
				if not gateway then
					errors.gateway = "Enter a valid management gateway"
				elseif legacy_unchanged and v.ipaddr ~= original_ip then
					errors.gateway = "Changing the management IP requires explicitly replacing or clearing the legacy gateway; verify an alternative management path first"
				elseif gateway == ip and not legacy_unchanged then
					errors.gateway = "New self-address gateways are not supported; choose a reachable router or leave blank"
				elseif gateway ~= ip and (math.floor(ip/span) ~= math.floor(gateway/span) or gateway % span == 0 or gateway % span == span-1) then
					errors.gateway = "Gateway must be a valid host in the management subnet"
				end
			end
		end
	end
	if next(errors) then return nil, errors, 422 end
	return {changes=changes,diff=diff,revision=snapshot.revision}
end

-- The fixed shell entry point holds the shared environment lock before calling
-- this function. This is checked sequential persistence, not an atomic flash transaction.
function M.apply(snapshot, prepared)
	local result = {success=true,revision=snapshot.revision,diff=prepared.diff,verified={},errors={}}
	for _, change in ipairs(prepared.changes) do
		local item = change.item
		local setter = item.base and tools.fw_setenv or tools.fw_setenv_8311
		local ok = setter{item.id, change.raw}
		local readback = tools.fwenv_read_all()
		if not ok or not readback or (readback[key(item)] or "") ~= change.raw then
			result.success=false
			result.partial = #result.verified > 0 or (readback ~= nil and
				(readback[key(item)] or "") ~= (snapshot.values[key(item)] or ""))
			-- A setter can fail after its first redundant-environment write. A
			-- missing readback also cannot establish that nothing was changed.
			result.durability_unknown = true
			result.errors[item.id]="Persistence or readback failed; reload to see the durable state"
			break
		end
		result.verified[#result.verified+1]=item.id
	end
	if result.success then
		for _, change in ipairs(prepared.changes) do
			if change.item.id == "lang" then
				local code = web.capture({"/sbin/uci", "set", "luci.main.lang=" .. effective(change.item, change.value)}, 1024)
				if code == 0 then code = web.capture({"/sbin/uci", "commit", "luci"}, 1024) end
				if code ~= 0 then result.warning="Settings were saved; language activation failed and will be retried at startup" end
			end
		end
	end
	return result
end

function M.boot_snapshot()
	local values, why = tools.fwenv_read_all()
	if not values then return nil, why end
	local selected = {}
	for name, value in pairs(values) do
		if name:match("^8311_") or name == "bootdelay" or name == "uart_select" then selected[name] = value end
	end
	local ok, err = web.write(boot_path .. ".new", json.stringify({schema=1,values=selected}), 600)
	if not ok then return nil, err end
	if not fs.rename(boot_path .. ".new", boot_path) then fs.unlink(boot_path .. ".new"); return nil, "Cannot save startup snapshot" end
	return true
end

return M

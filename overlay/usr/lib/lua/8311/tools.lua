local require = require
local string = string
local setmetatable = setmetatable
local tonumber = tonumber
local tostring = tostring
local pairs = pairs
local type = type

module "8311.tools"

local util = require "luci.util"
local math = require "math"
local fs = require "nixio.fs"
local table = require "table"
local sys = require "luci.sys"

function html_escape(text)
	if text == nil then text = "" end
	text = tostring(text)

	return text:gsub("[&<>\"']", {
		["&"] = "&amp;",
		["<"] = "&lt;",
		[">"] = "&gt;",
		['"'] = "&quot;",
		["'"] = "&#039;"
	})
end

function nl2br(text)
	if text == nil then text = "" end
	return string.gsub(tostring(text), "\n", "<br />\n")
end

function fw_getenv(t)
	setmetatable(t, {__index={key=nil, default=nil, base64=false}})

	return fwenv_get(
		t[1] or t.key,
		t[2] or t.default,
		false,
		t[3] or t.base64
	)
end

function fw_getenv_8311(t)
	setmetatable(t, {__index={key=nil, default=nil, base64=false}})

	return fwenv_get(
		t[1] or t.key,
		t[2] or t.default,
		true,
		t[3] or t.base64
	)
end

function fwenv_get(key, default, _8311, base64)
	if not key then return false end

	local _8311_arg, base64_arg, default_arg = "", "", ""
	if _8311 then _8311_arg = "--8311 " end
	if base64 then base64_arg = "--base64 " end
	if default then default_arg = " " .. util.shellquote(default) end

	return string.gsub(util.exec("fwenv_get " .. _8311_arg .. base64_arg .. util.shellquote(key) .. default_arg), '[\r\n]+$', "")
end

function fw_getenvs_8311()
	local fwenvs = {}
	for k, v in string.gmatch(util.exec('echo ; fw_printenv | grep "^8311_"'), '\n8311_([^\n=]+)=([^\r\n]+)') do
		fwenvs[k] = v
	end

	return fwenvs
end

function fw_setenv(t)
	setmetatable(t, {__index={key=nil, value=nil, base64=false}})

	return fwenv_set(
		t[1] or t.key,
		t[2] or t.value,
		false,
		t[3] or t.base64
	)
end

function fw_setenv_8311(t)
	setmetatable(t, {__index={key=nil, value=nil, base64=false}})

	return fwenv_set(
		t[1] or t.key,
		t[2] or t.value,
		true,
		t[3] or t.base64
	)
end

function fwenv_set(key, value, _8311, base64)
	if type(key) ~= "string" or not key:match("^[A-Za-z0-9_]+$") or
	   (value ~= nil and type(value) ~= "string") then return false, "Invalid setting" end
	local cmd = { "/usr/sbin/fwenv_set" }
	if _8311 then table.insert(cmd, "--8311") end
	if base64 then table.insert(cmd, "--base64") end
	table.insert(cmd, key)
	table.insert(cmd, "--")
	table.insert(cmd, value or "")
	local result = sys.process.exec(cmd)
	if not result or result.code ~= 0 then return false, "Environment write or readback failed" end
	return true
end

-- One checked snapshot; missing keys are distinct from an unreadable environment.
function fwenv_read_all()
	local chunks, size, overflow = {}, 0, false
	local result = sys.process.exec({ "/usr/sbin/fw_printenv" }, function(chunk)
		chunk = chunk or ""
		size = size + #chunk
		if size <= 131072 then chunks[#chunks+1] = chunk else overflow = true end
	end)
	if not result or result.code ~= 0 or overflow then
		return nil, "Unable to read the complete boot environment"
	end
	local values = {}
	for line in (table.concat(chunks) .. "\n"):gmatch("([^\n]*)\n") do
		local key, value = line:match("^([A-Za-z0-9_]+)=(.*)$")
		if key then values[key] = value end
	end
	return values
end

function number_format(number, decimals)
	return string.format("%." .. decimals .."f", number)
end

function is_finite(value)
	return type(value) == "number" and value == value
		and value ~= math.huge and value ~= -math.huge
end

-- Keep missing readings in the JSON schema without inventing zero values.
function metric_names()
	return {
		"cpu1_tempC", "cpu2_tempC", "module_voltage", "optic_tempC",
		"ploam_state", "rx_power_dBm", "tx_bias_mA", "tx_power_dBm",
	}
end

local function sensor_temperature(path)
	-- nixio may return data, errno, message; pass only data to tonumber.
	local raw = fs.readfile(path)
	local value = tonumber(raw)
	if is_finite(value) then return value / 1000 end
end

local function optical_dbm(word)
	-- Zero optical power has no finite dBm representation.
	if word > 0 then return 10 * math.log10(word / 10000) end
end

function metrics()
	local ploam_status = string.match(" " .. (util.exec("pon psg") or "") .. " ", "%scurrent=(%d+)%s")
	local values = {
		ploam_state = tonumber(ploam_status),
		cpu1_tempC = sensor_temperature("/sys/class/thermal/thermal_zone0/temp"),
		cpu2_tempC = sensor_temperature("/sys/class/thermal/thermal_zone1/temp"),
	}

	local eep51 = fs.readfile("/sys/class/pon_mbox/pon_mbox0/device/eeprom51", 256)
	-- A transient mailbox read failure must not take down the status page.
	if type(eep51) == "string" and #eep51 >= 106 then
		local function word(offset)
			return eep51:byte(offset) * 256 + eep51:byte(offset + 1)
		end
		-- SFF-8472 temperature is a signed, big-endian fixed-point value.
		local optic_temp = word(97)
		if optic_temp >= 32768 then optic_temp = optic_temp - 65536 end
		values.optic_tempC = optic_temp / 256
		values.module_voltage = word(99) / 10000
		values.tx_bias_mA = word(101) / 500
		values.tx_power_dBm = optical_dbm(word(103))
		values.rx_power_dBm = optical_dbm(word(105))
	end

	return values
end

function sorted_keys(t)
	local tkeys = {}
	-- populate the table that holds the keys
	for k in pairs(t) do table.insert(tkeys, k) end
	-- sort the keys
	table.sort(tkeys)

	return tkeys
end

function iterator2array(...)
	local arr = {}
	for v in ... do
		table.insert(arr, v)
	end
	return arr
end

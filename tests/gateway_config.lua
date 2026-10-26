-- Offline Lua 5.1 regression tests for 8311 management gateway semantics.
-- No device, firmware, network, UCI or boot-environment operations are run.

local saved, boot_snapshot = {}, nil
package.preload["8311.tools"] = function()
    return {fwenv_read_all=function() return saved end}
end
package.preload["8311.webutil"] = function()
    return {
        digest_text=function() return "fixture-revision" end,
        read_json=function() return boot_snapshot end,
        capture=function() return 0 end
    }
end
package.preload["nixio.fs"] = function() return {} end
package.preload["base64"] = function()
    return {enc=function(v) return v end,dec=function(v) return v end}
end
package.preload["luci.jsonc"] = function() return {} end

local path = assert(arg[1], "Provide source config.lua path")
local module = assert(loadfile(path))()

local function schema()
    return {{items={
        {id="ipaddr", type="text", maxlength=15, pattern="ipv4", default="192.0.2.10"},
        {id="netmask", type="text", maxlength=15, pattern="ipv4", default="255.255.255.0"},
        {id="gateway", type="text", maxlength=15, pattern="ipv4", default=""}
    }}}
end

local function scenario(override)
    saved={
        ["8311_ipaddr"]=override.saved_ip or "192.0.2.10",
        ["8311_netmask"]=override.saved_mask or "255.255.255.0",
        ["8311_gateway"]=override.saved_gateway or ""
    }
    boot_snapshot=override.boot
    local snap, err = module.snapshot(schema())
    assert(snap, tostring(err))
    local values = {}
    for _,item in ipairs(snap.items) do values[item.id]=item end
    assert(values.gateway.default == "", "Gateway default must always be empty")
    local form = {
        complete="8311-v1", revision=snap.revision, mode="preview",
        ipaddr=override.ip or saved["8311_ipaddr"],
        netmask=override.mask or saved["8311_netmask"],
        gateway=override.gateway or values.gateway.value
    }
    local plan, errors, code = module.prepare(snap, form)
    return snap, values, plan, errors, code
end

-- Blank gateway stays blank and never becomes the ONU's IP.
local snap,vals,plan,errors = scenario({})
assert(plan and not next(errors or {}), "Unset gateway rejected")
assert(vals.gateway.value == "", "Default gateway unexpectedly populated")
for _,item in ipairs(plan.changes) do
    assert(item.item.id ~= "gateway", "Unexpected gateway write")
end

-- Historical "gateway == local IP" is a no-route sentinel, not a next hop.
snap,vals,plan,errors = scenario({saved_gateway="192.0.2.10"})
assert(vals.gateway.value == "", "Legacy self-address gateway was not normalized")
assert(plan and not next(errors or {}), "Legacy gateway no-route value rejected")

-- Legacy boot-snapshot and current self gateway should not look like an
-- unapplied modification to the subscriber's network.
snap,vals,plan,errors = scenario({
    saved_gateway="192.0.2.10",
    boot={schema=1,values={
        ["8311_ipaddr"]="192.0.2.10",
        ["8311_netmask"]="255.255.255.0",
        ["8311_gateway"]="192.0.2.10"
    }}
})
assert(#snap.pending==0, "Normalized legacy gateway creates false pending change")

-- Clearing a saved legacy self-gateway when the management IP changes
-- prevents the old local IP being treated as an off-subnet next hop.
snap,vals,plan,errors = scenario({
    saved_gateway="192.0.2.10",
    ip="198.51.100.10",
    gateway=""
})
assert(plan and not next(errors or {}), "Management IP change without gateway rejected")
local cleared = false
for _,change in ipairs(plan.changes) do
    if change.item.id == "gateway" then
        assert(change.raw == "", "Legacy gateway was not cleared")
        cleared = true
    end
end
assert(cleared, "Management IP change failed to remove old self-gateway")
local migration_visible = false
for _,change in ipairs(plan.diff) do
    if change.id == "gateway" and change.before == "(legacy self-gateway sentinel)" then
        migration_visible = true
    end
end
assert(migration_visible, "Gateway migration was hidden in the change preview")

-- Valid gateway remains valid and is not deleted.
snap,vals,plan,errors = scenario({gateway="192.0.2.1"})
assert(plan and not next(errors or {}), "Valid subnet next hop rejected")
assert(#plan.changes==1 and plan.changes[1].item.id=="gateway","Gateway update missing")

-- An explicit self-address is prohibited.
snap,vals,plan,errors = scenario({gateway="192.0.2.10"})
assert(not plan and errors.gateway, "New self-address route unexpectedly accepted")

-- Crossing subnets without an on-link router is rejected.
snap,vals,plan,errors = scenario({gateway="198.51.100.10"})
assert(not plan and errors.gateway, "Off-subnet gateway unexpectedly accepted")

-- Validate subnet even if the gateway is disabled.
snap,vals,plan,errors = scenario({mask="255.255.0" .. ".255",gateway=""})
assert(not plan and errors.netmask, "Noncontiguous mask bypassed via blank gateway")

-- Reject network and broadcast addresses without requiring a gateway.
snap,vals,plan,errors = scenario({ip="192.0.2." .. "0",gateway=""})
assert(not plan and errors.ipaddr,"Network address bypassed via blank gateway")
snap,vals,plan,errors = scenario({ip="192.0.2." .. "255",gateway=""})
assert(not plan and errors.ipaddr,"Broadcast address bypassed via blank gateway")

print("Gateway Lua 5.1: all 10 regression scenarios passed")

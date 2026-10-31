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

-- Historical self-address gateways are persisted on some qualified
-- deployments. Do not silently normalize or delete a saved gateway.
snap,vals,plan,errors = scenario({saved_gateway="192.0.2.10"})
assert(vals.gateway.value == "192.0.2.10",
       "Saved management gateway was not preserved and displayed")
assert(plan and not next(errors or {}), "Saved self-address gateway was rejected")
for _,change in ipairs(plan.changes) do
    assert(change.item.id ~= "gateway", "Unrelated save silently changed gateway")
end

-- A matching boot snapshot must not cause false pending modifications.
snap,vals,plan,errors = scenario({
    saved_gateway="192.0.2.10",
    boot={schema=1,values={
        ["8311_ipaddr"]="192.0.2.10",
        ["8311_netmask"]="255.255.255.0",
        ["8311_gateway"]="192.0.2.10"
    }}
})
assert(#snap.pending==0, "Preserved legacy gateway creates false pending change")

-- A user may explicitly clear a saved gateway during a management
-- address change. The deliberate edit must appear in the diff.
snap,vals,plan,errors = scenario({
    saved_gateway="192.0.2.10",
    ip="198.51.100.10",
    gateway=""
})
assert(plan and not next(errors or {}), "Explicit gateway clearance rejected")
local cleared = false
for _,change in ipairs(plan.changes) do
    if change.item.id == "gateway" then
        assert(change.raw == "", "Gateway clearance was not recorded")
        cleared = true
    end
end
assert(cleared, "Explicit gateway clearance missing from change plan")
local migration_visible = false
for _,change in ipairs(plan.diff) do
    if change.id == "gateway" and change.before == "192.0.2.10" then
        migration_visible = true
    end
end
assert(migration_visible, "Explicit gateway edit hidden from preview")

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

-- AoTT-8311 v3 runtime capability summary.
-- Reports installed versus activated/qualified state. No writes or services.
local fs = require "nixio.fs"
local M = {}
local function exists(path)
    local st = fs.stat(path)
    return st and st.type == "reg"
end
local function feature(id,label,state,detail)
    return {id=id,label=label,state=state,detail=detail}
end
function M.snapshot()
    local history_core =
        exists("/usr/lib/lua/8311/history_model.lua") and
        exists("/usr/lib/lua/8311/history_sampler.lua") and
        exists("/usr/lib/lua/8311/history_export.lua")
    local history_runtime =
        history_core and
        exists("/usr/lib/lua/8311/history_live_snapshot.lua") and
        exists("/usr/lib/lua/8311/history_config.lua") and
        exists("/usr/libexec/8311-history-worker.lua") and
        exists("/usr/libexec/8311-history-wrapper") and
        exists("/etc/init.d/8311-history")
    local tls_key = exists("/usr/libexec/8311-root-hash-valid")
    local config_readback =
        exists("/usr/lib/lua/8311/effective_probe.lua") and
        exists("/usr/lib/lua/8311/effective_vlan_probe.lua")
    local bank_guard = exists("/usr/sbin/8311-bankctl.sh")
    return {
        schema=1, product="AoTT-8311", release="v3", revision="r1",
        baseline="v2r9 hardware-qualified RC",
        residential_profile=true, remote_management_default=false,
        features={
            feature("configuration","Configuration readback/control",
                config_readback and "integrated" or "unavailable",
                "54-field readback baseline retained; live setters remain qualification-gated."),
            feature("recovery","A/B firmware recovery",
                bank_guard and "qualified" or "unavailable",
                "Guarded A/B lifecycle retained from the hardware-qualified r9 baseline."),
            feature("history","Local history engine",
                history_runtime and "integrated_opt_in_unqualified" or
                    (history_core and "integrated_inactive" or "unavailable"),
                "Opt-in RAM-only sampling, bounded exports and authenticated local history are integrated. Disabled by default; persistent history and final hardware resource qualification remain gated."),
            feature("tls","TLS/key health",
                tls_key and "integrated" or "unavailable",
                "Existing key-health checks retained; certificate generation/import activation remains gated."),
            feature("remote_gui","Remote management firewall","disabled",
                "Remote GUI remains off by default; future enablement requires explicit firewall policy and recovery checks.")
        }
    }
end
return M

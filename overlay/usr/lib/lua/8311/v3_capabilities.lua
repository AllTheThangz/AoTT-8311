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
    local management_preview =
        exists("/usr/lib/lua/8311/management_preflight.lua") and
        exists("/usr/lib/lua/8311/native_management_reader.lua") and
        exists("/usr/lib/lua/8311/recovery_storage.lua") and
        exists("/usr/lib/lua/8311/vlan_transition.lua")
    local management_transaction =
        management_preview and
        exists("/usr/lib/lua/8311/management_transaction.lua") and
        exists("/usr/lib/lua/8311/management_runtime.lua") and
        exists("/usr/lib/lua/8311/management_recovery_store.lua") and
        exists("/usr/libexec/8311-management-apply")
    local tls_candidate =
        exists("/usr/lib/lua/8311/tls_candidate.lua") and
        exists("/usr/lib/lua/8311/tls_key_hardener.lua") and
        exists("/usr/libexec/8311-tls-key-permissions") and
        exists("/etc/init.d/8311-tls-key-permissions")
    local tls_activation =
        tls_candidate and
        exists("/usr/lib/lua/8311/tls_activation.lua") and
        exists("/usr/libexec/8311-tls-activate.lua") and
        exists("/usr/libexec/8311-tls-recover-pending")
    local tls_import =
        tls_activation and exists("/usr/lib/lua/8311/tls_import.lua")
    local remote_firewall =
        exists("/usr/lib/lua/8311/remote_firewall.lua") and
        exists("/usr/lib/lua/8311/access_transaction.lua") and
        exists("/usr/lib/lua/8311/access_recovery_store.lua") and
        exists("/usr/libexec/8311-access-apply")
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
                config_readback and "integrated_source_complete_unqualified" or "unavailable",
                "55 Configuration-page controls are explicitly routed through live, management, PON/OMCI, boot or credential transactions. MIB prompts are profile-driven; hardware qualification remains per control."),
            feature("recovery","A/B firmware recovery",
                bank_guard and "qualified" or "unavailable",
                "Guarded A/B lifecycle retained from the hardware-qualified r9 baseline."),
            feature("management_vlan","Management VLAN transaction",
                management_transaction and "guarded_transaction_integrated_unqualified" or
                    (management_preview and "preview_integrated" or "unavailable"),
                "Full management tuple preview/apply, persistent rollback, exact runtime convergence, reconnect confirmation and boot recovery are integrated. Live hardware mutation remains unqualified."),
            feature("history","Local history engine",
                history_runtime and "integrated_opt_in_unqualified" or
                    (history_core and "integrated_inactive" or "unavailable"),
                "Opt-in RAM-only sampling, bounded exports and authenticated local history are integrated. Disabled by default; persistent history and final hardware resource qualification remain gated."),
            feature("tls","TLS certificates and key protection",
                (tls_key and tls_import) and "generated_and_imported_guarded_activation_integrated_unqualified" or
                    ((tls_key and tls_activation) and "guarded_self_signed_activation_integrated" or
                    ((tls_key and tls_candidate) and "candidate_generation_integrated_activation_gated" or "unavailable")),
                "Persistent HTTPS keys are root-only. Generated or operator-owned PEM/DER candidates use the same inactive slot, native uhttpd pair check, persistent backup, 180-second browser confirmation and automatic rollback. Browser trust remains a hardware/runtime confirmation."),
            feature("remote_gui","Remote management firewall",
                remote_firewall and "integrated_opt_in_unqualified" or "unavailable",
                "Remote HTTPS remains disabled by default. Explicit /24-or-narrower IPv4 allowlists generate fixed WAN input rules inside the guarded Access transaction; live packet-path exposure remains hardware-unqualified.")
        }
    }
end
return M

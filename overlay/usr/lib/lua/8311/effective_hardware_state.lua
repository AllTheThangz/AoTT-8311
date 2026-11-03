-- AoTT-8311 C-011: read-only advanced system/host evidence model.
-- Portable Lua 5.1, pure data. No shell or UCI calls, GPIO writes,
-- login hashes, PON identifiers, boot selector changes or reboot.
local M={}
local IDS={
    "bootdelay","uart_select","console_en","dying_gasp_en",
    "rx_los","ethtool_speed","failsafe_delay","persist_root",
}
local BASE={bootdelay=true,uart_select=true}

local function clean(v,limit)
    if type(v)~="string" or #v>(limit or 100) or
       v:find("[%z\1-\31\127]") then return nil end
    return v
end

local function unsigned(v,low,high)
    if not clean(v,9) or not v:match("^%d+$") or
       (#v>1 and v:sub(1,1)=="0") then return nil end
    local n=tonumber(v)
    if not n or n<low or n>high then return nil end
    return tostring(n)
end

local function bit(v)
    if v=="0" or v=="1" then return v end
end

local function uart(v)
    if v=="on" or v=="off" then return v end
end

local function speed_options(v)
    if not clean(v,100) then return nil end
    if v=="" then return "" end
    if not v:match("^[A-Za-z0-9_ %-]+$") or
       v:find("%s%s") or v:sub(1,1)==" " or v:sub(-1)==" " then
        return nil
    end
    -- Read-only evidence of a validated option string, not permission
    -- to pass arbitrary arguments to an ethtool setter.
    local items={}
    for word in v:gmatch("%S+") do
        if #items>=16 then return nil end
        items[#items+1]=word
    end
    return table.concat(items," ")
end

local NORMAL={
    bootdelay=function(v)return unsigned(v,0,3) end,
    uart_select=uart,
    console_en=bit,dying_gasp_en=bit,rx_los=bit,
    ethtool_speed=speed_options,
    failsafe_delay=function(v)return unsigned(v,0,300) end,
    persist_root=bit,
}

local function compare(a,b)
    if a==nil or b==nil or a=="" or b=="" then return "unverified" end
    return a==b and "match" or "mismatch"
end

local function pin(value,direction)
    if value~="0" and value~="1" then return nil end
    if direction~="out" then return nil end
    return value
end

local function speed(v)
    return unsigned(v,10,100000)
end

function M.inspect(saved,config,runtime)
    if type(saved)~="table" or type(config)~="table" or
       type(runtime)~="table" then
        return nil,"invalid_hardware_readback_input"
    end
    local fields={}
    for _,id in ipairs(IDS) do
        local norm=NORMAL[id]
        local raw=saved[id]
        local saved_value=(raw~=nil and norm(raw) or nil)
        local item={
            id=id,
            key_scope=BASE[id] and "base_boot_environment" or
                                    "aott_prefixed_environment",
            saved_value=saved_value,
            configured_value=nil,
            observed_effective_value=nil,
            configured_source="unavailable",
            observed_source="unavailable",
            saved_to_configured="unverified",
            saved_to_observed="unverified",
            runtime_effect_proven=false,
            reboot_persistence_proven=false,
            recovery_proven=false,
            hardware_qualified=false,
            source_only_not_hardware_qualified=true,
            sensitivity="noncredential",
            notes={},
        }
        if raw~=nil and saved_value==nil then
            item.notes[#item.notes+1]="saved_value_invalid_or_not_supported"
        end
        fields[id]=item
    end

    -- A UCI dying-gasp disable flag is the inverse of the saved
    -- enabled bit. It is configuration, NOT proof of a PON/host alarm.
    local dg=config.optic_dg_dis
    if dg=="0" or dg=="1" then
        local item=fields.dying_gasp_en
        item.configured_value=dg=="0" and "1" or "0"
        item.configured_source="uci_optic_common_dg_dis_inverse"
        item.saved_to_configured=compare(item.saved_value,item.configured_value)
        item.notes[#item.notes+1]="optic_configuration_not_power_loss_signalling_proof"
    end

    -- GPIO readback observes an output electrical level, but neither
    -- confirms serial console data nor validates a dying-gasp message.
    local gpio=runtime.gpio or {}
    local gpio510=type(gpio)=="table" and gpio["510"] or nil
    local gpio508=type(gpio)=="table" and gpio["508"] or nil
    local gpio505=type(gpio)=="table" and gpio["505"] or nil
    local uart_level=gpio510 and pin(gpio510.value,gpio510.direction)
    local dying_level=gpio508 and pin(gpio508.value,gpio508.direction)
    local los_level=gpio505 and pin(gpio505.value,gpio505.direction)
    local pininfo={
        tx_fault_shared_uart_output=uart_level,
        rx_shared_dying_gasp_output=dying_level,
        rx_los_output=los_level,
        pins_read_only=true,
        gpio_levels_prove_serial_or_optic_signalling=false,
    }
    if uart_level then
        local item=fields.console_en
        item.observed_source="kernel_gpio510_output_only"
        item.observed_effective_value=uart_level
        item.saved_to_observed=compare(item.saved_value,uart_level)
        item.notes[#item.notes+1]="gpio_output_does_not_prove_console_function"
    end
    if dying_level then
        local item=fields.dying_gasp_en
        -- Low GPIO RX corresponds to enabled dying-gasp.
        local inferred=dying_level=="0" and "1" or "0"
        item.observed_source="kernel_gpio508_output_only"
        item.observed_effective_value=inferred
        item.saved_to_observed=compare(item.saved_value,inferred)
        item.notes[#item.notes+1]="gpio_level_not_proof_of_optical_alarm"
    end
    if los_level then
        fields.rx_los.notes[#fields.rx_los.notes+1]=
            "gpio505_alarm_level_not_proof_of_feature_enabled"
    end

    -- Host link speed is an independent measured link quantity. It
    -- does NOT validate every ethtool argument or prove the override
    -- caused the negotiated speed.
    local link=speed(runtime.link_speed_mbps)
    local eth={
        device="eth0_0",
        negotiated_speed_mbps=link,
        independent_source=link and "kernel_sysfs_speed" or "unavailable",
        proves_speed_override_applied=false,
        proves_subscriber_internet=false,
    }
    if link then
        fields.ethtool_speed.notes[#fields.ethtool_speed.notes+1]=
            "negotiated_speed_is_not_override_effect_proof"
    end

    -- Optional procd presence is not proof of active RX_LOS pin
    -- configuration or alarm propagation.
    local rx_daemon=runtime.rx_los_daemon
    if type(rx_daemon)~="boolean" then rx_daemon=nil end
    local diagnostics={
        gpio=pininfo,
        ethernet=eth,
        rx_los_daemon_present=rx_daemon,
        rx_los_daemon_proves_alarm=false,
        bootdelay_observed_during_running_session=false,
        early_uart_observed_after_boot=false,
        failsafe_startup_timing_verified=false,
        persistent_root_recovery_verified=false,
    }

    for _,id in ipairs(IDS) do
        local item=fields[id]
        item.notes[#item.notes+1]=
            "readback_does_not_qualify_change_persistence_or_recovery"
    end
    return {
        schema=1,
        group="advanced_system_and_host",
        source="read_only_noncredential_hardware_settings",
        no_device_write=true,
        no_reboot=true,
        no_firmware_commit=true,
        source_only_not_hardware_qualified=true,
        contains_credential_material=false,
        fields=fields,
        diagnostics=diagnostics,
        summary={
            source_fields=8,
            fully_effective_verified=0,
            hardware_qualified=0,
        },
    }
end

M.fields=IDS
M.base_environment=BASE
return M

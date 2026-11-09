module("luci.controller.8311", package.seeall)

local tools = require "8311.tools"
local util = require "luci.util"
local ltemplate = require "luci.template"
local http = require "luci.http"
local formvalue = http.formvalue
local dispatcher = require "luci.dispatcher"
local sys = require "luci.sys"
local i18n = require "luci.i18n"
local translate = i18n.translate
local base64 = require "base64"
local ltn12 = require "luci.ltn12"
local fs = require "nixio.fs"
local bit = require "nixio.bit"
local uci = require "luci.model.uci"
local json = require "luci.jsonc"
local web = require "8311.webutil"
local health = require "8311.health"
local monitoring = require "8311.monitoring"
local history_config = require "8311.history_config"
local history_snapshot = require "8311.history_live_snapshot"
local management_preflight = require "8311.management_preflight"
local tls_candidate = require "8311.tls_candidate"
local tls_activation = require "8311.tls_activation"
local tls_import = require "8311.tls_import"
local effective_probe = require "8311.effective_probe"
local effective_device_probe = require "8311.effective_device_probe"
local effective_pon_probe = require "8311.effective_pon_probe"
local effective_vlan_probe = require "8311.effective_vlan_probe"
local effective_hardware_probe = require "8311.effective_hardware_probe"
local effective_reporting_probe = require "8311.effective_reporting_probe"
local config = require "8311.config"
local mib_profile = require "8311.mib_profile"
local uploads = require "8311.uploads"
local jobs = require "8311.jobs"

function index()
	entry({"admin", "8311"}, firstchild(), translate("AoTT-8311"), 99).dependent=false
	entry({"admin", "8311", "config"}, call("action_config"), translate("Configuration"), 1)
	entry({"admin", "8311", "pon_status"}, call("action_pon_status"), translate("PON Status"), 2)
	entry({"admin", "8311", "pon_explorer"}, call("action_pon_explorer"), translate("PON ME Explorer"), 3)
	entry({"admin", "8311", "vlans"}, call("action_vlans"), translate("VLAN Tables"), 4)
	entry({"admin", "8311", "support"}, call("action_support"), translate("Support"), 5)

	entry({"admin", "8311", "save"}, post("action_save"))
	entry({"admin", "8311", "mib_profile"}, post("action_mib_profile")).leaf=true
	entry({"admin", "8311", "boot_config_apply"}, post("action_boot_config_apply")).leaf=true
	entry({"admin", "8311", "boot_config_status"}, call("action_boot_config_status")).leaf=true
	entry({"admin", "8311", "boot_config_confirm"}, post("action_boot_config_confirm")).leaf=true
	entry({"admin", "8311", "pon_config_apply"}, post("action_pon_config_apply")).leaf=true
	entry({"admin", "8311", "pon_config_status"}, call("action_pon_config_status")).leaf=true
	entry({"admin", "8311", "pon_config_confirm"}, post("action_pon_config_confirm")).leaf=true
	entry({"admin", "8311", "get_hook_script"}, call("action_get_hook_script")).leaf=true
	entry({"admin", "8311", "save_hook_script"}, post("action_save_hook_script")).leaf=true
	entry({"admin", "8311", "pontop"}, call("action_pontop")).leaf=true
	entry({"admin", "8311", "pon_dump"}, call("action_pon_dump")).leaf=true
	entry({"admin", "8311", "gpon_status"}, call("action_gpon_status")).leaf = true
	entry({"admin", "8311", "vlans", "extvlans"}, call("action_vlan_extvlans"))
	entry({"admin", "8311", "support", "support.tar.gz"}, call("action_support_download"))

	entry({"admin", "8311", "firmware"}, call("action_firmware"), translate("Firmware"), 6);
	-- This route checks a header token before raising the streaming body limit.
	entry({"admin", "8311", "firmware_upload"}, call("action_firmware_upload"))
	entry({"admin", "8311", "job_status"}, call("action_job_status"))
	entry({"admin", "8311", "job_cancel"}, post("action_job_cancel"))
    entry({"admin", "8311", "health"}, call("action_r5_health"), translate("Live health"), 7)
    entry({"admin", "8311", "health_data"}, call("action_r5_health_data")).leaf=true
    -- C-011 authenticated-only readback, never an anonymous collector
    entry({"admin", "8311", "effective_management"},
          call("action_effective_management")).leaf=true
    entry({"admin", "8311", "effective_device"},
          call("action_effective_device")).leaf=true
    entry({"admin", "8311", "effective_pon"},
          call("action_effective_pon")).leaf=true
    entry({"admin", "8311", "effective_vlan"},
          call("action_effective_vlan")).leaf=true
    entry({"admin", "8311", "effective_hardware"},
          call("action_effective_hardware")).leaf=true
    entry({"admin", "8311", "effective_reporting"},
          call("action_effective_reporting")).leaf=true
    entry({"admin", "8311", "effective_identity"},
          call("action_effective_identity")).leaf=true
    entry({"admin", "8311", "security"}, call("action_r5_security"), translate("Security & access"), 8)
    entry({"admin", "8311", "security_data"}, call("action_r5_security_data")).leaf=true
	entry({"admin", "8311", "bank_status"}, call("action_bank_status"))
	-- The inherited unauthenticated metrics route is intentionally removed.
    -- Admin operations inherit LuCI authentication. A separate public-path
    -- collector route performs its own TLS, IP and bearer checks.
    entry({"admin", "8311", "monitoring"}, call("action_r8_monitoring"),
          translate("Monitoring & telemetry"), 9)
    entry({"admin", "8311", "history"}, call("action_history"), translate("Local history"), 10)
    entry({"admin", "8311", "history_save"}, post("action_history_save")).leaf=true
    entry({"admin", "8311", "history_data"}, call("action_history_data")).leaf=true
    entry({"admin", "8311", "management_preflight"}, call("action_management_preflight"),
          translate("Management preflight"), 11)
    entry({"admin", "8311", "management_vlan_preview"},
          post("action_management_vlan_preview")).leaf=true
    entry({"admin", "8311", "management_preview"},
          post("action_management_preview")).leaf=true
    entry({"admin", "8311", "management_apply"},
          post("action_management_apply")).leaf=true
    entry({"admin", "8311", "management_confirm"},
          post("action_management_confirm")).leaf=true
    entry({"admin", "8311", "tls"}, call("action_tls"), translate("HTTPS certificates"), 12)
    entry({"admin", "8311", "tls_generate"}, post("action_tls_generate")).leaf=true
    entry({"admin", "8311", "tls_import"}, call("action_tls_import")).leaf=true
    entry({"admin", "8311", "tls_discard"}, post("action_tls_discard")).leaf=true
    entry({"admin", "8311", "tls_activate"}, post("action_tls_activate")).leaf=true
    entry({"admin", "8311", "tls_confirm"}, post("action_tls_confirm")).leaf=true
    entry({"admin", "8311", "v3"}, call("action_v3"), translate("V3 status"), 13)
    entry({"admin", "8311", "v3_status"}, call("action_v3_status")).leaf=true
    entry({"admin", "8311", "access"}, call("action_access"), translate("Access & servers"), 14)
    entry({"admin", "8311", "access_preview"}, post("action_access_preview")).leaf=true
    entry({"admin", "8311", "access_apply"}, post("action_access_apply")).leaf=true
    entry({"admin", "8311", "access_confirm"}, post("action_access_confirm")).leaf=true
    entry({"admin", "8311", "access_status"}, call("action_access_status")).leaf=true
    entry({"admin", "8311", "factory_password_ack"}, post("action_factory_password_ack")).leaf=true
    entry({"admin", "8311", "monitoring_save"},
          post("action_r8_monitoring_save")).leaf=true
    entry({"admin", "8311", "monitoring_test"},
          post("action_r8_monitoring_test")).leaf=true
    entry({"admin", "8311", "monitoring_credential"},
          post("action_r8_monitoring_credential")).leaf=true
    entry({"admin", "8311", "metrics"}, call("action_metrics")).leaf=true
    entry({"8311", "metrics"}, call("action_collector_metrics")).leaf=true
end

function pontop_page_details()
	return {{
			id="status",
			page="Status",
			label=translate("Status")
		},{
			id="cap",
			page="Capability and Configuration",
			label=translate("Capability")
		},{
			id="lan",
			page="LAN Interface Status & Counters",
			label=translate("LAN Info"),
			display=false
		},{
			id="alarms",
			page="Active alarms",
			label=translate("Alarms")
		},{
			id="gem",
			page="GEM/XGEM Port Status",
			label=translate("GEM Status")
		},{
			id="gem_stats",
			page="GEM/XGEM Port Counters",
			label=translate("GEM Stats")
		},{
			id="gem_ds",
			page="GEM/XGEM port DS Counters",
			label=translate("GEM DS"),
			display=false
		},{
			id="gem_us",
			page="GEM/XGEM port US Counters",
			label=translate("GEM US"),
			display=false
		},{
			id="eth_ds",
			page="GEM/XGEM port Eth DS Cnts",
			label=translate("ETH DS Stats"),
		},{
			id="eth_us",
			page="GEM/XGEM port Eth US Cnts",
			label=translate("ETH US Stats")
		},{
			id="fec",
			page="FEC Status & Counters",
			label=translate("FEC Info")
		},{
			id="gtc",
			page="GTC/XGTC Status & Counters",
			label=translate("GTC Info")
		},{
			id="power_save",
			page="Power Save Status",
			label=translate("PS Status")
		},{
			id="psm",
			page="PSM Configuration",
			label=translate("PSM")
		},{
			id="alloc_stats",
			page="Allocation Counters",
			label=translate("Alloc Stats")
		},{
			id="ploam_ds",
			page="PLOAM Downstream Counters",
			label=translate("PLOAM DS")
		},{
			id="ploam_us",
			page="PLOAM Upstream Counters",
			label=translate("PLOAM US")
		},{
			id="optical",
			page="Optical Interface Status",
			label=translate("Optical Status")
		},{
			id="optical_info",
			page="Optical Interface Info",
			label=translate("Optical Info")
		},{
			id="debug_burst",
			page="Debug Burst Profile",
			label=translate("Burst Profile")
		},{
			id="cqm",
			page="CQM ofsc",
			label=translate("CQM")
		},{
			id="cqm_map",
			page="CQM Queue Map",
			label=translate("CQM Q Map")
		},{
			id="datapath_ports",
			page="Datapath Ports",
			label=translate("DP Ports")
		},{
			id="datapath_qos",
			page="Datapath QOS",
			label=translate("DP QoS")
		},{
			id="pp4_buffers",
			page="PPv4 Buffer MGR HW Stats",
			label=translate("PPv4 Buffers")
		},{
			id="pp4_pps",
			page="PPv4 QoS Queue PPS",
			label=translate("PPv4 PPS")
		},{
			id="pp4_stats",
			page="PPv4 QoS Queues Stats",
			label=translate("PPv4 Stats")
		},{
			id="pp4_tree",
			page="PPv4 QoS Tree",
			label=translate("PPv4 Tree")
		},{
			id="pp4_qstats",
			page="PPv4 QoS QStats",
			label=translate("PPv4 QStats")
		}
	}
end


function pontop_pages()
	local details = pontop_page_details()
	local pages = {}
	for _, page in pairs(details) do
		pages[page.id] = page.page
	end

	return pages
end

local function mib_profile_options()
    local out={}
    for path in fs.glob("/etc/mibs/*.ini") do
        if type(path)=="string" then
            local filename=path:match("([^/]+)$") or path
            local label=filename
            local profile=mib_profile.inspect(path)
            if type(profile)=="table" and type(profile.topology)=="table" then
                local kind=tostring(profile.profile_kind or "profile"):gsub("_"," ")
                local tcont=tonumber(profile.topology.tcont_me262_count) or 0
                local unis=tonumber(profile.topology.physical_uni_count) or 0
                label=filename.." — "..kind..", "..tostring(tcont).." T-CONT"
                if unis>0 then label=label..", "..tostring(unis).." physical UNI" end
                if tonumber(profile.topology.iphost_me134_count or 0)==0 then
                    label=label..", no IP Host ME"
                end
            end
            out[#out+1]={name=label,value=path}
        end
    end
    table.sort(out,function(a,b)return a.value<b.value end)
    return out
end

function language_change(value)
	util.exec("uci set luci.main.lang=" .. util.shellquote(value) .. " && uci commit luci")
end

function fwenvs_8311()
	local zones = util.trim(util.exec("grep -v '^#' /usr/share/zoneinfo/zone.tab  | awk '{print $3}' | sort -uV ; echo UTC"))
	local timezones = {}
	for zone in zones:gmatch("[^\r\n]+") do
		table.insert(timezones, zone)
	end

	local languages = {{
		name="auto",
		value="auto"
	}}
	local langs = util.trim(util.exec("uci show luci.languages | pcre2grep -o1 '^luci\.languages\.([^=]+)='"))
	for lang in langs:gmatch("[^\r\n]+") do
		table.insert(languages, {
			name=util.trim(util.exec("uci get luci.languages." .. util.shellquote(lang))),
			value=lang
		})
	end

	local ipv4_regex = "^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$"

	return {{
			id="pon",
			category=translate("PON & OLT identity"),
			items={	{
					id="gpon_sn",
					name=translate("PON serial number (ONT ID)"),
					description=translate("Identifier presented to the optical line terminal (OLT). The ISP-provisioned value must match: four letters/digits followed by eight hex characters. Changing it can prevent PON registration."),
					maxlength=12,
					pattern='^[A-Za-z0-9]{4}[A-F0-9]{8}$',
					type="text",
					required=true
				},{
					id="vendor_id",
					name=translate("PON vendor ID"),
					description=translate("Four-character vendor code advertised to the OLT. If blank, it is derived from the PON serial number. Changing it may affect ISP provisioning."),
					maxlength=4,
					pattern='^[A-Za-z0-9]{4}$',
					type="text"
				},{
					id="equipment_id",
					name=translate("ONT equipment model ID"),
					description=translate("Up to 20 characters advertised in OMCI ONU2-G Managed Entity 257. This is a reported model identifier, not a hardware modification."),
					maxlength=20,
					type="text"
				},{
					id="hw_ver",
					name=translate("Reported hardware version"),
					description=translate("Up to 14 characters presented to the OLT as the reported hardware version. Does not update physical hardware."),
					maxlength=14,
					type="text"
				},{
					id="cp_hw_ver_sync",
					name=translate("Sync circuit-pack hardware version"),
					description=translate("When enabled, align Circuit Pack MIB Managed Entity 6 version fields with the reported hardware version. The MIB editor rejects unsupported profile edits."),
					type="checkbox",
					default=false
				},{
					id="sw_verA",
					name=translate("Reported software image A version"),
					description=translate("Up to 14 characters advertised for firmware bank A in OMCI Software Image Managed Entity 7. This does NOT flash, boot or commit bank A."),
					maxlength=14,
					type="text",
					default=tools.fw_getenv{"img_versionA"}
				},{
					id="sw_verB",
					name=translate("Reported software image B version"),
					description=translate("Up to 14 characters advertised for firmware bank B in OMCI Software Image Managed Entity 7. This does NOT flash, boot or commit bank B."),
					maxlength=14,
					type="text",
					default=tools.fw_getenv{"img_versionB"}
				},{
					id="fw_match_b64",
					name=translate("Software version matching pattern"),
					description=translate("Advanced PCRE expression used to extract a version when processing firmware uploads from the OLT. Must contain exactly one capture group; leave unchanged unless required by the ISP."),
					type="text",
					maxlength="255",
					base64=true
				},{
					id="fw_match_num",
					name=translate("Version match occurrence"),
					description=translate("Select which occurrence of the version-matching expression to use if several are found. Default: 1."),
					type="number",
					min=1,
					max=99,
					default="1"
				},{
					id="override_active",
					name=translate("Reported active bank override (OMCI)"),
					description=translate("Overrides the bank reported as active in OMCI Software Image Managed Entity 7 only. Does NOT change the bootloader active bank; use Firmware to manage actual bank selection."),
					type="select",
					default="",
					options={
						"",
						"A",
						"B"
					}
				},{
					id="override_commit",
					name=translate("Reported committed bank override (OMCI)"),
					description=translate("Overrides the bank reported as committed in OMCI Software Image Managed Entity 7 only. Does NOT commit actual firmware; use Firmware for actual bank selection."),
					type="select",
					default="",
					options={
						"",
						"A",
						"B"
					}
				},{
					id="pon_mode",
					name=translate("Optical access technology"),
					description=translate("Optical access protocol presented to the network. XGS-PON is the known-working mode for this stick; changing it can disconnect service."),
					type="select_named",
					default="xgspon",
					options={
						{
							name="XGS-PON",
							value="xgspon"
						},{
							name="XG-PON",
							value="xgpon"
						}
					}
				},{
					id="omcc_version",
					name=translate("OMCI channel version"),
					description=translate("Advanced OLT management channel version, hexadecimal 0x82 to 0xBF. Default: 0xA3. Change only to match documented ISP requirements."),
					type="text",
					default="0xA3",
					maxlength=4,
					pattern='^0x(8[2-9A-F]|[9AB][0-9A-F])$'
				},{
					id="iop_mask",
					name=translate("OMCI interoperability mask (advanced)"),
					description =
						translate("Advanced: compatibility flags (sum of bit values). ISP-specific; leave unchanged unless required. The options are:") .. "\n" ..
						translate("1 - Force Unauthorized IGMP/MLD behavior") .. "\n" ..
						translate("2 - Skip Alloc-IDs termination upon T-CONT deactivation") .. "\n" ..
						translate("4 - Drop all packets on default Downstream Extended VLAN rules") .. "\n" ..
						translate("8 - Ignore Downstream Extended VLAN rules priority matching") .. "\n" ..
						translate("16 - Convert Traffic Descriptor PIR/CIR values from kbyte/s to kbit/s") .. "\n" ..
						translate("32 - Force common IP handling - apply the IPv4 Ethertype 0x0800 to the Extended VLAN rule matching for IPv6 packets") .. "\n" ..
						translate("64 - It is unknown what this option does but it appears to affect the message length in omci_msg_send."),
					type="number",
					default="18",
					min=0,
					max=127
				},{
					id="reg_id_hex",
					name=translate("PON registration ID / PLOAM credential (hex)"),
					description=translate("Up to 36 bytes of authentication data, represented as hex pairs (72 characters maximum). The PLOAM password occupies the last 12 bytes where required. Treat this as a secret."),
					maxlength=72,
					pattern='^([A-Fa-f0-9]{2})*$',
					type="text",
                    ["secret"] = true
				},{
					id="loid",
					name=translate("Logical ONU identifier (LOID)"),
					description=translate("Optional Logical ONU ID advertised in OMCI ONU-G Managed Entity 256 (up to 24 characters), if required by the provider."),
					maxlength=24,
					type="text"
				},{
					id="lpwd",
					name=translate("Logical ONU password"),
					description=translate("Optional LOID authentication password in OMCI ONU-G Managed Entity 256 (up to 12 characters). Treat this value as a secret."),
					maxlength=12,
					type="text",
                    ["secret"] = true
				},{
					id="mib_file",
					name=translate("OMCI device profile (MIB)"),
					description=translate("OMCI Managed Information Base profile loaded by omcid. The current prx300_1U.ini profile is verified on this deployment. Other profiles may change UNI and service behavior."),
					type="select_named",
					default="/etc/mibs/prx300_1U.ini",
					options=mib_profile_options()
				},{
					id="pon_slot",
					name=translate("Reported ONU UNI slot number"),
					description=translate("UNI port slot number advertised through the MIB (1–254; default 1). Intended for provider-specific profiles. Unsupported or ambiguous profiles cannot be safely edited."),
					type="number",
					min=1,
					max=254
				},{
					id="iphost_mac",
					name=translate("Reported IP-host MAC address"),
					description=translate("MAC address reported in OMCI IP Host Config Data Managed Entity 134, formatted XX:XX:XX:XX:XX:XX. This is not the host-facing physical Ethernet MAC."),
					maxlength=17,
					pattern='^[A-Fa-f0-9]{2}(:[A-Fa-f0-9]{2}){5}$',
					type="text",
					default=util.trim(util.exec(". /lib/pon.sh && pon_mac_get host")):upper()
				},{
					id="iphost_hostname",
					name=translate("Reported IP-host hostname"),
					description=translate("Hostname reported to the OLT in OMCI IP Host Config Data Managed Entity 134 (up to 25 characters)."),
					maxlength=25,
					type="text"
				},{
					id="iphost_domain",
					name=translate("Reported IP-host domain"),
					description=translate("Domain name reported in OMCI IP Host Config Data Managed Entity 134 (up to 25 characters)."),
					maxlength=25,
					type="text"
				}
			}
		},{
			id="isp",
			category=translate("VLAN & ISP services"),
			items={	{
					id="fix_vlans",
					name=translate("OLT VLAN translation mode"),
					description=translate("Controls automatic translation of OLT-provisioned traffic VLANs to local service mappings. Enabled uses the built-in mapping; Hook script only delegates to the privileged custom hook. Changing this can interrupt Internet/services."),
					type="select_named",
					default="1",
					options={
						{
							name=translate("Disabled"),
							value="0"
						},
						{
							name=translate("Enabled"),
							value="1"
						},
						{
							name=translate("Hook script only"),
							value="2"
						}
					}
				},{
					id="internet_vlan",
					name=translate("Local Internet VLAN ID"),
					description=translate("Local Internet VLAN: 0 means untagged and removes VLAN 0; 1–4095 uses that VLAN ID. Default: 0. Keep the existing mapping unless the service profile requires a change."),
					type="number",
					min=0,
					max=4095,
					default="0"
				},{
					id="services_vlan",
					name=translate("Local services VLAN ID"),
					description=translate("Optional local services VLAN (1–4095). Leave blank to detect from the OLT when supported. The services VLAN is distinct from the Internet VLAN."),
					type="number",
					min=1,
					max=4095,
				}
			}
		},{
			id="device",
			category=translate("System & startup"),
			items={ {
					id="lang",
					name=translate("Web interface language"),
					description=translate("Select the language for web-interface labels. Changing this does not change optical registration."),
					type="select_named",
					default="auto",
					options=languages,
					change=language_change
				},{
					id="bootdelay",
					name=translate("Bootloader pause (seconds)"),
					description=translate("U-Boot pause before booting (seconds). A zero-second delay may prevent interactive recovery and disable multicast upgrade. Default: 3; a shorter delay may boot faster."),
					type="select_named",
					default="3",
					base=true,
					options={
						{
							name=translate("0 (Fastest, disables multicast upgrade, not recommended)"),
							value="0"
						},{
							name=translate("1 (Fast Boot)"),
							value="1"
						},{
							name="2",
							value="2"
						},{
							name=translate("3 (Default)"),
							value="3"
						}
					}
				},{
					id="console_en",
					name=translate("Serial console (shared TX_FAULT pin)"),
					description=translate("Enable serial console output. On this SFP platform, the serial interface shares the TX_FAULT pin; changing it may affect host alarm signalling."),
					type="checkbox",
					default=false
				},{
					id="uart_select",
					name=translate("Early UART console"),
					description=translate("Configure early UART output during boot. Shares hardware signals with SFP functions; change only if serial recovery is required."),
					type="checkbox_onoff",
					base=true,
					default=true,
				},{
					id="dying_gasp_en",
					name=translate("Power-loss signal (dying gasp)"),
					description=translate("Transmit the dying-gasp power-loss signal. This function shares an SFP pin with serial console input and can interfere with console access."),
					type="checkbox",
					default=false
				},{
					id="rx_los",
					name=translate("Receive-loss (RX_LOS) pin reporting"),
					description=translate("Controls receive-loss-of-signal pin reporting. Turning it off may allow local management when fiber is disconnected on some host devices."),
					type="checkbox",
					default=false
				},{
					id="root_pwhash",
					name=translate("Root login password hash (advanced)"),
					description=translate("Optional root password override in supported crypt hash format ($1$, $5$ or $6$). Never enter plaintext here. For ordinary password changes, use Device & access → Root password."),
					maxlength=255,
					pattern="^\\$(1\\$[A-Za-z0-9.\\/]{0,8}\\$[A-Za-z0-9.\\/]{22}|5\\$(rounds=([1-9][0-9]{3,5}|1000000)\\$)?[A-Za-z0-9.\\/]{0,16}\\$[A-Za-z0-9.\\/]{43}|6\\$(rounds=([1-9][0-9]{3,5}|1000000)\\$)?[A-Za-z0-9.\\/]{0,16}\\$[A-Za-z0-9.\\/]{86})$",
					type="text",
                    ["secret"] = true
				},{
					id="ethtool_speed",
					name=translate("Ethernet link speed override (advanced)"),
					description=translate("Raw ethtool speed options for the host-facing eth0_0 interface. Incorrect settings can disable the 10G host link and interrupt Internet/management access."),
					maxlength=100,
					type="text"
				},{
					id="failsafe_delay",
					name=translate("OMCI startup delay (seconds)"),
					description=translate("Delay OMCI startup after boot by 0–300 seconds; default 15. A longer delay also postpones PON registration."),
					type="number",
					min=0,
					max=300,
					default="15"
				},{
					id="hostname",
					name=translate("Device hostname"),
					description=translate("Name displayed in the SSH shell, console and web interface. Does not change the ISP-provisioned PON serial number."),
					maxlength=100,
					type="text",
					default="prx126-sfp-pon"
				},{
					id="timezone",
					name=translate("Device time zone"),
					description=translate("Time zone used for local timestamps and logs. Does not affect optical registration."),
					type="select",
					default="UTC",
					options=timezones
				},{
					id="ntp_servers",
					name=translate("Time synchronization servers (NTP)"),
					description=translate("One or more time-sync server hostnames/IPs separated by spaces. Synchronizes local clocks and log timestamps."),
					maxlength=255,
					type="text"
				},{
					id="persist_root",
					name=translate("Persistent root filesystem (debug only)"),
					description=translate("Advanced debugging mode requiring coordinated boot-command changes. Not supported as a safe everyday setting; leave disabled."),
					type="checkbox",
					default=false
				}
			}
		},{
			id="sfp",
			category=translate("SFP EEPROM identity"),
			items={ {
					id="sfp_vendor",
					name=translate("Host-visible SFP vendor name"),
					description=translate("Up to 16 characters presented to the host router through the virtual SFP EEPROM, not a hardware-manufacturer change."),
					type="text",
					maxlength=16,
				},{
					id="sfp_oui",
					name=translate("Host-visible SFP vendor OUI"),
					description=translate("Three-byte vendor OUI reported to the host through the SFP EEPROM. Format: XX:XX:XX (uppercase hex)."),
					type="text",
					pattern="^[0-9A-F]{2}(:[0-9A-F]{2}){2}$",
					maxlength=8,
				},{
					id="sfp_partno",
					name=translate("Host-visible SFP part number"),
					description=translate("Up to 16 characters for the part number reported in the SFP EEPROM. This is not the actual OMCI equipment ID."),
					type="text",
					maxlength=16,
				},{
					id="sfp_rev",
					name=translate("Host-visible SFP hardware revision"),
					description=translate("Up to four characters for the SFP hardware revision reported to the host, not the installed firmware revision."),
					type="text",
					maxlength=4,
				},{
					id="sfp_serial",
					name=translate("Host-visible SFP serial number"),
					description=translate("Up to 16 characters for the host-visible SFP EEPROM serial number. Separate from the PON serial used for ISP authentication."),
					type="text",
					maxlength=16,
				},{
					id="sfp_date",
					name=translate("Host-visible SFP date code"),
					description=translate("Six-digit date (YYMMDD), with up to two optional trailing characters, reported in the SFP EEPROM."),
					type="text",
					pattern="^\\d{6}.{0,2}$",
					maxlength="8",
				},{
					id="sfp_vendordata",
					name=translate("SFP vendor-specific EEPROM data"),
					description=translate("Up to 32 characters of vendor-specific EEPROM data reported to the host device."),
					type="text",
					maxlength=32,
				}
			}
		},{
			id="manage",
			category=translate("Management network"),
			items={	{
					id="lct_vlan",
					name=translate("Management VLAN"),
					description=translate("Management interface VLAN. 0 is untagged; 1-4094 creates the guarded tagged management interface. Changes use timed confirmation with automatic rollback."),
					type="number",
					min=0,
					max=4094,
					default="0"
				},{
					id="ipaddr",
					name=translate("Management IPv4 address"),
					description=translate("Local IPv4 address for the ONU management interface. Changing it can end this web/SSH session; reconnect to the new address after a restart. Factory baseline: 192.168.11.1."),
					maxlength=15,
					pattern=ipv4_regex,
					type="text",
					default="192.168.11.1"
				},{
					id="netmask",
					name=translate("Management subnet mask"),
					description=translate("IPv4 subnet mask used with the management address, for example 255.255.255.0. Incorrect values can break management reachability."),
					maxlength=15,
					pattern=ipv4_regex,
					type="text",
					default="255.255.255.0"
				},{
					id="gateway",
					name=translate("Management default gateway"),
					description=translate("Optional management default gateway. Existing legacy self-address routes are kept for compatibility: do not clear one until another management path is verified. A blank new setting means no route. New self-address gateways are rejected. Changes apply on next startup and can disconnect remote management."),
					maxlength=15,
					pattern=ipv4_regex,
					type="text",
					default=""
				},{
					id="dns_server",
					name=translate("Management DNS resolver"),
					description=translate("Optional DNS resolver for the ONU management plane. Separate from the IP settings supplied to subscribers by the ISP."),
					maxlength=15,
					pattern=ipv4_regex,
					type="text"
				},{
					id="pingd",
					name=translate("Management keepalive ping"),
					description=translate("Periodically ping the configured management-side target to help keep management connectivity available on certain SFP hosts."),
					type="checkbox",
					default=true,
				},{
					id="ping_ip",
					name=translate("Keepalive destination IPv4 address"),
					description=translate("IPv4 target for management keepalive traffic, usually a reachable address on the management subnet. Do not point it at an unrelated public endpoint."),
					maxlength=15,
					pattern=ipv4_regex,
					type="text",
					default=util.trim(util.exec(". /lib/8311.sh && get_8311_default_ping_host"))
				},{
					id="lct_mac",
					name=translate("Local control terminal (LCT) MAC"),
					description=translate("MAC address of the ONU local control terminal management interface (LCT), formatted XX:XX:XX:XX:XX:XX."),
					maxlength=17,
					pattern='^[A-Fa-f0-9]{2}(:[A-Fa-f0-9]{2}){5}$',
					type="text",
					default=util.trim(util.exec(". /lib/pon.sh && pon_mac_get lct")):upper()
				},{
					id="reverse_arp",
					name=translate("Reverse ARP address learning"),
					description=translate("Learns management-side MAC/IP neighbor mappings from observed packets." ..
						" This can help in reaching the management interface without using NAT."),
					type="checkbox",
					default=true
				},{
					id="https_redirect",
					name=translate("Always redirect HTTP to HTTPS"),
					description=translate("Redirect browser HTTP connections to HTTPS. Recommended enabled; HTTPS certificate trust is managed separately."),
					type="checkbox",
					default=true
				}
			}
		}
	}
end

function action_pontop(page)
	local cmd

	page = page or "status"

	local pages = pontop_pages()

    if not pages[page] then
        http.status(404, "Unknown PON status page")
        return
    end
    cmd = { "/usr/bin/pontop", "-g", pages[page], "-b" }
    local code, output, overflow = web.capture(cmd, 262144)
    if code ~= 0 or overflow or not output or output == "" then
        http.status(502, "PON command failed")
        http.prepare_content("text/plain; charset=utf-8")
        http.write("The PON status command did not complete successfully. No data was substituted. Review system logs.")
        return
    end
    http.prepare_content("text/plain; charset=utf-8")
    http.write(output)
end

function action_pon_status()
	local pages = pontop_page_details()

	ltemplate.render("8311/pon_status", {
		pages=pages,
	})
end

function pon_state(state)
	state = tonumber(state)
	local states = {
		[0]		= "O0, Power-up state",
		[10]	= "O1, Initial state",
		[11]	= "O1.1, Off-sync state",
		[12]	= "O1.2, Profile learning state",
		[20]	= "O2, Stand-by state",
		[23]	= "O2.3, Serial number state",
		[30]	= "O3, Serial number state",
		[40]	= "O4, Ranging state",
		[50]	= "O5, Operation state",
		[51]	= "O5.1, Associated state",
		[52]	= "O5.2, Pending state",
		[60]	= "O6, Intermittent LOS state",
		[70]	= "O7, Emergency stop state",
		[71]	= "O7.1, Emergency stop off-sync state",
		[72]	= "O7.2, Emergency stop in-sync state",
		[81]	= "O8.1, Downstream tuning off-sync state",
		[82]	= "O8.2, Downstream tuning profile learning state",
		[90]	= "O9, Upstream tuning state",
	}

	return translate(states[state] or "N/A")
end

-- r5 endpoints are authenticated by the existing admin/8311 LuCI route tree.
-- Only read operations; no actions, config writes or secrets are accepted.
function action_r5_health()
    ltemplate.render("8311/health", {})
end

function action_r5_health_data()
    local ok, result = pcall(health.performance)
    if not ok or type(result) ~= "table" or result.schema ~= 1 then
        return web.reply(http, 503, {success=false,error="Telemetry is unavailable; no values were inferred."})
    end
    web.reply(http, 200, result)
end

function action_effective_management()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, snapshot = pcall(effective_probe.live_management)
    if not ok or type(snapshot) ~= "table" or snapshot.schema ~= 1 then
        return web.reply(http, 503,
            {success=false,error="Effective management readback unavailable; no settings changed"})
    end
    -- Never report a UCI-only read as a kernel-verified effect.
    return web.reply(http, 200, {success=true,data=snapshot})
end

function action_effective_device()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, snapshot = pcall(effective_device_probe.live_device, i18n.context.lang)
    if not ok or type(snapshot) ~= "table" or snapshot.schema ~= 1 then
        return web.reply(http, 503,
            {success=false,error="Device and SFP readback unavailable; no settings changed"})
    end
    return web.reply(http, 200, {success=true,data=snapshot})
end

function action_effective_pon()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, snapshot = pcall(effective_pon_probe.live_pon)
    if not ok or type(snapshot) ~= "table" or snapshot.schema ~= 1 or
       snapshot.contains_registration_secret ~= false then
        return web.reply(http, 503,
            {success=false,error="PON configuration readback unavailable; no settings changed"})
    end
    return web.reply(http, 200, {success=true,data=snapshot})
end

function action_effective_vlan()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, snapshot = pcall(effective_vlan_probe.live_vlan)
    if not ok or type(snapshot) ~= "table" or snapshot.schema ~= 1 or
       snapshot.contains_registration_secret ~= false then
        return web.reply(http, 503,
            {success=false,error="VLAN service readback unavailable; no settings changed"})
    end
    return web.reply(http, 200, {success=true,data=snapshot})
end

function action_effective_hardware()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, snapshot = pcall(effective_hardware_probe.live_hardware)
    if not ok or type(snapshot) ~= "table" or snapshot.schema ~= 1 or
       snapshot.contains_credential_material ~= false then
        return web.reply(http, 503,
            {success=false,error="Hardware settings readback unavailable; no settings changed"})
    end
    return web.reply(http, 200, {success=true,data=snapshot})
end

-- Authenticated manual GET only: no identity strings, credentials,
-- raw firmware version labels, boot environment or bank changes.
function action_effective_identity()
    http.header("Cache-Control", "no-store, private")
    http.header("Pragma", "no-cache")
    http.header("X-Content-Type-Options", "nosniff")
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http,405,{success=false,error="Read-only GET required"})
    end
    local ok,snapshot,reason=pcall(function()
        local probe=require "8311.effective_identity_probe"
        return probe.live_identity(dispatcher,util)
    end)
    if ok and reason=="forbidden" then
        return web.reply(http,403,{success=false,error="Administrator session required"})
    end
    if not ok or type(snapshot)~="table" or snapshot.schema~=1 or
       snapshot.no_identity_exported~=true or
       snapshot.no_credential_hash_exported~=true or
       snapshot.no_raw_environment_exported~=true or
       snapshot.source_only_not_hardware_qualified~=true then
        return web.reply(http,503,{success=false,
            error="Identity source readback unavailable; no settings changed"})
    end
    return web.reply(http,200,{success=true,data=snapshot})
end

function action_effective_reporting()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405,
            {success=false,error="Read-only GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok,snapshot=pcall(effective_reporting_probe.live_reporting)
    if not ok or type(snapshot)~="table" or snapshot.schema~=1 or
       snapshot.no_registration_secret_read~=true or
       snapshot.no_subscriber_identity_exported~=true or
       snapshot.no_raw_environment_value_exported~=true or
       snapshot.source_only_not_hardware_qualified~=true then
        return web.reply(http,503,
            {success=false,error="Reporting source readback unavailable; no settings changed"})
    end
    return web.reply(http,200,{success=true,data=snapshot})
end

function action_r5_security()
    ltemplate.render("8311/security", {})
end

function action_r5_security_data()
    local ok, result = pcall(health.security)
    if not ok or type(result) ~= "table" or result.schema ~= 1 then
        return web.reply(http, 503, {success=false,error="Security readback is unavailable; no settings changed."})
    end
    web.reply(http, 200, result)
end

function action_metrics()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    -- The authenticated admin metrics view remains available if enabled.
    if not monitoring.metrics_enabled() then
        return web.reply(http, 403, {success=false,
            error="Metrics export is disabled by the administrator"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    local ok, metrics = pcall(tools.metrics, true)
    if not ok or type(metrics) ~= "table" then
        return web.reply(http, 503, {success=false, error="Metrics unavailable"})
    end
	luci.http.prepare_content("application/json")
	luci.http.write("{\n")

	for i, metric in ipairs(tools.metric_names()) do
		if i > 1 then
			luci.http.write(",\n")
		end

		local value = metrics[metric]
		if tools.is_finite(value) then
			local dec = 2
			if metric == "ploam_state" then
				dec = 0
			end

			value = string.format("%." .. dec .. "f", value)
		else
			value = "null"
		end

		luci.http.write('  "' .. metric .. '": ' .. value)
	end
	luci.http.write("\n}\n")
end

-- A dedicated read-only collector route, not the inherited anonymous API.
-- It is disabled by default and fails closed on missing TLS, socket identity,
-- allowed IP or the independently rotated token.
function action_collector_metrics()
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    http.header("Referrer-Policy", "no-referrer")
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    if not monitoring.collector_authorized(http.getenv) then
        return web.reply(http, 403,
            {success=false,error="Read-only collector access denied"})
    end
    return action_metrics()
end

function temperature(t)
	if not tools.is_finite(t) then return translate("N/A") end
	return string.format(translate("%.2f °C (%.1f °F)"), t, (t * 1.8 + 32))
end

local function display_metric(value, format)
	if not tools.is_finite(value) then return translate("N/A") end
	return string.format(translate(format), value)
end

function action_gpon_status()
	local metrics = tools.metrics()

	local eep50 = fs.readfile("/sys/class/pon_mbox/pon_mbox0/device/eeprom50", 256)
	local function module_field(first, last)
		if not eep50 or #eep50 < last then return translate("N/A") end
		local value = eep50:sub(first, last):gsub("%z", ""):trim()
		return value ~= "" and value or translate("N/A")
	end

	local eth_speed = tonumber((fs.readfile("/sys/class/net/eth0_0/speed") or ""):trim())
	local vendor_name = module_field(21, 36)
	local vendor_pn = module_field(41, 56)
	local vendor_rev = module_field(57, 60)
	local pon_mode = uci:get("gpon", "ponip", "pon_mode") or "xgspon"
	local module_type = util.exec(". /lib/8311.sh && get_8311_module_type"):trim() or "bfw"
	local active_bank = util.exec(". /lib/8311.sh && active_fwbank"):trim() or "A"

	local rv = {
		status = pon_state(metrics.ploam_state),
		power = string.format("%s / %s / %s", display_metric(metrics.rx_power_dBm, "%.2f dBm"), display_metric(metrics.tx_power_dBm, "%.2f dBm"), display_metric(metrics.tx_bias_mA, "%.2f mA")),
		temperature = string.format("%s / %s / %s", temperature(metrics.cpu1_tempC), temperature(metrics.cpu2_tempC), temperature(metrics.optic_tempC)),
		voltage = display_metric(metrics.module_voltage, "%.2f V"),
		pon_mode = pon_mode:upper():gsub("PON$", "-PON"),
		module_info = string.format("%s %s %s (%s)", vendor_name, vendor_pn, vendor_rev, module_type),
		eth_speed = (eth_speed and eth_speed > 0 and string.format(translate("%s Mbps"), eth_speed) or translate("N/A")),
		active_bank = active_bank,
	}
	luci.http.prepare_content("application/json")
	luci.http.write_json(rv)
end

function action_vlans()
	ltemplate.render("8311/vlans", {})
end

function action_vlan_extvlans()
    local code, preflight, overflow = web.capture({"/usr/sbin/8311-extvlan-decode.sh","-t"},131072)
    if code ~= 0 or overflow then
        http.status(502, "VLAN inspection unavailable")
        http.prepare_content("text/plain; charset=utf-8")
        http.write("VLAN preflight failed; output is unavailable. Check ONU/PON readiness.")
        return
    end
    local data_code, data, data_overflow = web.capture({"/usr/sbin/8311-extvlan-decode.sh"},262144)
    if data_code ~= 0 or data_overflow or not data then
        http.status(502, "VLAN decoding failed")
        http.prepare_content("text/plain; charset=utf-8")
        http.write("VLAN decoder did not complete successfully; no partial output is shown.")
        return
    end
    http.prepare_content("text/plain; charset=utf-8")
    http.write((preflight or "") .. "\n\n" .. data)
end

function action_get_hook_script()
	local record, err = require("8311.hook").read()
	web.reply(http, record and 200 or 503, record or {success=false,error=err})
end

local function checked_worker(kind, values)
	local parse_error, parse_code = http.inputerror()
	if parse_error then return web.reply(http, parse_code, {success=false,error=parse_error}) end
	local content = json.stringify(values)
	if not content or #content > 100000 then return web.reply(http,413,{success=false,error="Request is too large"}) end
	local dir, why = web.private_dir("/tmp/8311-" .. kind .. "-")
	if not dir then return web.reply(http,507,{success=false,error=why}) end
	local path = dir .. "/request.json"
	local ok, err = web.write(path, content, 600)
	if not ok then fs.rmdir(dir); return web.reply(http,507,{success=false,error=err}) end
	local commands={config="/usr/libexec/8311-config-apply",hook="/usr/libexec/8311-hook-save",["boot-config"]="/usr/libexec/8311-boot-config-apply"}
	local command=commands[kind]
	if not command then fs.unlink(path);fs.rmdir(dir);return web.reply(http,400,{success=false,error="Unsupported checked operation"}) end
	local code, output, overflow = web.capture({command,path}, 65536)
	local cleaned = fs.unlink(path) and fs.rmdir(dir)
	local result = code == 0 and not overflow and json.parse(output or "") or nil
	if type(result) ~= "table" then return web.reply(http,503,{success=false,error="Operation failed or its lock is busy; reload before retrying"}) end
	if not cleaned then result.warning="Operation completed; temporary request cleanup failed" end
	local status = tonumber(result.http_status) or 502; result.http_status=nil
	web.reply(http,status,result)
end

function action_save_hook_script()
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	checked_worker("hook", http.formvalue())
end

function action_support_download()
	local id = http.formvalue("job_id")
	if type(id) ~= "string" or #id ~= 32 or not id:match("^[a-f0-9]+$") then return web.reply(http,400,{error="A diagnostic job ID is required"}) end
	local path, err = jobs.download(id, dispatcher.context.authsession)
	if not path then return web.reply(http,404,{error=err}) end
	local file = io.open(path, "rb")
	if not file then return web.reply(http,503,{error="Archive could not be opened; retry generation"}) end
	local stat = fs.lstat(path)
	if not stat or stat.type ~= "reg" then file:close(); return web.reply(http,503,{error="Archive is unavailable"}) end
	http.prepare_content("application/gzip")
	http.header("Content-Length", tostring(stat.size))
	http.header("Content-Disposition", 'attachment; filename="8311-support-' .. id .. '.tar.gz"')
	http.header("Cache-Control", "no-store")
	local ok, problem = ltn12.pump.all(ltn12.source.file(file), http.write)
	if not ok then error("Support download interrupted") end
end

function populate_8311_fwenvs()
	local fwenvs = fwenvs_8311()
	local fwenvs_values = tools.fw_getenvs_8311()

	for catid, cat in pairs(fwenvs) do
		for itemid, item in pairs(cat.items) do
			local value
			if item.base then
				value = tools.fw_getenv{item.id}
			else
				value = fwenvs_values[item.id] or ''
			end
			if item.base64 and value ~= '' then
				value = base64.dec(value)
			end

			fwenvs[catid]["items"][itemid]["value"] = value
		end
	end

	return fwenvs
end

function action_config()
	local snapshot, err = config.snapshot(fwenvs_8311())
	if not snapshot then return web.reply(http,503,{success=false,error=err}) end
    local display_order = { pon=1, isp=2, manage=3, device=4, sfp=5 }
    table.sort(snapshot.schema, function(a,b)
        return (display_order[a.id] or 99) < (display_order[b.id] or 99)
    end)
	local boot_config=require "8311.boot_config_transaction"
	local boot_trial,boot_trial_why=boot_config.status()
	if not boot_trial then
		boot_trial={schema=1,pending=false,error=boot_trial_why or "Boot trial status unavailable"}
	end
	ltemplate.render("8311/config", {fwenvs=snapshot.schema,revision=snapshot.revision,
		boot_known=snapshot.boot_known,pending=snapshot.pending,boot_trial=boot_trial})
end

function action_save()
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	checked_worker("config", http.formvalue())
end

function action_boot_config_apply()
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	if dispatcher.context.authuser~="root" then
		return web.reply(http,403,{success=false,error="Root administrator session required"})
	end
	checked_worker("boot-config", http.formvalue())
end

function action_boot_config_status()
	local boot_config=require "8311.boot_config_transaction"
	if http.getenv("REQUEST_METHOD")~="GET" then
		return web.reply(http,405,{success=false,error="GET required"})
	end
	if not dispatcher.context.authsession then
		return web.reply(http,403,{success=false,error="Authentication required"})
	end
	local state,why=boot_config.status()
	http.header("Cache-Control","no-store, private")
	return web.reply(http,state and 200 or 503,
		state or {success=false,error=why or "Boot configuration trial status unavailable"})
end

function action_boot_config_confirm()
	local boot_config=require "8311.boot_config_transaction"
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	if dispatcher.context.authuser~="root" then
		return web.reply(http,403,{success=false,error="Root administrator session required"})
	end
	local values=http.formvalue()
	local parse_error,parse_code=http.inputerror()
	if parse_error then return web.reply(http,parse_code,{success=false,error=parse_error}) end
	for name,value in pairs(values) do
		if (name~="token" and name~="job_id") or type(value)~="string" then
			return web.reply(http,400,{success=false,error="Unknown, missing or duplicate confirmation field"})
		end
	end
	if type(values.job_id)~="string" or #values.job_id~=32 or
	   values.job_id:find("[^0-9a-f]") then
		return web.reply(http,400,{success=false,error="Valid boot trial job ID required"})
	end
	local result,why=boot_config.confirm(values.job_id)
	return web.reply(http,result and 200 or 409,
		result and {success=true,status=result.status,confirmation_required=false,
			contains_configuration_values=false}
			or {success=false,error=why or "Boot configuration trial confirmation refused"})
end

function action_pon_config_apply()
    local pon_transaction=require "8311.pon_config_transaction"
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required for PON/OMCI changes"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local form=http.formvalue()
    local parse_error,parse_code=http.inputerror()
    if parse_error then return web.reply(http,parse_code,{success=false,error=parse_error}) end
    local snapshot,why=config.snapshot(fwenvs_8311())
    if not snapshot then return web.reply(http,503,{success=false,error=why or "Configuration snapshot unavailable"}) end
    local prepared,errors,status=config.prepare(snapshot,form)
    if not prepared then return web.reply(http,status or 422,{success=false,errors=errors}) end
    if form.mode~="apply" or prepared.route~="pon" or #prepared.changes<1 then
        return web.reply(http,409,{success=false,error="Reviewed request is not a PON/OMCI transaction"})
    end
    local changes={}
    for _,change in ipairs(prepared.changes) do
        changes[change.item.id]=change.raw
    end
    local record,error_code=jobs.start("pon_apply",{
        revision=snapshot.revision,changes=changes
    },dispatcher.context.authsession)
    changes=nil
    return web.reply(http,record and 202 or 409,
        record and {
            success=true,job=record,
            rollback_seconds=pon_transaction.WAIT_SECONDS,
            verification_seconds=pon_transaction.VERIFY_SECONDS,
            requires_explicit_confirmation=true,
            olt_per_field_effect_proven=false,
        } or {success=false,error=error_code or "PON/OMCI transaction could not start"})
end

function action_pon_config_status()
    local pon_transaction=require "8311.pon_config_transaction"
    local pon_runtime=require "8311.pon_config_runtime"
    if http.getenv("REQUEST_METHOD")~="GET" then
        return web.reply(http,405,{success=false,error="GET required"})
    end
    if not dispatcher.context.authsession then
        return web.reply(http,403,{success=false,error="Authentication required"})
    end
    local query=http.getenv("QUERY_STRING")
    if query~=nil and query~="" then
        return web.reply(http,400,{success=false,error="PON status query parameters are not supported"})
    end
    local pending,why=pon_transaction.pending()
    if not pending then
        return web.reply(http,503,{success=false,error=why or "PON transaction state unavailable"})
    end
    local state=pon_runtime.pon_state()
    local omcid=pon_runtime.omcid_running()
    http.header("Cache-Control","no-store, private, max-age=0")
    http.header("X-Content-Type-Options","nosniff")
    if pending.pending~=true then
        return web.reply(http,200,{
            success=true,pending=false,confirmation_available=false,
            pon_registered_o5_1=state==51,omcid_running=omcid==true,
            contains_configuration_values=false,
        })
    end
    local confirm=pending.phase=="trial_running" and state==51 and omcid==true
    return web.reply(http,200,{
        success=true,pending=true,job_id=pending.job_id,phase=pending.phase,
        confirmation_available=confirm,
        pon_registered_o5_1=state==51,omcid_running=omcid==true,
        olt_per_field_effect_proven=false,
        contains_configuration_values=false,
    })
end

function action_pon_config_confirm()
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required to confirm PON/OMCI changes"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=http.formvalue()
    local parse_error,parse_code=http.inputerror()
    if parse_error then return web.reply(http,parse_code,{success=false,error=parse_error}) end
    for name,value in pairs(values) do
        if (name~="token" and name~="job_id") or type(value)~="string" then
            return web.reply(http,400,{success=false,error="Unknown, missing or duplicate confirmation field"})
        end
    end
    if type(values.job_id)~="string" or #values.job_id~=32 or
       values.job_id:find("[^0-9a-f]") then
        return web.reply(http,400,{success=false,error="Valid PON transaction job ID required"})
    end
    local record,why=jobs.confirm_pon(values.job_id)
    return web.reply(http,record and 200 or 409,
        record and {success=true,job=record,contains_configuration_values=false}
            or {success=false,error=why or "PON/OMCI confirmation refused"})
end

function action_pon_explorer()
    -- Listings may contain private device metadata. Do not allow a shared
    -- browser or intermediary to retain an authenticated OMCI response.
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    -- Plain CLI MIB output is UNTRUSTED DATA. Escape content before adding
    -- only strictly numeric, statically constructed ME links.
    local code, output, overflow = web.capture({"/usr/bin/omci_pipe.sh", "md"},262144)
    local html_lines = {}
    if code ~= 0 or overflow or not output or output == "" then
        html_lines = {"PON ME listing is temporarily unavailable. Check OMCI status and system logs."}
    else
        for line in (output .. "\n"):gmatch("(.-)\n") do
            local class, instance = line:match("^|%s*(%d+)%s*|%s*(%d+)%s*%(")
            local safe = tools.html_escape(line)
            if class and instance and tonumber(class) <= 65535 and tonumber(instance) <= 65535 then
                local href = dispatcher.build_url("admin", "8311", "pon_dump", class, instance)
                -- The path comes from LuCI, while class and instance are
                -- checked decimal values. Escape the final HTML attribute.
                safe = '<a href="' .. tools.html_escape(href) .. '" data-me-id="' .. class .. '" data-instance-id="' .. instance .. '">' .. safe .. '</a>'
            end
            local marker = class and instance and ' data-me-entry="1"' or ''
            html_lines[#html_lines + 1] = '<div class="aott-me-line"' .. marker .. '>' .. safe .. '</div>'
        end
    end
    ltemplate.render("8311/pon_me", { omci=table.concat(html_lines,"\n") })
end

function action_pon_dump(me_id, instance_id)
    -- OMCI attributes can contain device/subscriber information. Never let a
    -- browser or intermediary cache a raw dump, including error responses.
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
	for _, id in ipairs({me_id or "", instance_id or ""}) do
		if type(id) ~= "string" or not id:match("^%d+$") or #id > 5 or tonumber(id) > 65535 then
			return web.reply(http,400,{error="ME and instance IDs must be decimal numbers from 0 to 65535"})
		end
	end
    local cmd = { "/usr/bin/omci_pipe.sh", "meg", me_id, instance_id }
    local code, output, overflow = web.capture(cmd, 262144)
    if code ~= 0 or overflow or not output or output == "" then
        http.status(502, "Managed entity read failed")
        http.prepare_content("text/plain; charset=utf-8")
        http.write("Managed entity lookup did not complete successfully.")
        return
    end
    http.prepare_content("text/plain; charset=utf-8")
    http.write(output)
end

-- bankctl's status action shares the firmware and boot-environment locks with
-- other operations. Concurrent read-only GUI polling can encounter a busy lock.
-- Retry a bounded number of times; never weaken the firmware writer locks.
local function bank_status()
    local nixio = require "nixio"
    for attempt = 1, 3 do
        local code, output, overflow = web.capture({"/usr/sbin/8311-bankctl.sh","status"},16384)
        if code == 0 and not overflow then
            local valid, state = pcall(json.parse, output or "")
            if valid and type(state) == "table" and state.schema == 1
                and (state.active == "A" or state.active == "B")
                and (state.committed == "A" or state.committed == "B")
                and state.boot_contract == true
                and type(state.banks) == "table"
                and type(state.state_guard) == "string"
                and #state.state_guard == 64
                and not state.state_guard:find("[^0-9a-f]")
            then
                return state
            end
            -- An apparently successful but malformed answer is not a lock race.
            return nil, "The firmware-bank response was incomplete. Actions are unavailable."
        end
        if attempt < 3 then
            -- Back off before rereading; 0.2 s then 0.4 s, bounded by CGI timeout.
            nixio.nanosleep(0, attempt * 200000000)
        end
    end
    return nil, "The firmware bank is busy or unavailable. No change was made; refresh shortly."
end

local function operation_form(allowed)
	local values = http.formvalue()
	local err, code = http.inputerror()
	if err then web.reply(http,code,{success=false,error=err}); return nil end
	for name,value in pairs(values) do
		if (name ~= "token" and not allowed[name]) or type(value) ~= "string" then
			web.reply(http,400,{success=false,error="Unknown, missing or duplicate operation field"}); return nil
		end
	end
	return values
end

-- The monitoring and local-history pages are inside the authenticated
-- admin/8311 route tree; writes also require LuCI's CSRF check.
function action_mib_profile()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({mib_file=true})
    if not values then return end
    local record,why=mib_profile.inspect(values.mib_file)
    if not record then
        return web.reply(http,422,{success=false,error=why or "MIB profile inspection failed"})
    end
    http.header("Cache-Control","no-store, private")
    http.header("X-Content-Type-Options","nosniff")
    return web.reply(http,200,{success=true,profile=record})
end

function action_history()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    local state, err = history_config.snapshot()
    if not state then
        return web.reply(http, 503, {success=false,error=err or "History configuration unavailable"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    return ltemplate.render("8311/history", {history=state})
end

function action_history_save()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values = operation_form({
        revision=true,enabled=true,pon_interval_seconds=true,
        host_interval_seconds=true,ram_sample_limit=true,ram_event_limit=true
    })
    if not values then return end
    local state, err, status = history_config.apply(values)
    return web.reply(http, status or 503,
        state and {success=true,revision=state.revision,
                   enabled=state.enabled,service_running=state.service_running,
                   pon_interval_seconds=state.pon_interval_seconds,
                   host_interval_seconds=state.host_interval_seconds,
                   ram_sample_limit=state.ram_sample_limit,
                   ram_event_limit=state.ram_event_limit}
            or {success=false,error=err or "History configuration failed"})
end

function action_history_data()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    if not dispatcher.context.authsession then
        return web.reply(http, 403, {success=false,error="Authentication required"})
    end
    local query=http.getenv("QUERY_STRING")
    if query~=nil and query~="" then
        return web.reply(http, 400, {success=false,error="History query parameters are not supported"})
    end
    local body, info = history_snapshot.read_guarded()
    if not body then
        return web.reply(http, 503, {success=false,error=info or "History is unavailable"})
    end
    http.status(200, "OK")
    http.header("Cache-Control", "no-store, private, max-age=0")
    http.header("X-Content-Type-Options", "nosniff")
    http.header("Content-Security-Policy", "default-src 'none'")
    http.header("Referrer-Policy", "no-referrer")
    http.header("Vary", "Cookie")
    http.prepare_content("application/json; charset=utf-8")
    http.write(body)
end

function action_management_preflight()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    local state=management_preflight.status()
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    return ltemplate.render("8311/management_preflight", {management=state})
end

function action_management_vlan_preview()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    local values=operation_form({vlan=true})
    if not values then return end
    local plan,why=management_preflight.preview(values.vlan)
    return web.reply(http, plan and 200 or 422,
        plan and {
            success=true,current_vlan=plan.current_vlan,
            requested_vlan=plan.requested_vlan,
            operations=plan.operations,
            network_operations=plan.network_operations,
            firewall_operations=plan.firewall_operations,
            changes_required=plan.changes_required,
            recovery_store_ready=plan.recovery_store_ready,
            recovery_provisioning_required=plan.recovery_provisioning_required,
            native_fields_checked=plan.native_fields_checked,
            native_present_empty=plan.native_present_empty,
            production_write_allowed=false
        } or {success=false,error=why or "Management VLAN preview unavailable"})
end

function action_management_preview()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({
        vlan=true,ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true
    })
    if not values then return end
    local plan,why=management_preflight.preview_management(values)
    return web.reply(http,plan and 200 or 422,
        plan and {
            success=true,status=plan.status,current_vlan=plan.current_vlan,
            requested_vlan=plan.requested_vlan,operations=plan.operations,
            network_operations=plan.network_operations,
            firewall_operations=plan.firewall_operations,
            changes_required=plan.changes_required,
            recovery_store_ready=plan.recovery_store_ready,
            recovery_provisioning_required=plan.recovery_provisioning_required,
            native_fields_checked=plan.native_fields_checked,
            production_apply_source_available=plan.production_apply_source_available,
            hardware_qualified=false,requires_timed_confirmation=true
        } or {success=false,error=why or "Management preview unavailable"})
end

function action_management_apply()
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required for management changes"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({
        vlan=true,ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true
    })
    if not values then return end
    local plan,why=management_preflight.preview_management(values)
    if not plan then
        return web.reply(http,422,{success=false,error=why or "Management preflight failed"})
    end
    local record,error_code=jobs.start(
        "management_apply",values,dispatcher.context.authsession)
    local loaded,tx=pcall(require,"8311.management_transaction")
    local seconds=loaded and type(tx)=="table" and tx.WAIT_SECONDS or 180
    return web.reply(http,record and 202 or 409,
        record and {success=true,job=record,rollback_seconds=seconds,
                    changes_required=plan.changes_required}
            or {success=false,error=error_code or "Management transaction could not start"})
end

function action_management_confirm()
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required to confirm management changes"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({job_id=true})
    if not values then return end
    local record,why=jobs.confirm_management(values.job_id)
    return web.reply(http,record and 200 or 409,
        record and {success=true,job=record}
            or {success=false,error=why or "Management confirmation was refused"})
end

local function access_values()
    return operation_form({
        revision=true,
        ssh_enabled=true,ssh_port=true,ssh_password_auth=true,
        ssh_root_password_auth=true,ssh_root_login=true,
        ssh_gateway_ports=true,ssh_keepalive=true,ssh_idle_timeout=true,
        ssh_max_auth_tries=true,ssh_mdns=true,luci_sessiontime=true,
        web_http_port=true,web_https_port=true,web_script_timeout=true,
        web_network_timeout=true,web_http_keepalive=true,
        web_tcp_keepalive=true,web_max_requests=true,
        web_max_connections=true,web_rfc1918_filter=true,
        remote_gui_enabled=true,remote_gui_ipv4_sources=true
    })
end

local function access_runtime()
    local ok,cfg=pcall(require,"8311.access_config")
    local ok2,tx=pcall(require,"8311.access_transaction")
    if not ok or type(cfg)~="table" or not ok2 or type(tx)~="table" then
        return nil,nil,"Access configuration runtime is unavailable"
    end
    return cfg,tx
end

function action_access()
    if http.getenv("REQUEST_METHOD")~="GET" then
        return web.reply(http,405,{success=false,error="GET required"})
    end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local cfg,tx,why=access_runtime()
    if not cfg then return web.reply(http,503,{success=false,error=why}) end
    local snapshot,swhy=cfg.snapshot()
    if not snapshot then return web.reply(http,503,{success=false,error=swhy or "Access configuration unavailable"}) end
    local public=cfg.public_snapshot(snapshot)
    if not public then return web.reply(http,503,{success=false,error="Access configuration unavailable"}) end
    local pending,pwhy=tx.pending()
    if not pending then pending={pending=false,error=pwhy} end
    http.header("Cache-Control","no-store, private")
    http.header("X-Content-Type-Options","nosniff")
    return ltemplate.render("8311/access",{access=public,pending=pending})
end

function action_access_preview()
    if not dispatcher.context.authsession or not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=access_values(); if not values then return end
    local cfg,_,why=access_runtime()
    if not cfg then return web.reply(http,503,{success=false,error=why}) end
    local snapshot,swhy=cfg.snapshot()
    if not snapshot then return web.reply(http,503,{success=false,error=swhy}) end
    local prepared,errors,status=cfg.prepare(snapshot,values)
    return web.reply(http,prepared and 200 or (status or 422),
        prepared and {success=true,revision=prepared.revision,diff=prepared.diff,
                      changes_required=prepared.changes_required,
                      confirmation_required=prepared.confirmation_required,
                      listener_migration_required=prepared.listener_migration_required}
            or {success=false,errors=errors})
end

function action_access_apply()
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required for access changes"})
    end
    if not dispatcher.context.authsession or not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=access_values(); if not values then return end
    local cfg,tx,why=access_runtime()
    if not cfg then return web.reply(http,503,{success=false,error=why}) end
    local snapshot,swhy=cfg.snapshot()
    if not snapshot then return web.reply(http,503,{success=false,error=swhy}) end
    local prepared,errors,status=cfg.prepare(snapshot,values)
    if not prepared then return web.reply(http,status or 422,{success=false,errors=errors}) end
    if not prepared.changes_required then
        return web.reply(http,200,{success=true,status="ACCESS_TRANSACTION_NO_CHANGE",
            confirmation_required=false,changes_required=false})
    end
    local record,error_code=jobs.start("access_apply",values,dispatcher.context.authsession)
    return web.reply(http,record and 202 or 409,
        record and {success=true,job=record,rollback_seconds=tx.WAIT_SECONDS,
                    confirmation_required=true,changes_required=true}
            or {success=false,error=error_code or "Access transaction could not start"})
end

function action_access_confirm()
    local https=http.getenv("HTTPS")
    if https~="on" and https~="1" then
        return web.reply(http,403,{success=false,error="HTTPS is required to confirm access changes"})
    end
    if not dispatcher.context.authsession or not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({job_id=true}); if not values then return end
    local record,why=jobs.confirm_access(values.job_id)
    return web.reply(http,record and 200 or 409,
        record and {success=true,job=record}
            or {success=false,error=why or "Access confirmation was refused"})
end

function action_access_status()
    if http.getenv("REQUEST_METHOD")~="GET" then
        return web.reply(http,405,{success=false,error="GET required"})
    end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local cfg,tx,why=access_runtime()
    if not cfg then return web.reply(http,503,{success=false,error=why}) end
    local snapshot,swhy=cfg.snapshot()
    if not snapshot then return web.reply(http,503,{success=false,error=swhy}) end
    local public=cfg.public_snapshot(snapshot)
    local pending,pwhy=tx.pending()
    return web.reply(http,200,{success=true,access=public,
        pending=pending or {pending=false,error=pwhy},
        contains_credentials=false,contains_management_address=false})
end

function action_tls()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    local candidate,why=tls_candidate.status()
    if not candidate then
        candidate={status="unavailable",candidate_ready=false}
    end
    local ok,security=pcall(health.security)
    if not ok or type(security)~="table" then security={} end
    local pending,pending_why=tls_activation.pending()
    if not pending then pending={pending=false,error=pending_why} end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    http.header("Referrer-Policy", "no-referrer")
    return ltemplate.render("8311/tls", {candidate=candidate,security=security,pending=pending})
end

local function tls_https_required()
    local value=http.getenv("HTTPS")
    return value=="on" or value=="1"
end

function action_tls_generate()
    if not tls_https_required() then
        return web.reply(http,403,{success=false,error="HTTPS is required for TLS candidate operations"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values=operation_form({
        dns_sans=true,ip_sans=true,days=true,key_type=true
    })
    if not values then return end
    local state,why,status=tls_candidate.generate(values)
    return web.reply(http,status or 503,
        state and {
            success=true,candidate_ready=state.candidate_ready,
            certificate_sha256=state.certificate_sha256,
            certificate_bytes=state.certificate_bytes,
            private_key_bytes=state.private_key_bytes,
            private_key_mode=state.private_key_mode,
            dns_san_count=state.dns_san_count,
            ipv4_san_count=state.ipv4_san_count,
            validity_days=state.validity_days,
            key_type=state.key_type,
            active_https_changed=false,
            install_available=false
        } or {success=false,error=why or "TLS candidate generation failed"})
end

function action_tls_import()
    if not tls_https_required() then
        return web.reply(http,403,{success=false,error="HTTPS is required for TLS import"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    http.header("Cache-Control","no-store, private")
    http.header("X-Content-Type-Options","nosniff")
    http.header("Referrer-Policy","no-referrer")
    local state,why,status=tls_import.receive(http,dispatcher.context.authsession)
    return web.reply(http,status or 503,
        state and {
            success=true,status=state.status,
            candidate_ready=state.candidate_ready,
            certificate_sha256=state.certificate_sha256,
            certificate_bytes=state.certificate_bytes,
            private_key_bytes=state.private_key_bytes,
            private_key_mode=state.private_key_mode,
            expires_utc=state.expires_utc,
            dns_san_count=state.dns_san_count,
            ipv4_san_count=state.ipv4_san_count,
            chain_certificates=state.chain_certificates,
            native_uhttpd_pair_verified=state.native_uhttpd_pair_verified,
            chain_name_links_verified=state.chain_name_links_verified,
            browser_trust_unverified=true,
            active_https_changed=false,
        } or {success=false,error=why or "TLS import failed"})
end

function action_tls_discard()
    if not tls_https_required() then
        return web.reply(http,403,{success=false,error="HTTPS is required for TLS candidate operations"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values=operation_form({})
    if not values then return end
    local state,why,status=tls_candidate.discard()
    return web.reply(http,status or 503,
        state and {success=true,candidate_ready=false,active_https_changed=false}
            or {success=false,error=why or "TLS candidate discard failed"})
end

function action_tls_activate()
    if not tls_https_required() then
        return web.reply(http,403,{success=false,error="HTTPS is required for TLS activation"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({certificate_sha256=true})
    if not values then return end
    if type(values.certificate_sha256)~="string" or
       #values.certificate_sha256~=64 or
       values.certificate_sha256:find("[^0-9a-f]") then
        return web.reply(http,422,{success=false,error="Refresh the TLS candidate before activation"})
    end
    local state,why=tls_candidate.status()
    if not state or state.candidate_ready~=true or
       state.certificate_sha256~=values.certificate_sha256 then
        return web.reply(http,409,{success=false,error=why or "TLS candidate changed; refresh before activation"})
    end
    local pending,pending_why=tls_activation.pending()
    if not pending then
        return web.reply(http,503,{success=false,error=pending_why or "TLS activation state unavailable"})
    end
    if pending.pending then
        return web.reply(http,409,{success=false,error="A TLS activation is already awaiting confirmation"})
    end
    local record,error_code=jobs.start("tls_activate",
        {certificate_sha256=values.certificate_sha256},
        dispatcher.context.authsession)
    return web.reply(http,record and 202 or 409,
        record and {success=true,job=record,rollback_seconds=tls_activation.WAIT_SECONDS}
            or {success=false,error=error_code or "TLS activation could not start"})
end

function action_tls_confirm()
    if not tls_https_required() then
        return web.reply(http,403,{success=false,error="HTTPS is required to confirm TLS activation"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local values=operation_form({job_id=true})
    if not values then return end
    local record,why=jobs.confirm_tls(values.job_id)
    return web.reply(http,record and 200 or 409,
        record and {success=true,job=record}
            or {success=false,error=why or "TLS activation confirmation was refused"})
end

function action_v3()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    return ltemplate.render("8311/v3", {})
end

function action_v3_status()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    local cap = require "8311.v3_capabilities"
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    return web.reply(http, 200, cap.snapshot())
end

function action_factory_password_ack()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security() then return end
    if dispatcher.context.authuser~="root" then
        return web.reply(http,403,{success=false,error="Root administrator session required"})
    end
    local loaded,first_login=pcall(require,"8311.first_login")
    if not loaded or type(first_login)~="table" or type(first_login.acknowledge)~="function" then
        return web.reply(http,503,{success=false,error="Factory password prompt state unavailable"})
    end
    local result,why=first_login.acknowledge()
    if not result then
        return web.reply(http,503,{success=false,error=why or "Factory password prompt acknowledgement failed"})
    end
    return http.redirect(dispatcher.build_url("admin","status","overview"))
end

function action_r8_monitoring()
    if http.getenv("REQUEST_METHOD") ~= "GET" then
        return web.reply(http, 405, {success=false,error="GET required"})
    end
    local state, err = monitoring.snapshot()
    if not state then
        return web.reply(http, 503, {success=false,error=err})
    end
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    -- The private saved digest and UCI section must never enter the view scope.
    state.original = nil
    state.section = nil
    return ltemplate.render("8311/monitoring", {monitor=state})
end

function action_r8_monitoring_save()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values = operation_form({
        revision=true,log_remote=true,log_ip=true,log_port=true,
        log_proto=true,aott_metrics=true,aott_metrics_client=true
    })
    if not values then return end
    local state, err, status = monitoring.apply(values)
    return web.reply(http, status or 503,
        state and {success=true,revision=state.revision,
                   configured=state.configured,
                   log_remote=state.log_remote,log_ip=state.log_ip,
                   log_port=state.log_port,log_proto=state.log_proto,
                   aott_metrics=state.aott_metrics,
                   aott_metrics_client=state.aott_metrics_client,
                   credential_configured=state.credential_configured,
                   receiver_confirmed=false}
            or {success=false,error=err or "Monitoring configuration failed"})
end

function action_r8_monitoring_test()
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values = operation_form({})
    if not values then return end
    local result, err = monitoring.send_test()
    return web.reply(http, result and 200 or 503,
        result and {success=true,event_id=result.event_id,
                    receiver_confirmed=false,note=result.note}
            or {success=false,error=err})
end

function action_r8_monitoring_credential()
    http.header("Cache-Control", "no-store, private")
    http.header("X-Content-Type-Options", "nosniff")
    http.header("Referrer-Policy", "no-referrer")
    if http.getenv("HTTPS") ~= "on" and http.getenv("HTTPS") ~= "1" then
        return web.reply(http, 403, {success=false,
            error="HTTPS is required for collector credential management"})
    end
    if not dispatcher.context.authsession or
       not dispatcher.test_post_security(true) then return end
    local values = operation_form({revision=true,credential_action=true})
    if not values then return end
    local result, why, status = monitoring.change_credential(
        values.revision, values.credential_action)
    return web.reply(http, status or 503,
        result and {success=true,revision=result.revision,
                    credential_configured=result.credential_configured,
                    aott_metrics=result.aott_metrics,
                    collector_token=result.collector_token}
            or {success=false,error=why or "Credential change failed"})
end

function action_bank_status()
    -- An administrator's boot-state fingerprint is a transient concurrency
    -- precondition. Never cache it in a proxy or intermediary.
    http.header("Cache-Control","no-store, private")
    http.header("X-Content-Type-Options","nosniff")
	local state, err = bank_status()
	web.reply(http,state and 200 or 503,state or {success=false,error=err})
end

function action_firmware_upload()
	if not dispatcher.context.authsession or not dispatcher.test_post_security(true) then return end
	local record, err, code = uploads.receive(http, dispatcher.context.authsession)
	web.reply(http,record and 201 or (code or 400), record and {success=true,upload=record} or {success=false,error=err})
end

function action_job_status()
	local id = http.formvalue("id")
	if type(id) ~= "string" then return web.reply(http,400,{success=false,error="Job ID required"}) end
	local record, err = jobs.get(id, dispatcher.context.authsession)
	web.reply(http,record and 200 or 404,record or {success=false,error=err})
end

function action_job_cancel()
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	local values = operation_form({id=true}); if not values then return end
	local record, err = jobs.cancel(values.id, dispatcher.context.authsession)
	web.reply(http,record and 200 or 409,record or {success=false,error=err})
end

function action_firmware()
	if http.getenv("REQUEST_METHOD") == "GET" then
		local state, err = bank_status()
		local version = require "8311.version"
		return ltemplate.render("8311/firmware", {version=version,bank_state=state,bank_error=err,
			uploads=uploads.list(dispatcher.context.authsession),upload_maximum=uploads.maximum})
	end
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	local values = operation_form({action=true,upload_id=true,sha256=true,bank=true,state_guard=true,expected_active=true,expected_target=true})
	if not values then return end
	local action = values.action
	if action == "discard_upload" then
        if values.state_guard or values.expected_active or values.expected_target then
            return web.reply(http,400,{success=false,error="Unexpected bank expectation for upload discard"})
        end
		local ok, err = uploads.discard(values.upload_id, dispatcher.context.authsession)
		return web.reply(http,ok and 200 or 409,{success=not not ok,error=err})
	elseif action == "validate" or action == "install" then
        if values.bank then
            return web.reply(http,400,{success=false,error="Unexpected bank operation field for an archive"})
        end
        if action == "install" then
            if not ((values.expected_active == "A" and values.expected_target == "B") or
                    (values.expected_active == "B" and values.expected_target == "A")) then
                return web.reply(http,409,{success=false,
                    error="Refresh live bank state and review the exact overwrite target."})
            end
            if type(values.state_guard) ~= "string" or #values.state_guard ~= 64 or
                values.state_guard:find("[^0-9a-f]") then
                return web.reply(http,409,{success=false,
                    error="A fresh bank-state confirmation is required for installation."})
            end
        elseif values.state_guard or values.expected_active or values.expected_target then
            return web.reply(http,400,{success=false,error="Validation does not change any bank"})
        end
		local artifact, err = uploads.get(values.upload_id, dispatcher.context.authsession)
		if not artifact then return web.reply(http,404,{success=false,error=err}) end
		if type(values.sha256) ~= "string" or values.sha256 ~= artifact.sha256 then
			return web.reply(http,409,{success=false,error="Upload digest changed; select and review this upload again"})
		end
		local args = {upload_id=artifact.upload_id,path=artifact.path,sha256=artifact.sha256,size=artifact.size}
        if action == "install" then
            args.expected_active=values.expected_active
            args.expected_target=values.expected_target
            args.state_guard=values.state_guard
        end
		local record, why = jobs.start(action == "validate" and "firmware_validate" or "firmware_install",args,dispatcher.context.authsession)
		return web.reply(http,record and 202 or 409,record or {success=false,error=why})
	end
	local args = {}
	local commands = {commit="commit",cancel_trial="cancel_trial",return_saved="return_saved",reboot="reboot"}
	if commands[action] then args.action=commands[action]
	elseif action == "trial" or action == "verify_bank" then
		if values.bank ~= "A" and values.bank ~= "B" then return web.reply(http,400,{success=false,error="Select bank A or B"}) end
		args.action=action == "trial" and "trial" or "verify"; args.bank=values.bank
	else return web.reply(http,400,{success=false,error="Unsupported firmware operation"}) end
	if values.upload_id or values.sha256 or values.expected_active or
        values.expected_target or (values.bank and not args.bank) then
		return web.reply(http,400,{success=false,error="Unexpected argument for this bank operation"})
	end
    -- The guard comes from a live authenticated bank-status read. It is
    -- a concurrency precondition, not a credential or CSRF substitute.
    -- The bank-control utility verifies it under the actual firmware lock.
    if type(values.state_guard) ~= "string" or #values.state_guard ~= 64 or
        values.state_guard:find("[^0-9a-f]") then
        return web.reply(http,409,{success=false,
            error="Live firmware state confirmation required. Refresh and review before retrying."})
    end
    args.state_guard=values.state_guard
	local record, why = jobs.start("bank_operation", args, dispatcher.context.authsession)
	return web.reply(http,record and 202 or 409,record or {success=false,error=why})
end

function action_support()
	if http.getenv("REQUEST_METHOD") == "GET" then return ltemplate.render("8311/support", {}) end
	if not dispatcher.context.authsession or
	   not dispatcher.test_post_security() then return end
	local values = operation_form({action=true,full=true}); if not values then return end
	if values.action ~= "generate" or (values.full ~= "0" and values.full ~= "1") then
		return web.reply(http,400,{success=false,error="Choose a diagnostic export mode"})
	end
	local record, err = jobs.start("support",{full=values.full == "1"},dispatcher.context.authsession)
	web.reply(http,record and 202 or 409,record or {success=false,error=err})
end

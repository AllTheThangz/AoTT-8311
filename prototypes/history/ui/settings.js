/* AoTT-8311 H-018 source-only history settings preview.
 * Uses the real Lua catalogue injected by an isolated test harness.
 * No saved settings, services, device writes, probes or notifications.
 */
(function () {
  "use strict";
  const EXACT_IDS = new Set([
    "sampling_enabled","pon_interval_seconds","host_interval_seconds",
    "optical_interval_seconds","heavy_probe_seconds","ram_sample_limit",
    "ram_event_limit","persist_enabled","retention_days",
    "flush_interval_seconds","local_alerts_enabled","alert_pon_changes",
    "alert_host_changes","alert_gaps","alert_reboots","rx_low_dbm",
    "remote_notifications"
  ]);
  const OPTIONS = {
    pon_interval_seconds:[30,60,120,300],
    host_interval_seconds:[30,60,120,300],
    optical_interval_seconds:[60,120,300],
    heavy_probe_seconds:[0,300,900],
    flush_interval_seconds:[900,1800,3600,7200],
    retention_days:[0,7,30,90]
  };
  const LIMITS = {
    ram_sample_limit:[30,720],
    ram_event_limit:[16,256]
  };
  const BOOL = new Set([
    "sampling_enabled","persist_enabled","local_alerts_enabled",
    "alert_pon_changes","alert_host_changes","alert_gaps",
    "alert_reboots","remote_notifications"
  ]);
  const formState = {
    original:null,fields:null,inputs:new Map()
  };
  function id(key) { return document.getElementById(key); }
  function status(message) { id("settings-error").textContent=message; }
  function clear() {
    formState.original=null;
    formState.fields=null;
    formState.inputs=new Map();
    id("settings-basic-fields").replaceChildren();
    id("settings-advanced-fields").replaceChildren();
    id("settings-preview-button").disabled=true;
    id("settings-reset-button").disabled=true;
    id("settings-preview").textContent="No validated settings catalogue is loaded.";
  }
  function typeFor(key) {
    if (BOOL.has(key)) return "boolean";
    if (OPTIONS[key]) return "choice";
    if (LIMITS[key]) return "integer";
    if (key==="rx_low_dbm") return "optional_half_dbm";
    return null;
  }
  function validSnapshot(payload) {
    if (!payload || typeof payload!=="object" || payload.schema!==1 ||
        payload.demo!==true || payload.real_save_available!==false ||
        payload.output_is_live!==false ||
        payload.firmware_persistence_available!==false ||
        payload.alerts_running!==false ||
        !payload.state || !payload.catalogue ||
        payload.state.schema!==1 || payload.state.revision!==1 ||
        payload.state.source_only_not_live!==true ||
        payload.state.no_device_write!==true ||
        payload.catalogue.schema!==1 ||
        payload.catalogue.no_real_setting_save!==true ||
        payload.catalogue.hardware_qualification_unverified!==true ||
        !Array.isArray(payload.catalogue.fields) ||
        payload.catalogue.fields.length!==17 ||
        !payload.state.values || typeof payload.state.values!=="object") {
      return false;
    }
    const seen=new Set();
    for (const row of payload.catalogue.fields) {
      if (!row || typeof row!=="object" || !EXACT_IDS.has(row.id) ||
          seen.has(row.id) || typeof row.label!=="string" ||
          row.label.length>85 || !["basic","advanced"].includes(row.group) ||
          typeFor(row.id)!==row.type ||
          typeof row.available!=="boolean") return false;
      seen.add(row.id);
      if (row.available===false && ![
        "not_hardware_qualified","delivery_not_implemented"
      ].includes(row.unavailable_reason)) return false;
      if (row.type==="choice" &&
          (!Array.isArray(row.options) ||
           JSON.stringify(row.options)!==JSON.stringify(OPTIONS[row.id]))) {
        return false;
      }
      if (row.type==="integer" &&
          (row.minimum!==LIMITS[row.id][0] ||
           row.maximum!==LIMITS[row.id][1])) return false;
      const value=payload.state.values[row.id];
      if (row.type==="boolean" && typeof value!=="boolean") return false;
      if (row.type==="choice" && !OPTIONS[row.id].includes(value)) return false;
      if (row.type==="integer" && (!Number.isInteger(value) ||
          value<LIMITS[row.id][0] || value>LIMITS[row.id][1])) return false;
      if (row.type==="optional_half_dbm" && value!==undefined &&
          (typeof value!=="number" || !Number.isFinite(value) ||
           value<-35 || value>-5 || !Number.isInteger(value*2))) return false;
    }
    return seen.size===EXACT_IDS.size &&
           payload.state.values.sampling_enabled===false &&
           payload.state.values.persist_enabled===false &&
           payload.state.values.local_alerts_enabled===false &&
           payload.state.values.remote_notifications===false;
  }
  function makeField(definition,value) {
    const box=document.createElement("div");
    box.className="settings-field";
    box.setAttribute("aria-disabled",definition.available ? "false":"true");
    const label=document.createElement("label");
    label.textContent=definition.label;
    const controlId="setting-"+definition.id;
    label.htmlFor=controlId;
    box.appendChild(label);
    let input;
    if (definition.type==="choice") {
      input=document.createElement("select");
      definition.options.forEach(function (option) {
        const opt=document.createElement("option");
        opt.value=String(option);
        opt.textContent=option===0 ? "Off" : String(option);
        input.appendChild(opt);
      });
      input.value=String(value);
    } else {
      input=document.createElement("input");
      if (definition.type==="boolean") {
        input.type="checkbox";
        input.checked=value===true;
      } else {
        input.type="number";
        input.step=definition.type==="optional_half_dbm" ? "0.5" : "1";
        if (definition.type==="integer") {
          input.min=String(definition.minimum);
          input.max=String(definition.maximum);
        } else {
          input.min="-35";
          input.max="-5";
        }
        input.value=value===undefined ? "" : String(value);
      }
    }
    input.id=controlId;
    input.disabled=!definition.available;
    box.appendChild(input);
    if (!definition.available) {
      const reason=document.createElement("span");
      reason.className="settings-reason";
      reason.textContent=definition.unavailable_reason==="delivery_not_implemented"
        ? "Not implemented. No external notifications are sent."
        : "Unavailable until separately qualified on hardware.";
      box.appendChild(reason);
    }
    formState.inputs.set(definition.id,input);
    return box;
  }
  function render(payload) {
    clear();
    if (!validSnapshot(payload)) {
      status("Invalid source-only settings description.");
      return false;
    }
    const safeValues={};
    const safeFields=[];
    for (const def of payload.catalogue.fields) {
      const row={
        id:def.id,label:def.label,group:def.group,
        type:def.type,available:def.available,
        unavailable_reason:def.unavailable_reason
      };
      if (def.options) row.options=def.options.slice();
      if (def.minimum!==undefined) row.minimum=def.minimum;
      if (def.maximum!==undefined) row.maximum=def.maximum;
      safeFields.push(row);
      const value=payload.state.values[def.id];
      if (value!==undefined) safeValues[def.id]=value;
    }
    formState.original=safeValues;
    formState.fields=safeFields;
    for (const def of safeFields) {
      const target=def.group==="basic"
        ? id("settings-basic-fields") : id("settings-advanced-fields");
      target.appendChild(makeField(def,safeValues[def.id]));
    }
    id("settings-preview-button").disabled=false;
    id("settings-reset-button").disabled=false;
    status("");
    id("settings-preview").textContent=
      "Settings are available for local preview only. Nothing is applied to the ONU.";
    return true;
  }
  function draft() {
    if (!formState.original || !formState.fields) return null;
    const values=Object.assign({},formState.original);
    for (const def of formState.fields) {
      if (!def.available) continue;
      const input=formState.inputs.get(def.id);
      if (!input) return null;
      let value;
      if (def.type==="boolean") {
        value=input.checked;
      } else if (def.type==="optional_half_dbm") {
        value=input.value==="" ? undefined : Number(input.value);
      } else {
        if (!input.value.trim()) return null;
        value=Number(input.value);
      }
      if (def.type==="choice" && !OPTIONS[def.id].includes(value)) return null;
      if (def.type==="integer" && (!Number.isInteger(value) ||
          value<LIMITS[def.id][0] || value>LIMITS[def.id][1])) return null;
      if (def.type==="optional_half_dbm" && value!==undefined &&
          (!Number.isFinite(value) || value<-35 || value>-5 ||
           !Number.isInteger(value*2))) return null;
      if (value===undefined) delete values[def.id];
      else values[def.id]=value;
    }
    return values;
  }
  function preview() {
    if (!formState.original) {
      status("No valid source-only preferences loaded.");
      return null;
    }
    const values=draft();
    if (!values) {
      status("Invalid values. Check numerical limits and supported intervals.");
      id("settings-preview").textContent="No configuration applied.";
      return null;
    }
    if (values.sampling_enabled || values.persist_enabled ||
        values.local_alerts_enabled || values.remote_notifications ||
        values.retention_days!==0 || values.heavy_probe_seconds>0 ||
        values.rx_low_dbm!==undefined) {
      status("Requested feature is unavailable until hardware or delivery qualification.");
      return null;
    }
    const worst=3600/values.pon_interval_seconds*3+
                3600/values.host_interval_seconds*4;
    if (!Number.isFinite(worst) || worst>720) {
      status("Polling exceeds the source model's 720-second per-hour worst-case command budget.");
      id("settings-preview").textContent="Unsafe polling plan rejected. No configuration applied.";
      return null;
    }
    const changed=Object.keys(values).filter(
      key=>values[key]!==formState.original[key]);
    if (!changed.length) {
      status("No proposed changes. The defaults remain unchanged.");
      id("settings-preview").textContent="Nothing to preview. No settings were saved.";
      return null;
    }
    status("");
    const result={
      source_only_not_live:true,preview_only:true,
      no_device_write:true,no_flash_write:true,no_alert_sent:true,
      changed_fields:changed.slice().sort(),
      pon_calls_per_hour:3600/values.pon_interval_seconds,
      host_calls_per_hour:3600/values.host_interval_seconds,
      optical_reads_per_hour:3600/values.optical_interval_seconds,
      worst_case_command_seconds_per_hour:worst,
      worst_case_command_duty_fraction:worst/3600,
      ram_sample_limit:values.ram_sample_limit,
      ram_event_limit:values.ram_event_limit,
      external_notifications:"not_implemented",
    };
    id("settings-preview").textContent=[
      "Proposed fields: "+result.changed_fields.join(", "),
      "PON reads per hour: "+result.pon_calls_per_hour,
      "Ethernet reads per hour: "+result.host_calls_per_hour,
      "Optical reads per hour: "+result.optical_reads_per_hour,
      "Worst-case process wait budget: "+worst+" seconds per hour (not measured CPU usage)",
      "RAM capacity: "+values.ram_sample_limit+" samples and "+values.ram_event_limit+" events",
      "No settings saved. Sampling, flash writes and alerts remain disabled."
    ].join("\n");
    return result;
  }
  function reset() {
    if (!formState.original || !formState.fields) return false;
    for (const field of formState.fields) {
      const input=formState.inputs.get(field.id);
      const value=formState.original[field.id];
      if (field.type==="boolean") input.checked=value===true;
      else input.value=value===undefined ? "" : String(value);
    }
    status("");
    id("settings-preview").textContent=
      "Draft restored to source defaults. No changes were saved.";
    return true;
  }
  function bind() {
    id("settings-preview-button").addEventListener("click",preview);
    id("settings-reset-button").addEventListener("click",reset);
    id("settings-theme").addEventListener("change",function (event) {
      if (event.target.value==="light" || event.target.value==="dark") {
        document.documentElement.setAttribute("data-aott-theme",event.target.value);
      }
    });
  }
  window.AoTTHistorySettings={
    render:render,preview:preview,reset:reset,sourceOnly:true
  };
  if (document.readyState==="loading") {
    document.addEventListener("DOMContentLoaded",bind,{once:true});
  } else bind();
})();

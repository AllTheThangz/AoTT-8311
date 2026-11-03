/* AoTT-8311 H-016 source-only history preview.
 * Never starts probes, fetches data, or claims a connection to an ONU.
 * A future authenticated LuCI adapter must explicitly supply a validated
 * projection from the bounded H-011/H-014 Lua source pipeline.
 */
(function () {
  "use strict";
  const RANGE_SECONDS = {
    hour: 3600, day: 86400, week: 604800,
    month: 2592000, ninety_days: 7776000
  };
  const SAMPLE_STATES = new Set([
    "baseline", "valid_interval", "observation_unavailable",
    "reboot", "source_changed", "sampling_gap"
  ]);
  const EVENT_NAMES = {
    pon_state_change: "PON state changed",
    host_link_change: "Host Ethernet changed",
    reboot_observed: "ONU reboot observed",
    source_changed: "Host interface changed",
    sampling_gap: "Observation gap",
    observation_unavailable: "Observation unavailable"
  };
  const NS = "http://www.w3.org/2000/svg";
  const documentRoot = document.documentElement;
  let current = null;
  let activeRange = "hour";

  function id(name) {
    return document.getElementById(name);
  }
  function valid(v, max) {
    return typeof v === "number" && Number.isFinite(v) &&
           v >= 0 && v <= (max === undefined ? 1e12 : max);
  }
  function int(v, max) {
    return valid(v, max) && Number.isInteger(v);
  }
  function safeScalar(source, keys, out) {
    keys.forEach(function (key) {
      const value = source[key];
      if (valid(value)) out[key] = value;
    });
  }
  function safeStats(src) {
    const out = {};
    if (!src || typeof src !== "object") return out;
    safeScalar(src, ["average_mbps", "peak_mbps", "covered_seconds",
                      "coverage_fraction", "interval_count"], out);
    return out;
  }
  function safeWindow(src, requested) {
    if (!src || typeof src !== "object" ||
        src.requested_window_seconds !== requested ||
        src.window_complete !== false ||
        src.customer_wan_throughput_proven !== false ||
        src.full_internet_availability_proven !== false ||
        src.cross_reboot_continuity_proven !== false ||
        src.hardware_resource_qualified !== false) return null;
    const out = {
      requested_window_seconds: requested, window_complete: false,
      customer_wan_throughput_proven: false,
      full_internet_availability_proven: false,
      cross_reboot_continuity_proven: false,
      hardware_resource_qualified: false,
      rx: safeStats(src.rx), tx: safeStats(src.tx),
      terminated_at_epoch_boundary: src.terminated_at_epoch_boundary === true
    };
    safeScalar(src, ["latest_uptime", "observed_span_seconds",
                     "samples_considered", "unavailable_pon_samples",
                     "unavailable_host_samples", "samples_without_valid_rate",
                     "excluded_cross_window_intervals", "pon_state",
                     "host_link_speed_mbps"], out);
    if (["observed","unavailable"].includes(src.pon_observation)) {
      out.pon_observation = src.pon_observation;
    }
    if (["observed","unavailable"].includes(src.host_link_observation)) {
      out.host_link_observation = src.host_link_observation;
    }
    if (typeof src.status === "string" &&
        ["no_retained_samples", "no_valid_rate_intervals", "partial_measured_rates"].includes(src.status)) {
      out.status = src.status;
    }
    return out;
  }
  function hostInterface(value) {
    return typeof value === "string" && value.length <= 15 &&
      /^(?:eth\d+(?:[._]?\d*)?|en[a-z0-9_.-]+|lan\d+|sfp\d+)$/.test(value);
  }
  function safeSample(src) {
    if (!src || typeof src !== "object" ||
        (!int(src.epoch_index, Number.MAX_SAFE_INTEGER) || src.epoch_index<1) ||
        !valid(src.at_uptime) || !hostInterface(src.source) ||
        !SAMPLE_STATES.has(src.status)) return null;
    const out = {
      epoch_index: src.epoch_index, at_uptime: src.at_uptime,
      source: src.source, status: src.status
    };
    safeScalar(src, ["pon_state", "host_link_speed_mbps", "elapsed_seconds",
                     "rx_mbps", "tx_mbps"], out);
    if (["observed", "unavailable"].includes(src.pon_observation)) {
      out.pon_observation = src.pon_observation;
    }
    if (["observed", "unavailable"].includes(src.host_link_observation)) {
      out.host_link_observation = src.host_link_observation;
    }
    if (out.status !== "valid_interval" || !valid(out.elapsed_seconds, 3600)) {
      delete out.elapsed_seconds;
      delete out.rx_mbps;
      delete out.tx_mbps;
    }
    return out;
  }
  function safeEvent(src) {
    if (!src || typeof src !== "object" ||
        (!int(src.epoch_index, Number.MAX_SAFE_INTEGER) || src.epoch_index<1) ||
        !valid(src.at_uptime) || !Object.prototype.hasOwnProperty.call(EVENT_NAMES, src.kind)) {
      return null;
    }
    const out = {
      epoch_index: src.epoch_index,
      at_uptime: src.at_uptime, kind: src.kind
    };
    safeScalar(src, ["from","to","observation_window_seconds"], out);
    if (["pon","host","pon,host"].includes(src.channels)) {
      out.channels = src.channels;
    }
    return out;
  }
  function sanitize(src) {
    if (!src || typeof src !== "object" || src.schema !== 1 ||
        src.kind !== "aott_source_only_history" ||
        src.source_only_not_live !== true ||
        src.actual_isp_uptime_unverified !== true ||
        src.calendar_time_unverified !== true ||
        src.history_is_volatile !== true ||
        src.optics_history_unavailable !== true ||
        src.clock_domain !== "onu_monotonic_uptime" ||
        !Array.isArray(src.samples) || !Array.isArray(src.events) ||
        src.samples.length > 100 || src.events.length > 100 ||
        !src.windows || typeof src.windows !== "object") return null;
    const windows = {};
    for (const key of Object.keys(RANGE_SECONDS)) {
      windows[key] = safeWindow(src.windows[key], RANGE_SECONDS[key]);
      if (!windows[key]) return null;
    }
    const samples = src.samples.map(safeSample);
    const events = src.events.map(safeEvent);
    if (samples.some(v => !v) || events.some(v => !v)) return null;
    const epoch = samples.length ? samples[samples.length - 1].epoch_index : null;
    if (epoch !== null && samples.some(v => v.epoch_index !== epoch)) return null;
    if (epoch !== null && events.some(v => v.epoch_index !== epoch)) return null;
    for (let i=1; i<samples.length; i++) {
      if (samples[i].at_uptime <= samples[i-1].at_uptime) return null;
    }
    return {
      schema: 1, kind: "aott_source_only_history",
      source_only_not_live: true,
      actual_isp_uptime_unverified: true,
      calendar_time_unverified: true,
      history_is_volatile: true,
      optics_history_unavailable: true,
      clock_domain: "onu_monotonic_uptime",
      range: Object.prototype.hasOwnProperty.call(RANGE_SECONDS, src.range)
        ? src.range : "hour",
      windows: windows, samples: samples, events: events,
      max_export_items: 100
    };
  }
  function text(name, value) {
    const node = id(name);
    if (node) node.textContent = String(value);
  }
  function fmt(value) {
    return valid(value) ? value.toFixed(2) + " Mbps" : "Unavailable";
  }
  function uptime(value) {
    return valid(value) ? value.toFixed(1) + " s" : "Unknown";
  }
  function cell(row, value) {
    const td = document.createElement("td");
    td.textContent = String(value);
    row.appendChild(td);
  }
  function svgElement(tag, attributes, label) {
    const node = document.createElementNS(NS, tag);
    Object.keys(attributes).forEach(function (key) {
      node.setAttribute(key, String(attributes[key]));
    });
    if (label !== undefined) node.textContent = String(label);
    return node;
  }
  function rateInWindow(row, key, cutoff) {
    if (!valid(row.at_uptime) || row.at_uptime < cutoff ||
        row.status !== "valid_interval" ||
        !valid(row.elapsed_seconds, 3600) || row.elapsed_seconds === 0 ||
        row.at_uptime - row.elapsed_seconds < cutoff) return null;
    return valid(row[key]) ? row[key] : null;
  }
  function draw(samples, cutoff) {
    const chart = id("history-chart");
    chart.replaceChildren();
    const rows = samples.filter(v => v.at_uptime >= cutoff);
    const measures = [];
    ["rx_mbps","tx_mbps"].forEach(function (kind) {
      rows.forEach(function (row) {
        const rate = rateInWindow(row, kind, cutoff);
        if (rate !== null) measures.push(rate);
      });
    });
    if (!measures.length) {
      chart.setAttribute("aria-label", "No valid host Ethernet throughput intervals");
      text("chart-caption", "No measured rate intervals in this view. Missing readings are not zero traffic.");
      return;
    }
    const left = 62, right = 621, top = 20, bottom = 207;
    const tMin = rows[0].at_uptime;
    const tMax = rows[rows.length-1].at_uptime;
    const span = Math.max(1,tMax-tMin);
    const maxRate = Math.max(1,...measures);
    function pos(row,rate) {
      const x = left+(row.at_uptime-tMin)/span*(right-left);
      const y = bottom-(rate/maxRate)*(bottom-top);
      return x.toFixed(1)+","+y.toFixed(1);
    }
    for (let i=0;i<=4;i++) {
      const y = top+(bottom-top)*i/4;
      chart.appendChild(svgElement("line",{
        x1:left,y1:y,x2:right,y2:y,class:"history-grid-line"
      }));
      chart.appendChild(svgElement("text",{
        x:8,y:y+5,class:"history-grid-label"
      },((4-i)*maxRate/4).toFixed(1)));
    }
    let plotted = 0;
    ["rx_mbps","tx_mbps"].forEach(function (key) {
      const classPrefix = key==="rx_mbps" ? "history-rx" : "history-tx";
      let segment = [];
      function flush() {
        if (!segment.length) return;
        if (segment.length>1) {
          chart.appendChild(svgElement("polyline",{
            points:segment.join(" "),class:classPrefix+"-series"
          }));
        } else {
          const point=segment[0].split(",");
          chart.appendChild(svgElement("circle",{
            cx:point[0],cy:point[1],r:4,class:classPrefix+"-point"
          }));
        }
        segment=[];
      }
      rows.forEach(function (row) {
        const rate=rateInWindow(row,key,cutoff);
        if (rate===null) { flush();return; }
        segment.push(pos(row,rate));
        plotted++;
      });
      flush();
    });
    chart.setAttribute("aria-label",
      "Measured host Ethernet RX and TX rates over device uptime. " +
      plotted + " plotted values, with missing intervals left blank.");
    text("chart-caption", plotted+
      " plotted rate readings from at most 100 retained samples. Gaps are not connected.");
  }
  function viewSamples(samples,cutoff) {
    const rows = id("history-sample-rows");
    rows.replaceChildren();
    const eligible=samples.filter(v => v.at_uptime>=cutoff).slice(-25);
    if (!eligible.length) {
      const tr=document.createElement("tr");
      const td=document.createElement("td");
      td.colSpan=5;td.textContent="No samples retained for this range";
      tr.appendChild(td);rows.appendChild(tr);return;
    }
    eligible.slice().reverse().forEach(function (item) {
      const tr=document.createElement("tr");
      cell(tr,uptime(item.at_uptime));
      cell(tr,item.pon_observation==="observed" && int(item.pon_state,255)
        ? "State "+item.pon_state : "Unavailable");
      cell(tr,item.host_link_observation==="observed" &&
           int(item.host_link_speed_mbps,100000)
        ? item.host_link_speed_mbps+" Mbps" : "Unavailable");
      const rx=rateInWindow(item,"rx_mbps",cutoff);
      const tx=rateInWindow(item,"tx_mbps",cutoff);
      cell(tr,rx===null ? "Unavailable" : rx.toFixed(2));
      cell(tr,tx===null ? "Unavailable" : tx.toFixed(2));
      rows.appendChild(tr);
    });
  }
  function viewEvents(events,cutoff) {
    const table=id("history-event-rows");
    table.replaceChildren();
    const shown=events.filter(v => v.at_uptime>=cutoff).slice(-25);
    if (!shown.length) {
      const tr=document.createElement("tr");
      const td=document.createElement("td");
      td.colSpan=3;td.textContent="No recorded state changes in this view";
      tr.appendChild(td);table.appendChild(tr);return;
    }
    shown.slice().reverse().forEach(function (entry) {
      const tr=document.createElement("tr");
      cell(tr,uptime(entry.at_uptime));
      cell(tr,EVENT_NAMES[entry.kind]);
      let detail="Sampled observation only";
      if (valid(entry.from) && valid(entry.to)) {
        detail="State "+entry.from+" to "+entry.to;
      } else if (entry.channels) {
        detail="Unavailable: "+entry.channels;
      }
      if (valid(entry.observation_window_seconds)) {
        detail+=" (within "+entry.observation_window_seconds+" s sampled window)";
      }
      cell(tr,detail);
      table.appendChild(tr);
    });
  }
  function setRange(name) {
    if (!current || !Object.prototype.hasOwnProperty.call(RANGE_SECONDS,name)) return false;
    const range=current.windows[name];
    if (!range) return false;
    activeRange=name;
    id("history-range").value=name;
    const cutoff=valid(range.latest_uptime)
      ? Math.max(0,range.latest_uptime-RANGE_SECONDS[name]) : 0;
    text("pon-state",range.pon_observation==="observed" && int(range.pon_state,255)
      ? range.pon_state===51 ? "O5.1 associated" : "PON state "+range.pon_state
      : "Unavailable");
    text("host-state",range.host_link_observation==="observed" &&
      int(range.host_link_speed_mbps,100000)
      ? range.host_link_speed_mbps+" Mbps host speed" : "Unavailable");
    text("wan-state","Not verified");
    text("optics-state","Not collected");
    text("rx-average",fmt(range.rx.average_mbps));
    text("rx-peak",fmt(range.rx.peak_mbps));
    text("tx-average",fmt(range.tx.average_mbps));
    text("tx-peak",fmt(range.tx.peak_mbps));
    function percent(x) {
      return valid(x,1) ? (x*100).toFixed(2)+"%" : "0.00%";
    }
    text("coverage-message",
      "Measured RX coverage "+percent(range.rx.coverage_fraction)+
      ", TX coverage "+percent(range.tx.coverage_fraction)+
      " of the requested period. "+
      (range.terminated_at_epoch_boundary ? "History stops at a reboot, link source change, or long gap. " : "")+
      "The full requested time range is not verified.");
    draw(current.samples,cutoff);
    viewSamples(current.samples,cutoff);
    viewEvents(current.events,cutoff);
    return true;
  }
  function validProjection(payload) {
    return sanitize(payload);
  }
  function render(payload) {
    const clean=validProjection(payload);
    if (!clean) {
      current=null;
      id("history-json").disabled=true;
      id("history-csv").disabled=true;
      text("history-export-status","Invalid or unauthenticated source projection; no data displayed.");
      ["pon-state","host-state","rx-average","rx-peak","tx-average","tx-peak"].forEach(function (name) {
        text(name,"Unavailable");
      });
      text("wan-state","Not verified");
      text("optics-state","Not collected");
      text("chart-caption","No validated history data is loaded.");
      text("coverage-message","No measured history has been loaded.");
      id("history-chart").replaceChildren();
      id("history-sample-rows").replaceChildren();
      id("history-event-rows").replaceChildren();
      return false;
    }
    current=clean;
    id("history-json").disabled=false;
    id("history-csv").disabled=false;
    text("history-export-status","Export is ready. Data is source-only and not live.");
    setRange(clean.range);
    return true;
  }
  function quote(value) {
    if (value===undefined || value===null) return "";
    let s=String(value);
    if (/^[=+\-@]/.test(s)) s="'"+s;
    return '"'+s.replace(/"/g,'""')+'"';
  }
  function toCSV() {
    if (!current) return null;
    const range=current.windows[activeRange];
    const cutoff=valid(range.latest_uptime)
      ? Math.max(0,range.latest_uptime-RANGE_SECONDS[activeRange]) : 0;
    const columns=[
      "record_type","at_uptime","source","status","pon_state",
      "host_link_speed_mbps","rx_mbps","tx_mbps","event_kind","from","to",
      "observation_window_seconds"
    ];
    const lines=[columns.join(",")];
    current.samples.filter(v => v.at_uptime>=cutoff).forEach(function (v) {
      const rx=rateInWindow(v,"rx_mbps",cutoff);
      const tx=rateInWindow(v,"tx_mbps",cutoff);
      lines.push(["sample",v.at_uptime,v.source,v.status,
        v.pon_state,v.host_link_speed_mbps,rx,tx,"","","",""].map(quote).join(","));
    });
    current.events.filter(v => v.at_uptime>=cutoff).forEach(function (v) {
      lines.push(["event",v.at_uptime,"","","","","","",v.kind,
        v.from,v.to,v.observation_window_seconds].map(quote).join(","));
    });
    const result=lines.join("\r\n")+"\r\n";
    return result.length<=65536 ? result : null;
  }
  function toJSON() {
    if (!current) return null;
    const value=JSON.stringify(current);
    return value.length<=65536 ? value : null;
  }
  function download(filename,content,mime) {
    if (!current || content===null) return false;
    const blob=new Blob([content],{type:mime});
    const url=URL.createObjectURL(blob);
    const anchor=document.createElement("a");
    anchor.href=url;anchor.download=filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    text("history-export-status",
      "Prepared "+filename+" from bounded source-only data.");
    return true;
  }
  function initialize() {
    id("history-range").addEventListener("change",function (event) {
      setRange(event.target.value);
    });
    id("history-theme").addEventListener("change",function (event) {
      if (event.target.value==="dark" || event.target.value==="light") {
        documentRoot.setAttribute("data-aott-theme",event.target.value);
      }
    });
    id("history-json").addEventListener("click",function () {
      download("aott-history-"+activeRange+".json",toJSON(),"application/json");
    });
    id("history-csv").addEventListener("click",function () {
      download("aott-history-"+activeRange+".csv",toCSV(),"text/csv;charset=utf-8");
    });
  }
  window.AoTTHistoryView={
    render:render,
    setRange:setRange,
    exportJSON:toJSON,
    exportCSV:toCSV,
    sourceOnly:true
  };
  if (document.readyState==="loading") {
    document.addEventListener("DOMContentLoaded",initialize,{once:true});
  } else initialize();
})();

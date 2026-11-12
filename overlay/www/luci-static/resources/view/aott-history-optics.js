/* AoTT-8311 V3r4: optional, strictly redacted RAM-only optical history.
 * Browser display only. No HTTP requests, timers, device writes or storage.
 * Receives exclusively prevalidated numeric samples from aott-history.js.
 */
(function () {
  "use strict";
  const NS="http://www.w3.org/2000/svg";
  const RANGES={
    rx_power_dbm:[-45,15],tx_power_dbm:[-45,15],
    optic_temp_c:[-40,110],module_voltage_v:[2,4],
    tx_bias_ma:[0,200],cpu0_temp_c:[-35,130],
    cpu1_temp_c:[-35,130]
  };
  const KEYS=Object.keys(RANGES);
  const ids=["optical-rx","optical-tx","optical-temp","optical-cpu",
             "optical-rx-low","optical-temp-high"];
  function byId(name) {return document.getElementById(name);}
  function write(name,value) {
    const element=byId(name);
    if (element) element.textContent=String(value);
  }
  function valid(value,key) {
    const bounds=RANGES[key];
    return bounds && typeof value==="number" &&
      Number.isFinite(value) && value>=bounds[0] && value<=bounds[1];
  }
  function format(value,key,unit) {
    return valid(value,key) ? value.toFixed(2)+unit : "Unavailable";
  }
  function svg(tag,attrs) {
    const element=document.createElementNS(NS,tag);
    for (const [key,value] of Object.entries(attrs)) {
      element.setAttribute(key,String(value));
    }
    return element;
  }
  function draw(chartId,rows,key,unit) {
    const chart=byId(chartId);
    if (!chart) return;
    chart.replaceChildren();
    const measured=rows.filter(point=>valid(point[key],key));
    if (!measured.length) {
      chart.setAttribute("aria-label","No validated "+key+" observations");
      return;
    }
    const min=Math.min(...measured.map(p=>p[key]));
    const max=Math.max(...measured.map(p=>p[key]));
    const pad=Math.max((max-min)*0.15,1.0);
    const bottom=min-pad,top=max+pad;
    const start=rows[0].at_uptime,end=rows[rows.length-1].at_uptime;
    const x=point=>20+600*(point.at_uptime-start)/Math.max(1,end-start);
    const y=point=>130-110*(point[key]-bottom)/Math.max(1,top-bottom);
    let segment=[],previous=null;
    function flush() {
      if (!segment.length) return;
      if (segment.length>1) {
        const points=segment.map(p=>x(p).toFixed(2)+","+
            y(p).toFixed(2)).join(" ");
        chart.appendChild(svg("polyline",{
          points,fill:"none",stroke:"var(--rx, #3187c2)",
          "stroke-width":2.5,"stroke-linecap":"round"
        }));
      }
      for (const point of segment) {
        chart.appendChild(svg("circle",{
          cx:x(point).toFixed(2),cy:y(point).toFixed(2),
          r:2.8,fill:"var(--rx, #3187c2)"
        }));
      }
      segment=[];
    }
    for (const point of rows) {
      if (!valid(point[key],key)) {
        if (point.optical_observation==="unavailable") {
          flush();
          previous=null;
        }
        continue;
      }
      if (previous && point.at_uptime-previous.at_uptime>600) flush();
      segment.push(point);
      previous=point;
    }
    flush();
    chart.setAttribute("aria-label",measured.length+" validated "+key+
      " readings, minimum "+min.toFixed(2)+unit+
      ", maximum "+max.toFixed(2)+unit+
      "; missing observations are not interpolated");
  }
  function tableCell(row,value) {
    const td=document.createElement("td");
    td.textContent=String(value);
    row.appendChild(td);
    return td;
  }
  function clear() {
    for (const id of ids) write(id,"Unavailable");
    write("optics-state","Not collected");
    write("optical-coverage","No validated optical measurements loaded.");
    for (const id of ["history-optical-rx-chart","history-optical-temp-chart",
                      "history-optical-rows"]) {
      const element=byId(id);
      if (element) element.replaceChildren();
    }
  }
  function render(samples,cutoff) {
    if (!Array.isArray(samples) || samples.length>100 ||
        typeof cutoff!=="number" || !Number.isFinite(cutoff) || cutoff<0) {
      clear();return false;
    }
    const rows=samples.filter(row=>row && Number.isFinite(row.at_uptime) &&
      row.at_uptime>=cutoff);
    const attempted=rows.filter(row=>row.optical_observation==="observed" ||
      row.optical_observation==="unavailable");
    const measured=attempted.filter(row=>row.optical_observation==="observed" &&
      KEYS.some(key=>valid(row[key],key)));
    const actual=measured.filter(row=>valid(row.rx_power_dbm,"rx_power_dbm") ||
      valid(row.tx_power_dbm,"tx_power_dbm") ||
      valid(row.optic_temp_c,"optic_temp_c"));
    const latest=key=>[...measured].reverse().find(v=>valid(v[key],key));
    const rx=latest("rx_power_dbm"),tx=latest("tx_power_dbm");
    const temp=latest("optic_temp_c");
    const cpu=[...measured].reverse().find(v=>
      valid(v.cpu0_temp_c,"cpu0_temp_c") ||
      valid(v.cpu1_temp_c,"cpu1_temp_c"));
    const cpuKey=cpu && valid(cpu.cpu0_temp_c,"cpu0_temp_c")
      ? "cpu0_temp_c":"cpu1_temp_c";
    write("optical-rx",rx?format(rx.rx_power_dbm,"rx_power_dbm"," dBm"):"Unavailable");
    write("optical-tx",tx?format(tx.tx_power_dbm,"tx_power_dbm"," dBm"):"Unavailable");
    write("optical-temp",temp?format(temp.optic_temp_c,"optic_temp_c"," °C"):"Unavailable");
    write("optical-cpu",cpu?format(cpu[cpuKey],cpuKey," °C"):"Unavailable");
    const powers=measured.filter(v=>valid(v.rx_power_dbm,"rx_power_dbm"))
      .map(v=>v.rx_power_dbm);
    const temperatures=measured.filter(v=>valid(v.optic_temp_c,"optic_temp_c"))
      .map(v=>v.optic_temp_c);
    write("optical-rx-low",powers.length
      ? Math.min(...powers).toFixed(2)+" dBm":"Unavailable");
    write("optical-temp-high",temperatures.length
      ? Math.max(...temperatures).toFixed(2)+" °C":"Unavailable");
    const lastTime=measured.length
      ? measured[measured.length-1].at_uptime.toFixed(1)+" s ONU uptime"
      : "unavailable";
    write("optics-state",actual.length
      ? actual.length+" retained optical sample(s)"
      : attempted.length?"Optical measurement unavailable":"Not collected in this view");
    write("optical-coverage",attempted.length+" attempted sample(s), "+
      actual.length+" with actual optical power or module temperature, "+
      (attempted.length-measured.length)+" without usable sensor values. "+
      "Latest source measurement at "+lastTime+
      ". Partial RAM-only evidence, not continuous ISP availability.");
    draw("history-optical-rx-chart",rows,"rx_power_dbm"," dBm");
    draw("history-optical-temp-chart",rows,"optic_temp_c"," °C");
    const tbody=byId("history-optical-rows");
    if (tbody) {
      tbody.replaceChildren();
      if (!attempted.length) {
        const tr=document.createElement("tr");
        tableCell(tr,"No optical observations retained for this range").colSpan=8;
        tbody.appendChild(tr);
      } else {
        for (const item of [...attempted].slice(-25).reverse()) {
          const tr=document.createElement("tr");
          tableCell(tr,item.at_uptime.toFixed(1)+" s");
          for (const [key,unit] of [
            ["rx_power_dbm"," dBm"],["tx_power_dbm"," dBm"],
            ["optic_temp_c"," °C"],["cpu0_temp_c"," °C"],
            ["cpu1_temp_c"," °C"],["tx_bias_ma"," mA"],
            ["module_voltage_v"," V"]
          ]) {
            tableCell(tr,format(item[key],key,unit));
          }
          tbody.appendChild(tr);
        }
      }
    }
    return true;
  }
  window.AoTTOpticalHistory={render,clear};
})();

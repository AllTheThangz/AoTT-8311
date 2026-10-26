/* AoTT-8311-v2r1: small, read-only browser client for trusted LuCI data. */
(function() {
    "use strict";
    var base = "/cgi-bin/luci/admin/8311/";
    var previous = null;
    var timer = null;
    var running = false;
    var intervals = {"0":true,"15000":true,"30000":true,"60000":true};
    var locale = (typeof Intl === "object" && Intl.NumberFormat) ? new Intl.NumberFormat() : null;

    function node(id) { return document.getElementById(id); }
    function put(id, text) {
        var el = node(id);
        if (el) el.textContent = text == null ? "Unavailable" : String(text);
    }
    function formatNumber(value, places) {
        if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
        if (places != null) return value.toFixed(places);
        return locale ? locale.format(value) : String(value);
    }
    function field(value, display) {
        if (value == null) return "Unavailable";
        return display == null ? String(value) : display;
    }
    function clear(el) {
        if (!el) return;
        while (el.firstChild) el.removeChild(el.firstChild);
    }
    function add(parent, tag, value, className) {
        var element = document.createElement(tag);
        if (value != null) element.textContent = String(value);
        if (className) element.className = className;
        parent.appendChild(element);
        return element;
    }
    function showError(id, message) {
        var el = node(id);
        if (el) {
            el.textContent = message;
            el.setAttribute("data-state","error");
        }
    }
    function showOk(id, message) {
        var el = node(id);
        if (el) {
            el.textContent = message;
            el.setAttribute("data-state","ok");
        }
    }
    async function fetchJSON(path) {
        var response = await fetch(base + path, {cache:"no-store",credentials:"same-origin"});
        if (!response.ok) {
            throw new Error("Status HTTP " + response.status + ". Reload after verifying management access.");
        }
        var record = await response.json();
        if (!record || record.schema !== 1 || record.success === false) {
            throw new Error("The device returned an incomplete status snapshot.");
        }
        return record;
    }
    function delta(current,old) {
        if (typeof current !== "number" || !Number.isFinite(current) ||
            typeof old !== "number" || !Number.isFinite(old)) return null;
        return (current >= old) ? current-old : null;
    }
    function macRows(snapshot) {
        var body = node("aott-r5-mac-body");
        if (!body) return;
        clear(body);
        var records = snapshot.counters || {};
        var prior = previous && previous.counters || {};
        var rows = [
            ["RxFCSErrorPkts", "Bad Ethernet FCS", "A rising count suggests Ethernet corruption."],
            ["RxDroppedPkts", "Ethernet received drops", "New receive drops require investigating host queues."],
            ["TxDroppedPkts", "Ethernet transmitted drops", "New transmit drops require investigating device queues."],
            ["TxAcmDroppedPkts", "ACM traffic-manager drops", "Compare increases, not the historical total alone."],
            ["RxOverflowError", "Receive overflow errors", "New overflow errors can indicate resource pressure."],
            ["RxExtendedVlanDiscardPkts", "Extended VLAN discards", "New discards may indicate provisioned mapping or policy changes."],
            ["MtuExceedDiscardPkts", "MTU discards", "New discards may indicate frames exceeding a hardware limit."],
            ["RxGoodPkts", "Valid received frames", "Expected to increase while traffic flows."],
            ["TxGoodPkts", "Valid transmitted frames", "Expected to increase while traffic flows."]
        ];
        rows.forEach(function(row) {
            var current = records[row[0]];
            var priorValue = prior[row[0]];
            var valid = delta(current,priorValue);
            var haveBoth = !!previous && valid !== null &&
                snapshot.uptime_seconds > previous.uptime_seconds;
            var tr = document.createElement("tr");
            add(tr,"th",row[1]);
            add(tr,"td",formatNumber(current));
            var diffCell = add(tr,"td",haveBoth ? "+"+formatNumber(valid) :
                (previous && current < priorValue ? "Counter reset" : "Need two samples"));
            var isErrorCounter = row[0] !== "RxGoodPkts" && row[0] !== "TxGoodPkts";
            if (isErrorCounter && haveBoth && valid > 0) {
                diffCell.setAttribute("data-counter","new");
            }
            add(tr,"td",row[2]);
            body.appendChild(tr);
        });
    }
    function gemRows(snapshot) {
        var body = node("aott-r5-gem-body");
        if (!body) return;
        clear(body);
        var items = Array.isArray(snapshot.gem_ports) ? snapshot.gem_ports : [];
        if (!items.length) {
            var empty = document.createElement("tr");
            var cell = add(empty,"td","GEM data is temporarily unavailable; no ports were inferred.");
            cell.colSpan=8;
            body.appendChild(empty);
            return;
        }
        items.slice(0,32).forEach(function(item) {
            var tr=document.createElement("tr");
            add(tr,"th",item.gem_id == null ? "Unavailable" : String(item.gem_id));
            add(tr,"td",field(item.service));
            add(tr,"td",item.alloc_id == null ? "None reported" : String(item.alloc_id));
            add(tr,"td",field(item.direction).trim());
            add(tr,"td",field(item.encryption_label));
            var c=item.counters || {};
            add(tr,"td",formatNumber(c.us_packets));
            add(tr,"td",formatNumber(c.ds_packets));
            var error = add(tr,"td",formatNumber(c.key_errors));
            if (c.key_errors > 0) error.setAttribute("data-counter","new");
            body.appendChild(tr);
        });
    }
    function updateRates(snapshot) {
        var now = snapshot.counters || {};
        var old = previous && previous.counters || {};
        var seconds = previous && snapshot.uptime_seconds - previous.uptime_seconds;
        var rx = delta(now.RxGoodBytes, old.RxGoodBytes);
        var tx = delta(now.TxGoodBytes, old.TxGoodBytes);
        if (seconds && seconds > 0 && seconds < 300 &&
            rx !== null && tx !== null) {
            put("aott-r5-upload",formatNumber(rx*8/seconds/1e6,2)+" Mbps");
            put("aott-r5-download",formatNumber(tx*8/seconds/1e6,2)+" Mbps");
            put("aott-r5-rate-notes","Two valid samples over "+
                formatNumber(seconds,1)+" seconds; ONU Ethernet MAC transfer estimates.");
        } else {
            put("aott-r5-upload","Collecting baseline…");
            put("aott-r5-download","Collecting baseline…");
            put("aott-r5-rate-notes","Another sample is needed or a counter reset occurred. No rate was inferred.");
        }
    }
    function paintTelemetry(snapshot) {
        var optics=snapshot.optics || {};
        put("aott-r5-pon",optics.ploam_state===51 ? "O5.1 · Associated" :
            (optics.ploam_state == null ? "Unavailable" : "State " + formatNumber(optics.ploam_state)));
        put("aott-r5-eth",snapshot.eth_speed_mbps>0 ?
            formatNumber(snapshot.eth_speed_mbps/1000,1)+" Gbps" : "Unavailable");
        put("aott-r5-rx-dbm",formatNumber(optics.rx_power_dBm,2));
        put("aott-r5-tx-dbm",formatNumber(optics.tx_power_dBm,2));
        put("aott-r5-optic-temp",formatNumber(optics.optic_tempC,1));
        put("aott-r5-cpu-temp",formatNumber(optics.cpu1_tempC,1)+" / "+
            formatNumber(optics.cpu2_tempC,1));
        put("aott-r5-voltage",formatNumber(optics.module_voltage,3));
        put("aott-r5-tx-bias",formatNumber(optics.tx_bias_mA,1));
        macRows(snapshot);
        gemRows(snapshot);
        updateRates(snapshot);
        previous = snapshot;
        put("aott-r5-last-sample","Sampled "+new Date(snapshot.sampled_at*1000).toLocaleTimeString());
        showOk("aott-r5-load-status","Live counters read successfully. "+
            ((snapshot.counters && snapshot.gem_ports) ?
            "MAC and GEM data are available." : "Some counter sources are unavailable."));
    }
    async function refreshTelemetry() {
        if (running || !node("aott-r5-load-status")) return;
        running=true;
        var refresh=node("aott-r5-refresh");
        if (refresh) refresh.disabled=true;
        try {
            var data=await fetchJSON("health_data");
            paintTelemetry(data);
        } catch(error) {
            showError("aott-r5-load-status","Telemetry request failed: "+error.message+
                " Existing readings are historical until a fresh sample succeeds.");
        } finally {
            running=false;
            if (refresh) refresh.disabled=false;
        }
    }
    function schedule() {
        if (timer) {clearInterval(timer);timer=null;}
        var select=node("aott-r5-interval");
        if (!select) return;
        var interval=String(select.value);
        if (!intervals[interval]) {interval="30000";select.value=interval;}
        try {localStorage.setItem("aott-8311-v2r1-interval",interval);} catch(_) {}
        if (Number(interval)>0) {
            timer=setInterval(function() {
                if (document.visibilityState !== "hidden") refreshTelemetry();
            },Number(interval));
        }
    }
    function setupTelemetry() {
        if (!node("aott-r5-refresh")) return;
        var select=node("aott-r5-interval");
        try {
            var preference=localStorage.getItem("aott-8311-v2r1-interval");
            if (intervals[preference]) select.value=preference;
        } catch(_) {}
        select.addEventListener("change",schedule);
        node("aott-r5-refresh").addEventListener("click",refreshTelemetry);
        window.addEventListener("pagehide",function(){if(timer)clearInterval(timer);timer=null;});
        schedule();
        refreshTelemetry();
    }

    function renderFindings(list) {
        var div=node("aott-r5-security-findings");
        if (!div) return;
        clear(div);
        if (!Array.isArray(list)) {
            add(div,"p","Security status unavailable; no findings were inferred.");
            return;
        }
        if (!list.length) {
            add(div,"p","No configured warnings were returned. This is not a full vulnerability scan.");
            return;
        }
        list.slice(0,24).forEach(function(f) {
            var card=add(div,"div",null,"aott-r5-finding");
            var severity=f.severity==="critical" ? "critical" : "warning";
            card.setAttribute("data-severity",severity);
            add(card,"strong",severity==="critical" ? "Critical finding" : "Review recommended");
            add(card,"p",String(f.message || "A configuration check requires attention."));
        });
    }
    function human(value) {
        var names={
            not_set:"Not configured",
            configured:"Configured",
            invalid:"Invalid saved hash",
            locked:"Locked",
            enabled:"Enabled",
            disabled:"Disabled",
            unknown:"Unknown"
        };
        return Object.prototype.hasOwnProperty.call(names,value) ?
            names[value] : (value == null ? "Unavailable" : String(value));
    }
    function showSecurity(data) {
        put("aott-r5-root-password",human(data.root_password));
        put("aott-r5-root-persistence",human(data.root_password_persistence));
        put("aott-r5-ssh-password",human(data.ssh_password_authentication));
        put("aott-r5-ssh-root-password",human(data.ssh_root_password_authentication));
        put("aott-r5-ssh-keys",data.ssh_authorized_keys_present ? "Key file present" : "No key file detected");
        put("aott-r5-ssh-interface",field(data.ssh_direct_interface));
        put("aott-r5-https-redirect",human(data.http_redirect));
        put("aott-r5-management-ip",field(data.management_address));
        put("aott-r5-management-gateway",field(data.management_gateway));
        put("aott-r5-http-listeners",Array.isArray(data.http_listeners) ?
            data.http_listeners.join("\n") : "Unavailable");
        put("aott-r5-https-listeners",Array.isArray(data.https_listeners) ?
            data.https_listeners.join("\n") : "Unavailable");
        renderFindings(data.warnings);
        put("aott-r5-security-updated","Checked "+new Date(data.sampled_at*1000).toLocaleTimeString());
        showOk("aott-r5-security-status","Read-only security audit complete. "+
            (Array.isArray(data.warnings) ? data.warnings.length : "Unknown number of")+
            " configuration findings.");
    }
    async function refreshSecurity() {
        var b=node("aott-r5-security-refresh");
        if (!b) return;
        b.disabled=true;
        try {showSecurity(await fetchJSON("security_data"));}
        catch(error) {showError("aott-r5-security-status","Security check failed: "+error.message);}
        finally {b.disabled=false;}
    }
    function setupSecurity() {
        var b=node("aott-r5-security-refresh");
        if (!b) return;
        b.addEventListener("click",refreshSecurity);
        refreshSecurity();
    }
    function startup() {
        setupTelemetry();
        setupSecurity();
    }
    if (document.readyState==="loading") {
        document.addEventListener("DOMContentLoaded",startup,{once:true});
    } else startup();
})();

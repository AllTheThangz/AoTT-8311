/* AoTT-8311 H-026: explicit, same-origin authenticated history load.
 * SOURCE-ONLY. This adapter is not referenced by the deployed LuCI HTML
 * and never fetches automatically. A separate authenticated route must
 * be qualified before it can be integrated into the residential GUI.
 */
(function () {
  "use strict";
  const ROUTE="/admin/8311/history_data";
  const MAX_BYTES=65536;
  let pending=false;

  function update(message) {
    const notice=document.getElementById("prototype-notice");
    if (notice) notice.textContent=message;
  }
  function rejected(message) {
    // Clear previous source data and disable exports on session expiration
    // or any invalid cached response. Never retain old visible history.
    if (window.AoTTHistoryView &&
        typeof window.AoTTHistoryView.render==="function") {
      window.AoTTHistoryView.render(null);
    }
    update(message);
    return {loaded:false,sourceOnly:true,liveHardwareVerified:false};
  }
  async function boundedText(response) {
    if (!response.body || typeof response.body.getReader!=="function") {
      throw new Error("stream_unavailable");
    }
    const reader=response.body.getReader();
    const decoder=new TextDecoder("utf-8",{fatal:true});
    let received=0;
    let output="";
    for (;;) {
      const next=await reader.read();
      if (next.done) break;
      received+=next.value.byteLength;
      if (received>MAX_BYTES) {
        await reader.cancel();
        throw new Error("response_too_large");
      }
      output+=decoder.decode(next.value,{stream:true});
    }
    output+=decoder.decode();
    if (received<2) throw new Error("response_empty");
    return output;
  }
  async function load() {
    if (pending) return rejected("A history request is already running.");
    if (!window.AoTTHistoryView ||
        typeof window.AoTTHistoryView.render!=="function" ||
        window.AoTTHistoryView.sourceOnly!==true) {
      return rejected("The bounded history viewer is unavailable.");
    }
    pending=true;
    const abort=new AbortController();
    const deadline=setTimeout(function () { abort.abort(); },7000);
    try {
      const response=await fetch(ROUTE,{
        method:"GET",
        credentials:"same-origin",
        cache:"no-store",
        redirect:"error",
        signal:abort.signal,
        headers:{"Accept":"application/json"}
      });
      const url=new URL(response.url);
      if (url.origin!==location.origin || url.pathname!==ROUTE ||
          response.status!==200 || !response.ok ||
          !/^application\/json(?:\s*;|$)/i.test(
            response.headers.get("content-type")||"")) {
        return rejected("Authenticated source history is unavailable.");
      }
      const length=response.headers.get("content-length");
      if (length!==null && (!/^\d+$/.test(length) ||
          Number(length)>MAX_BYTES)) {
        return rejected("The history response exceeds the safe size.");
      }
      const content=await boundedText(response);
      let payload;
      try {
        payload=JSON.parse(content);
      } catch (_error) {
        return rejected("The history response is invalid.");
      }
      if (!payload || payload.schema!==1 ||
          payload.source_only_not_live!==true ||
          payload.actual_isp_uptime_unverified!==true ||
          payload.history_is_volatile!==true ||
          payload.no_firmware_or_device_write!==true ||
          payload.calendar_time_unverified!==true ||
          !window.AoTTHistoryView.render(payload)) {
        return rejected("The history response failed validation.");
      }
      update("Source-only cached observations. Device uptime, not verified calendar time. PON and Ethernet states do not prove Internet availability.");
      return {
        loaded:true,
        sourceOnly:true,
        liveHardwareVerified:false,
        requestPath:ROUTE,
        noLiveProbesStarted:true,
      };
    } catch (_error) {
      return rejected("Authenticated source history is unavailable.");
    } finally {
      clearTimeout(deadline);
      pending=false;
    }
  }
  window.AoTTHistoryAdminPreview={
    load:load,
    sourceOnly:true,
    autoFetch:false,
    endpointInstalled:false,
  };
})();

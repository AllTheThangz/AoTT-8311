#!/usr/bin/env python3
"""AoTT P0 read-only residential ONU soak, run from a trusted management host.

No device writes, no load traffic, no PON identity, MAC, IP, password or secret
data in output. Stores JSONL only on the *host*. Do not infer real Internet
reachability from O5 or Ethernet carrier.
"""
from pathlib import Path
import argparse,datetime,json,os,re,subprocess,sys,time

REMOTE=r"""
LC_ALL=C
printf 'uptime='; cut -d ' ' -f1 /proc/uptime
printf 'speed='; cat /sys/class/net/eth0_0/speed
printf 'carrier='; cat /sys/class/net/eth0_0/carrier
for item in rx_errors tx_errors rx_dropped tx_dropped; do
 printf "$item="; cat /sys/class/net/eth0_0/statistics/$item
done
printf 'thermal0='; cat /sys/class/thermal/thermal_zone0/temp
printf 'thermal1='; cat /sys/class/thermal/thermal_zone1/temp
printf 'available_kb='; awk '/^MemAvailable:/ {print $2;found=1;exit} END {if(!found) print ""}' /proc/meminfo
printf 'pon_state='
/usr/bin/timeout -k 1 3 /usr/bin/pon psg 2>/dev/null |
  grep -o 'current=[0-9]*' | head -1 | cut -d '=' -f2
# All UBI values come from the kernel sysfs and are read-only. Missing
# attributes are returned as empty fields, never fabricated zeros.
for item in bad_peb_count max_ec reserved_for_bad avail_eraseblocks; do
  value=$(cat "/sys/class/ubi/ubi0/$item" 2>/dev/null) || value=
  printf 'ubi_%s=%s\n' "$item" "$value"
done
"""
COLUMNS={"uptime","speed","carrier","rx_errors","tx_errors","rx_dropped",
         "tx_dropped","thermal0","thermal1","available_kb","pon_state",
         "ubi_bad_peb_count","ubi_max_ec","ubi_reserved_for_bad","ubi_avail_eraseblocks"}
INTEGERS=COLUMNS-{"uptime"}
def decode(raw):
    if len(raw)>4096:raise ValueError("output_too_large")
    values={}
    for line in raw.splitlines():
        if not line:continue
        k,sep,v=line.partition("=")
        if sep!="=" or k not in COLUMNS or k in values:
            raise ValueError("unknown_or_duplicate_probe_field")
        if v=="":
            values[k]=None
        elif k=="uptime" and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,4})?",v):
            values[k]=float(v)
        elif k in INTEGERS and re.fullmatch(r"[0-9]{1,19}",v):
            values[k]=int(v)
        else:raise ValueError("invalid_probe_value")
    if set(values)!=COLUMNS or not isinstance(values["uptime"],float):
        raise ValueError("incomplete_probe")
    return values

def sample(target):
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,180}",target) or target.startswith("-"):
        raise ValueError("invalid_target")
    cmd=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
         "-o","PasswordAuthentication=no","-o","ConnectTimeout=7",target,REMOTE]
    p=subprocess.run(cmd,text=True,capture_output=True,timeout=15,check=False)
    if p.returncode:raise ValueError("ssh_probe_unavailable")
    return decode(p.stdout)

def analyze(records):
    good=[r for r in records if r["state"]=="observed"]
    lost=sum(r["state"]!="observed" for r in records)
    reboot=0; pon_changes=0; link_changes=0; bad_peb_growth=0; errors={k:0 for k in
          ("rx_errors","tx_errors","rx_dropped","tx_dropped")}
    for prev,cur in zip(good,good[1:]):
        a,b=prev["metrics"],cur["metrics"]
        if b["uptime"]<a["uptime"]:
            reboot+=1
            continue
        if a["pon_state"] is not None and b["pon_state"] is not None:
            pon_changes+=a["pon_state"]!=b["pon_state"]
        if a["carrier"] is not None and b["carrier"] is not None:
            link_changes+=a["carrier"]!=b["carrier"]
        for k in errors:
            if a[k] is not None and b[k] is not None and b[k]>=a[k]:
                errors[k]+=b[k]-a[k]
        if a["ubi_bad_peb_count"] is not None and b["ubi_bad_peb_count"] is not None:
            bad_peb_growth+=max(0,b["ubi_bad_peb_count"]-a["ubi_bad_peb_count"])
    return {"samples_total":len(records),"observed":len(good),
            "probe_gaps":lost,"reboots_observed":reboot,
            "pon_state_transitions_observed":pon_changes,
            "carrier_transitions_observed":link_changes,
            "ethernet_error_drop_deltas":errors,
            "ubi_bad_peb_growth_observed":bad_peb_growth,
            "ubi_peak_erase_count_observed":max(
                (r["metrics"]["ubi_max_ec"] for r in good if
                 r["metrics"]["ubi_max_ec"] is not None),default=None),
            "ubi_min_available_eraseblocks_observed":min(
                (r["metrics"]["ubi_avail_eraseblocks"] for r in good if
                 r["metrics"]["ubi_avail_eraseblocks"] is not None),default=None),
            "ubi_bad_peb_samples_unavailable":sum(
                r["metrics"]["ubi_bad_peb_count"] is None for r in good),
            "peak_thermal_c":[(round(v/1000,2) if v is not None else None)
                for v in (max((r["metrics"][k] for r in good if r["metrics"][k] is not None),default=None)
                for k in ("thermal0","thermal1"))],
            "three_layer_internet_verified":False,
            "sampling_is_not_continuous":True}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target",required=True,help="SSH destination, never logged")
    ap.add_argument("--output",required=True,type=Path,help="new, private off-device JSONL")
    ap.add_argument("--interval-seconds",type=int,default=60)
    ap.add_argument("--samples",type=int,default=3)
    a=ap.parse_args()
    if not 10<=a.interval_seconds<=3600 or not 2<=a.samples<=10081:
        ap.error("interval 10..3600 seconds, samples 2..10081")
    if a.output.exists() or a.output.is_symlink():
        ap.error("output must be an unused private file")
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    records=[];start=time.monotonic()
    with os.fdopen(fd,"w") as f:
        for i in range(a.samples):
            row={"seq":i,"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "state":"observed"}
            try:row["metrics"]=sample(a.target)
            except (ValueError,OSError,subprocess.TimeoutExpired) as e:
                row["state"]="unavailable";row["reason"]=str(e)[:64]
            records.append(row)
            f.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n");f.flush()
            if i+1<a.samples:
                delta=start+(i+1)*a.interval_seconds-time.monotonic()
                if delta>0:time.sleep(delta)
        report={"status":"P0_PASSIVE_SOAK_CAPTURE_COMPLETE","sample_interval_seconds":a.interval_seconds,
                "samples_requested":a.samples,
                "summary":analyze(records),"device_changed":False}
        f.write(json.dumps(report,sort_keys=True,separators=(",",":"))+"\n")
        f.flush();os.fsync(f.fileno())
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__":main()

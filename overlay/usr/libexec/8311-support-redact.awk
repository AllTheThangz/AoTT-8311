# BusyBox-compatible privacy filter for default AoTT support archives.
# Raw captures stay inside the private staging directory. Never use this
# filter as a substitute for refusing to collect actual secrets.
BEGIN {
    hex2="[0-9A-Fa-f][0-9A-Fa-f]"
    hex4=hex2 hex2
    mac=hex2
    for (i=0;i<5;i++) mac=mac "[:-]" hex2
    cisco_mac=hex4 "\\." hex4 "\\." hex4
    ipv4="[0-9][0-9]?[0-9]?\\.[0-9][0-9]?[0-9]?\\.[0-9][0-9]?[0-9]?\\.[0-9][0-9]?[0-9]?"
    vendor_sn="[A-Z][A-Z][A-Z][A-Z]"
    for (i=0;i<8;i++) vendor_sn=vendor_sn "[0-9A-F]"
    address_lexeme="[A-Za-z0-9:.%_+/-]+"
}
function replace_all(line, pattern, tag,   result) {
    result=""
    while (match(line,pattern)) {
        result=result substr(line,1,RSTART-1) tag
        line=substr(line,RSTART+RLENGTH)
    }
    return result line
}
function is_ipv6(value,   address, n, parts, count) {
    address=value
    sub(/%.*/, "", address)
    sub(/\/[0-9]+$/, "", address)
    # Reject timestamps (e.g., 2026-11-12T10:12:14) and prose tokens.
    if (address !~ /^[0-9A-Fa-f:.]+$/) return 0
    if (index(address,":")==0) return 0
    n=split(address,parts,":")
    count=n-1
    return (count>=3 || index(address,"::")>0)
}
function strip_ipv6(line,  result, chunk, remainder) {
    result=""
    remainder=line
    while (match(remainder,address_lexeme)) {
        result=result substr(remainder,1,RSTART-1)
        chunk=substr(remainder,RSTART,RLENGTH)
        if (is_ipv6(chunk)) {
            result=result "[IPv6-REDACTED]"
        } else {
            result=result chunk
        }
        remainder=substr(remainder,RSTART+RLENGTH)
    }
    return result remainder
}
{
    # A malicious vendor diagnostic can be megabytes on one line. This
    # simple bound also avoids quadratic work from repeated substitutions.
    # Do not publish the archive if a field cannot be safely processed.
    if (length($0)>65536) exit 74
    # Omit potentially credential-bearing lines beyond system_log.txt too.
    # fwenv values have already been replaced with literal <redacted>.
    lower=tolower($0)
    if (FILENAME !~ /\/fwenvs[.]txt$/ &&
        lower ~ /password|passwd|pwhash|lpwd|loid|registration|reg_id|gpon_sn|serial|authorization|credential|private[._-]?key|token|secret|bearer/) {
        print "[support: sensitive diagnostic line omitted]"
        next
    }
    # Redact address-like strings in all successful default-mode captures:
    # logs, traffic filters, firmware environment key listings, and host data.
    # Standard MAC is first to avoid classifying it as an IPv6 address.
    line=replace_all($0,mac,"[MAC-REDACTED]")
    line=replace_all(line,cisco_mac,"[MAC-REDACTED]")
    line=strip_ipv6(line)
    line=replace_all(line,ipv4,"[IPv4-REDACTED]")
    # PON serials may occur without a label in vendor output: VEND + 8 hex.
    line=replace_all(line,vendor_sn,"[PON-SERIAL-REDACTED]")
    print line
}

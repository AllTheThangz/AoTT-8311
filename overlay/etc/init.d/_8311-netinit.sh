#!/bin/sh /etc/rc.common

_lib_8311 2>/dev/null || . /lib/8311.sh

START=26

boot() {
	# fwenv for setting eth0_0 speed settings with ethtool
	ETH_SPEED=$(get_8311_ethtool)
	[ -n "$ETH_SPEED" ] && set_8311_ethtool "$ETH_SPEED"

	# LCT VLAN
	LCT_VLAN=$(get_8311_lct_vlan)
	[ "$LCT_VLAN" -gt 0 ] && set_8311_lct_vlan "$LCT_VLAN"

	# LCT IP Address
	set_8311_ipaddr "$(get_8311_ipaddr)"

	# LCT Netmask
	set_8311_netmask "$(get_8311_netmask)"

	# Keep existing management routes, including legacy self-address values.
	# Only an explicitly unset gateway means no default route.
	LCT_GATEWAY=$(get_8311_gateway)
	[ -n "$LCT_GATEWAY" ] && set_8311_gateway "$LCT_GATEWAY"

	# LCT MAC
	set_8311_lct_mac "$(get_8311_lct_mac)"

	# LCT DNS
	DNS_SERVER=$(get_8311_dns_server)
	[ -n "$DNS_SERVER" ] && set_8311_dns_server "$DNS_SERVER"

	# IP Host MAC
	set_8311_iphost_mac "$(get_8311_iphost_mac)"

	ifup "lct"
	[ "$LCT_VLAN" -gt 0 ] && ifup "mgmt"

}

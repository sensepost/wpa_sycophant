#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SUPPLICANT="$SCRIPT_DIR/wpa_supplicant/wpa_supplicant"
configfile=
interface=
socket_path=/run/wpa_sycophant.sock

usage() {
	printf 'Usage: %s -i interface -c config-file [-s socket-path]\n\n' "$0"
	printf 'Launch the built wpa_supplicant relay client. The socket path defaults to\n%s and must match the hostapd-mana sycophant_socket setting.\n' "$socket_path"
}

while getopts ":c:i:s:h" flag; do
	case "$flag" in
		c) configfile=$OPTARG ;;
		i) interface=$OPTARG ;;
		s) socket_path=$OPTARG ;;
		h) usage; exit 0 ;;
		:) echo "Missing value for -$OPTARG" >&2; usage >&2; exit 2 ;;
		\?) echo "Unknown option: -$OPTARG" >&2; usage >&2; exit 2 ;;
	esac
done

if [[ $(id -u) -ne 0 ]]; then
	echo "Run this script as root (for example, with sudo)." >&2
	exit 1
fi
if [[ -z $configfile || -z $interface ]]; then
	echo "Both -i and -c are required." >&2
	usage >&2
	exit 2
fi
if [[ ! -r $configfile ]]; then
	echo "Cannot read config file: $configfile" >&2
	exit 1
fi
if [[ ! -x $SUPPLICANT ]]; then
	echo "Built wpa_supplicant not found at $SUPPLICANT; build it first." >&2
	exit 1
fi

exec "$SUPPLICANT" -i "$interface" -c "$configfile" -S "$socket_path"

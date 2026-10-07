# PEAP relay hwsim test

This test runs the complete PEAP/MSCHAPv2 relay with four dynamically created
mac80211_hwsim radios:

1. A victim associates to the rogue MANA AP using the target SSID.
2. The sycophant station associates to the legitimate AP with its relay
   identity and password left empty.
3. The MANA AP relays the victim's identity and MSCHAPv2 response to the
   legitimate AP through the Unix socket.
4. The test checks both stations' BSSIDs, wpa_state=COMPLETED, and ping
   connectivity to their respective APs. It also checks the logs for the
   relayed challenge and accepted relayed MSCHAPv2 success.

The victim's 802.11 association starts first. Its EAP authentication remains
in progress until the sycophant station starts and completes the relay.

## Requirements

- Linux with mac80211_hwsim and its generic netlink control interface enabled.
- Root privileges, iproute2, iw, and ping.
- The matching wpa_sycophant 2.12 and hostapd-mana 2.12 source checkouts in
  sibling directories, as in this repository.
- Built wpa_supplicant, wpa_cli, hostapd, and hostapd_cli binaries.

The test creates four hwsim radios and moves them into isolated temporary
network namespaces: one for the APs, one for the victim, and one for the
sycophant. Keeping each station's IP stack separate from the AP lets the test
verify actual ping connectivity over the wireless link. The test returns the
radios to the original namespace and removes the temporary namespaces after
the run. The AP certificate and key are the public test fixtures from
hostapd-mana/tests/hwsim/auth_serv/.
If the hwsim module is not already loaded, load it before running the test:

    sudo modprobe mac80211_hwsim radios=0

## Build and run

From the wpa_sycophant source directory:

    cp wpa_supplicant/defconfig wpa_supplicant/.config
    make -C wpa_supplicant

From the sibling hostapd-mana checkout:

    cp hostapd/defconfig hostapd/.config
    make -C hostapd

Then run the test as root:

    sudo ./test/run-hwsim-e2e.py

The script locates the sibling hostapd-mana checkout and the default build
outputs automatically. Use --hostapd-src, --hostapd-bin,
--wpa-supplicant-bin, or --hwsim-dir to select different paths. A failed
run keeps its generated configs and logs and prints their location; use
--keep-logs to retain them after a successful run too.

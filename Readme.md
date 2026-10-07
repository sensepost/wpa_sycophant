# wpa_sycophant

wpa_sycophant is a wpa_supplicant 2.12 based PEAP/MSCHAPv2 relay peer for use with the matching hostapd-mana release. The relay hands EAP identities and MSCHAPv2 challenge/response data over a local Unix domain socket.

## Build

From this directory:

```sh
cp wpa_supplicant/defconfig wpa_supplicant/.config
make -C wpa_supplicant
```

The default build configuration enables the Linux nl80211 driver, PEAP, MSCHAPv2, and the sycophant socket client. Use the normal hostap build options to add or remove drivers as needed.

## Run

Enable Sycophant in the matching hostapd-mana configuration and use the same socket path on both programs. The default is `/run/wpa_sycophant.sock`:

```ini
enable_sycophant=1
sycophant_socket=/run/wpa_sycophant.sock
```

Then start the supplicant with the target interface and network profile:

```sh
sudo ./wpa_sycophant.sh -i wlan0 -c wpa_sycophant_example.conf
```

To use a different socket path, set it in hostapd-mana and pass `-s /path/to/socket` to the launcher. The launcher does not configure the interface or start DHCP; handle those through your normal network setup.

The example profile targets PEAP with inner MSCHAPv2. Set the target SSID and add the rogue AP BSSID to `bssid_blacklist` when both radios can hear the rogue AP.

## Compatibility

The socket protocol is intended for the matching wpa_sycophant and hostapd-mana 2.12 branches. It supports one active relay session per wpa_sycophant process.

The wpa_supplicant source retains the license in `COPYING`. Sycophant-specific changes are distributed under the BSD license.

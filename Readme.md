# wpa_sycophant

wpa_sycophant is a tool to exploit weaknesses in PEAP/MSCHAPv2 where the connection can be relayed between a station and wireless network. It works in concert with hostapd-mana as the rogue access point/authenticator. This can be done without knowing or cracking the password or hash used for authentication. The net result is a connection to both the target network with wpa_sycophant, and a connection to the rogue AP from the targetted station.

This is a wpa_supplicant 2.12 based PEAP/MSCHAPv2 relay peer for use with the matching hostapd-mana release. The relay hands EAP identities and MSCHAPv2 challenge/response data over a local Unix domain socket.

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

The example profile targets PEAP with inner MSCHAPv2. Set the target SSID. If the sycophant radio can also see the rogue AP, add that AP's BSSID to `bssid_ignore` in the profile so the sycophant does not connect back to the relay AP.

## Avoid relaying to yourself

When the rogue AP and target use the same SSID, the sycophant radio may see both. If it associates with the rogue AP, it can relay back to itself instead of reaching the legitimate network. Find the rogue AP's BSSID (for example, with `hostapd_cli -i <interface> status`) and add it to the sycophant network profile:

```ini
network={
  ssid="TestingEAP"
  # Other PEAP/MSCHAPv2 settings...
  bssid_ignore=02:11:22:33:44:55
}
```

Replace the example address with the rogue AP's actual BSSID. `bssid_ignore` is the current option name; `bssid_blacklist` is a deprecated alias.

## Remote AP with a RADIUS-only MANA server

The rogue AP can use hostapd-mana as an external RADIUS/EAP server instead of running MANA on the AP itself. Run hostapd-mana in standalone RADIUS mode with `driver=none`, then configure the rogue AP to send RADIUS authentication requests to it. A minimal hostapd-mana configuration looks like:

```ini
interface=lo
driver=none

eap_server=1
eap_user_file=/etc/hostapd-mana/eap_user.conf
ca_cert=/etc/hostapd-mana/ca.pem
server_cert=/etc/hostapd-mana/server.pem
private_key=/etc/hostapd-mana/server.key

radius_server_clients=/etc/hostapd-mana/radius_clients
radius_server_auth_port=1812

enable_sycophant=1
sycophant_socket=/run/wpa_sycophant.sock
```

The `radius_clients` file authorizes the rogue AP's RADIUS/NAS address and sets its shared secret:

```text
198.51.100.10 replace-with-a-shared-secret
```

Configure the rogue AP with the matching RADIUS server address, port, and secret:

```ini
auth_server_addr=192.0.2.20
auth_server_port=1812
auth_server_shared_secret=replace-with-a-shared-secret
```

Use your deployment's certificate, EAP user database, addresses, and secrets. The EAP user database must match the PEAP configuration used by MANA.

### Run MANA and sycophant on separate hosts

The relay uses a Unix domain socket, which is local to one host. To run the RADIUS-only hostapd-mana server and wpa_sycophant on separate hosts, forward the socket over OpenSSH. OpenSSH must allow Unix-socket forwarding on the MANA host (`AllowStreamLocalForwarding` in `sshd_config`).

On the sycophant host, start a persistent SSH tunnel. Replace `mana-user` and `mana-host` with the SSH account and hostname of the host running hostapd-mana:

```sh
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -o StreamLocalBindUnlink=yes \
  -L "$XDG_RUNTIME_DIR/wpa-sycophant.sock:/run/wpa_sycophant.sock" \
  mana-user@mana-host
```

In another terminal on the sycophant host, point the launcher at the forwarded local socket:

```sh
sudo ./wpa_sycophant.sh -i wlan0 -c wpa_sycophant_example.conf \
  -s "$XDG_RUNTIME_DIR/wpa-sycophant.sock"
```

The SSH account on the MANA host must be able to connect to `/run/wpa_sycophant.sock`. The socket is created with owner-only permissions (`0600`), so run the SSH tunnel as the same Unix user that runs hostapd-mana. The rogue AP can be on a third host and send its RADIUS traffic to MANA over IP as usual.

## Compatibility

The socket protocol is intended for the matching wpa_sycophant and hostapd-mana 2.12 branches. It supports one active relay session per wpa_sycophant process.

The wpa_supplicant source retains the license in `COPYING`. Sycophant-specific changes are distributed under the BSD license.

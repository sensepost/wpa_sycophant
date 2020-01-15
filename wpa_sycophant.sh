#!/bin/bash

if (( $EUID != 0 )); then
    echo "SYCOPHANT : Please run as root"
    exit
fi

# configfile="./wpa_sycophant_example.conf"
# interface="wlp0s20f0u6"
supplicant="./wpa_supplicant/wpa_supplicant"

# supplicant_location=''
configfile=''
interface=''

print_usage(){ 
    printf "Usage: sudo ./wpa_sycophant_new.sh -c wpa_sycophant_example.conf -i wlan0\n" 
}

while getopts 'c:i:h' flag; do
  case "${flag}" in
    i) interface="${OPTARG}" ;;
    c) configfile="${OPTARG}" ;;
    h) print_usage
       exit 1 ;;
    *) print_usage
       exit 1 ;;
  esac
done

clean_up(){
    rm /tmp/SYCOPHANT_P1ID
    rm /tmp/SYCOPHANT_P2ID
    rm /tmp/CHALLENGE
    rm /tmp/CHALLENGE_LOCK
    rm /tmp/RESPONSE
    rm /tmp/RESPONSE_LOCK 
    rm /tmp/SYCOPHANT_STATE
    return
}

exit_time(){
    printf "\n"
    printf "SYCOPHANT : Cleaning Up State\n"
    clean_up &>/dev/null
    printf "SYCOPHANT : Stopping dhcpcd\n"
    dhclient -x -r $interface
    printf "SYCOPHANT : Exiting\n" 
    kill 0
}

# ERR is triggered if rm file doesnt exist.
# trap "exit" INT TERM ERR
trap "exit" INT TERM
trap "exit_time" EXIT

clean_up &>/dev/null


printf "SYCOPHANT : RUNNING \"$supplicant -i $interface -c $configfile\"\n"
$supplicant -i $interface -c $configfile &

printf "SYCOPHANT : RUNNING \"dhclient $interface\"\n"
dhclient $interface 

wait

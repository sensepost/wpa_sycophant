#!/bin/bash

configfile="./wpa_sycophant_example.conf"
interface="wlp0s20f0u1"
supplicant="./wpa_supplicant/wpa_supplicant"


echo "Using config: " $configfile
echo "Using interface: " $interface

phase1_file="/tmp/IDENT_PHASE1_FILE.txt"
phase2_file="/tmp/IDENT_PHASE2_FILE.txt"

echo "Phase 1 File: " $phase1_file
echo "Phase 2 File: " $phase2_file

touch $phase1_file
touch $phase2_file

add_identities () {
    escaped_identity1=$(echo $2 |sed -e 's/\\/\\\\/g; s/\//\\\//g; s/&/\\\&/g')
    escaped_identity2=$(echo $3 |sed -e 's/\\/\\\\/g; s/\//\\\//g; s/&/\\\&/g')
    cat $1 | sed "s/<anonymous_identity>/$escaped_identity1/;s/<identity>/$escaped_identity2/"
}

echo "Waiting for Identities"

## IF inotifywait exists
if command -v inotifywait > /dev/null; then
    while inotifywait -e close_write $phase1_file > /dev/null; do
        while inotifywait -e close_write $phase2_file > /dev/null; do
            phase1_ident=$(cat $phase1_file)
            phase2_ident=$(cat $phase2_file)
            add_identities $configfile $phase1_ident $phase2_ident
            $supplicant -i $interface -c <(add_identities $configfile $phase1_ident $phase2_ident)
            echo '' > $phase1_file
            echo '' > $phase2_file
        done
    done
else
    echo "inotifywait not installed"
    echo "Using more generic method"
    while true; do
        if ! [ -s $phase1_file ]; then
            echo "Phase 1 Identity recieved:" $(cat $phase1_file) 
            while true; do
                if ! [ -s $phase2_file ]; then
                    echo "Phase 2 Identity recieved:" $(cat $phase2_file) 
                    phase1_ident=$(cat $phase1_file)
                    phase2_ident=$(cat $phase2_file)
                    add_identities $configfile $phase1_ident $phase2_ident
                    $supplicant -i $interface -c <(add_identities $configfile $phase1_ident $phase2_ident)
                    echo '' > $phase1_file
                    echo '' > $phase2_file
                    break
                fi
            done
        fi
    done
fi


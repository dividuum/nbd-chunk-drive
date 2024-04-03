#!/bin/bash
set -e
CACHE=/tmp/.remote
mkdir -p $CACHE/lower $CACHE/upper $CACHE/work
[ -d /sys/module/nbd ] || insmod mister-nbd.ko.xz
[ -d /sys/module/overlay ] || insmod mister-overlay.ko.xz
../nbd-chunk-connect /dev/nbd0 $1 &
while [ "$(blockdev --getsz /dev/nbd0)" == "0" ]; do
    echo "waiting for block device.."
    sleep 1
done
mount /dev/nbd0 $CACHE/lower -o ro
mount -t overlay none -o lowerdir=$CACHE/lower,upperdir=$CACHE/upper,workdir=$CACHE/work /media/usb0

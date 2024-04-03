This is an attempt at making MiSTer FPGA transparently use
a remote storage device.

In theory copying the complete checkout to your MiSTer, changing
into the `mister_fpga` directory and then running

```
./remote-mount-usb0.sh <intro_url>
```

should work. It will mount the referenced block device
into /tmp/.remote/lower and then layers an overlayfs
on top of that to allow writing. This also currently
sucks, as /tmp is a tmpfs (so had limited space)
and using /media/fat (and exfat) doesn't work as that
type of FS doesn't seem supported
for an upper layer.

An additional issue seems to be case insensitivity of
filenames and some issue in exfat that prevents it from
being used:

 * Using ext4 is cumbersome as MiSTer doesn't properly handle
   case sensitivity. While ext4 now has a mode to support
   casefolding, I didn't try that yet.
   Simply using an ext4 image with -O casefold doesn't
   mount with:

   ```
   EXT4-fs (nbd0): Filesystem with casefold feature cannot be mounted without CONFIG_UNICODE
   ```

   `CONFIG_UNICODE` in turn cannot be compiled as a kernel
   module but has to be built-in. Which means compiling
   a complete new kernel which makes all of that too
   complicated to use. The bundled kernel modules are
   already bad enough.

 * Exfat seems to try to read a random huge sector out of
   bounds every time I try to mount such an image:

   ```
   [EXFAT] trying to mount...
   [EXFAT] sector_read: out of range error! (sec = 109586501504)
   [EXFAT] FsMountVol failed
   ```

   Not sure what that's about. I also don't get why this
   error doesn't happen when mounting from USB.

Ideas on how to get this work are welcome.

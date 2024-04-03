# How the kernel modules were built

```
git clone --depth=1 https://github.com/MiSTer-devel/Linux-Kernel_MiSTer.git
cd Linux-Kernel_MiSTer/
export ARCH=arm
export CROSS_COMPILE=arm-linux-gnueabihf-
export LOCALVERSION=-MiSTer
make MiSTer_defconfig
export KCFLAGS="-fno-stack-protector"
make menu_config

Device Drivers > Block devices > <M> Network block device support
File Systems > <M> Overlay filesystem support

make modules -j30

drivers/block/nbd.ko
fs/overlayfs/overlay.ko
```

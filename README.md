# Create and mount block devices efficiently served by static HTTP

This toolset allows you to create a chunked representation of
a block device. The chunks can be uploaded to any static web server
to form a repository. A client side tool can import from this
repository and expose the content as a local block device using NBD so
you can mount it readonly into the local filesystem.

The chunked representation uses content based hashing and
encryption. Without knowledge of the 'UnlockKey', the
files provide no insight other than what can be observed
by their size and access pattern.

The repository can be easily validated using sha256sum
and all filenames correspond to their SHA256 checksum.

Chunking of a block device can be repeated and the chunks
can be placed in the same repository. When possible, chunks
are reused and compressed. Mixing multiple block devices
in the same repository is also possible.

## Example: Importing content to a repository

Create an empty filesystem image:

```
user:/tmp$ truncate demo.img --size 50M
user:/tmp$ mkfs.ext4 -b 4096 demo.img
[...]
Creating journal (1024 blocks): done
Writing superblocks and filesystem accounting information: done
user:/tmp$ _
```

Optionally now mount as loop back and put files on it and
unmount again. Then use the `nbd-chunk-import` tool to split up
the demo.img file into chunks:

```
user:/tmp$ nbd-chunk-import demo.img UnlockKey RepoKey /tmp/chunks
543.0MB/s: 50MB => 0MB - 99.54% compression, 98.23% chunk reuse, 0.00MB new

f2f4fc043b7df808e68fe928ebaee54e2326e01d62e6e05617b4519c74da91ff#UnlockKey
user:/tmp$ _
```

This has converted `demo.img` into chunks and placed them into
the specified target directory. Note that last line of output above.
It will be needed to access the data later. UnlockKey and RepoKey
must be replaced with real password-like value. This will be
described down below.

First the output of the chunking. An empty ext4 filesystem is
pretty easy to compress:

```
user:/tmp$ ls -l chunks/
total 20
-rw------- 1 user user 1830 Apr  1 23:23 145d9e19d411<truncated>
-rw------- 1 user user 1222 Apr  1 23:23 41cd84895c49<truncated>
-rw------- 1 user user 1206 Apr  1 23:23 c77b1e1ea5df<truncated>
-rw------- 1 user user  230 Apr  1 23:23 cdf67053231c<truncated>
-rw------- 1 user user  134 Apr  1 23:23 f2f4fc043b7d<truncated>
user:/tmp$ _
```

The files in `chunks` can now be placed on any static web server. Using
rsync might be recommended as it can avoid copying already existing
files in case the target web server already hosts chunks from a previous
run.

```
user:/tmp$ rsync -av chunks webstuff@repo.example.com:
sending incremental file list
chunks/
chunks/145d9e19d411cb8eae559a8ff25c90a010da8d4f28fcb23be5651eece87e75cf
chunks/41cd84895c4949a85e20b6b028477a3a3290c58baf8ae199be5dd39e3291297e
chunks/c77b1e1ea5df6dcd9f6d89d5a2b3b0a41a268fd50f5aff44f7d858e013587c0a
chunks/cdf67053231c5947cab30fb48300aa8eff3f84a6b96f8c30a42d8c9bc17dec18
chunks/f2f4fc043b7df808e68fe928ebaee54e2326e01d62e6e05617b4519c74da91ff

sent 5,302 bytes  received 115 bytes  2,166.80 bytes/sec
total size is 4,622  speedup is 0.85
user:/tmp$ _
```

You can also verify that everything is content addressed:

```
user:/tmp$ sha256sum chunks/*
145d9e19d411cb8eae55<truncated>  chunks/145d9e19d411cb8eae55<truncated>
41cd84895c4949a85e20<truncated>  chunks/41cd84895c4949a85e20<truncated>
c77b1e1ea5df6dcd9f6d<truncated>  chunks/c77b1e1ea5df6dcd9f6d<truncated>
cdf67053231c5947cab3<truncated>  chunks/cdf67053231c5947cab3<truncated>
f2f4fc043b7df808e68f<truncated>  chunks/f2f4fc043b7df808e68f<truncated>
user:/tmp$ _
```

Repeat the chunking and uploading steps after making changes to
the `demo.img` file or import additional block devices.

## Example: Accessing the content of a repository

You'll need the intro URL to open an imported chunked block device.
You can create that using the output of the `nbd-chunk-import` run above..

```
f2f4fc043b7df808e68fe928ebaee54e2326e01d62e6e05617b4519c74da91ff#UnlockKey
```

Prefix that value with the public URL base path where your HTTP server
exports your chunk files. A full intro URL might look like this:

```
https://repo.example.com/f2f4fc043<truncated>c74da91ff#UnlockKey
```

The `nbd-chunk-connect` tool opens this URL and exposes it to
the specified NBD /dev entry:

```
user:/tmp$ nbd-chunk-connect /dev/nbd0 https://repo.example.com/f2f4<...>
[..output..]
```

After a moment, the block device will be ready. See `dmesg`:

```
[ 6505.771400] nbd0: detected capacity change from 0 to 102400
```

(102400 * 512 sector size = 50MB) You can now mount the block
device in another terminal. The 'ro' makes it explicit that the
device will be read-only. Behold the almost empty filesystem:

```
user:/tmp$ mount /dev/nbd0 /mnt/demo -o ro
user:/tmp$ ls -l /mnt/demo
total 16
drwx------ 2 root root 16384 Apr  1 23:21 lost+found
user:/tmp$ _
```

## UnlockKey and RepoKey

Both keys are intended for different use cases:

 * The UnlockKey together with the SHA256 value of an intro
   chunk allows decryption of all referenced chunks required
   to access the complete chunkified block device. The intro URL
   above contains the URL of the intro chunk in the path component
   and the UnlockKey in the URL fragment.

   As long as users cannot list all chunks available on your
   repository web server, multiple UnlockKeys can be used
   to separate different version of a block device import while
   still allowing potential reuse for unchanged chunks.

   A value derived from the RepoKey is accessible to anyone
   with access to a intro URL as that is required to
   decrypt the referenced content.

 * The RepoKey protects the content of all uploaded chunks
   against snooping by anyone controlling the HTTP Server. Without
   that key, none of the files are readable.

   As SHA256 named files will realistically never collide,
   multiple RepoKey values can also be used to scope different
   unrelated imports from each other.

This means:

 * Once your share an intro URL (which includes the URL
   of the intro chunk and the UnlockKey) with other
   people, they will be able to fully access the content
   of the import that created the intro URL.

 * If other people cannot list all files available, they
   will not be able to learn about other repositories
   based on them having knowledge of a single intro URL
   as guessing filenames is improbable.

 * If all chunk files together with an UnlockKey leak,
   all imports using the same RepoKey will be accessible
   if the UnlockKey unlocks a single import.

 * Unless the operator of the HTTP server has access
   to the UnlockKey, they will not be able to decrypt
   any of the content. They can only observe the access
   pattern and file size of individual chunks. They
   can also not modify any of the chunks as all their
   content is cryptographically hashed to ensure integrity.

 * Due to the content addressing used, the operator of
   the HTTP server can verify the correctness of all
   chunk files by calculating their SHA256 sum and
   comparing it with the filename. Neither access to
   the UnlockKey or RepoKey is needed for that.

## Architecture

All content of the provided block device is streamed into
a chunk of fixed size. Once that chunk fills up (the default
is 256KB), the chunk is wrapped up by first attempting to
compress it using zlib, followed by encrypting it using
a key based on its content and the derived RepoKey. It is then
persisted and a new empty chunk as created.
A reference to the persisted chunk (its SHA256 checksum)
is added to the, potentially also newly created, chunk in
the layer above. Similarly if the chunk in the layer above
fills up, another layer is added on top of that, and so on.

Basically this forms a tree where each node has a vast
number of childs (when using 256KB chunks, each chunk has
8192 child references). There is always only a single
top level chunk.

As references use content based addressing repeated runs
of single byte value all reference the same chunk.
As a side effect, this also allows compressing those
references. Similarly, new imports can reference chunks
created by earlier imports assuming parts of the imported
block device remain unchanged.

Special treatment is made to chunks that only contain
zero-bytes. They will be completely skipped and the
special 32 byte \x00 value is used as a reference. This
also means that complete subtrees containing only
zero bytes will be pruned completely. This allows
efficient encoding of sparse files.

The top level chunk is referenced by the small intro chunk
which provides some metadata about the import, like
total size, number of layers and the derived RepoKey.
The intro chunk is encrypted using the UnlockKey and
persisted.

Then the SHA256 checksum of the intro chunk is printed
together with the UnlockKey to access all that.

## Notes

 * This is the first release. All claimed cryptographic
   properties might be completely false due to design
   flaws. No promises are made. Feel free to provide
   feedback.

 * I wrote this to see if its possible to mount a
   HTTP based, versioned and remote repository of my
   games stored on my MiSTer FPGA machine after my
   first SD card died.

 * There is limited protection when accessing repositories
   created by malicious users. This is twofold:

   * The tool itself might now handle all edge cases
     if corrupt data is fed to it.

   * The resulting block device on /dev/nbdX can be dangerous
     to mount as filesystem code is complex and might
     not be hardened. You shouldn't trust the created
     NBD /dev entry more than a random USB stick
     you've found.

 * As using `nbd-chunk-import` shares complete block devices,
   the usual caution is advised in regards to file deletion.
   `shred` with the `-z` flag (to help with compression)
   might help, but your mileage might vary.

 * Somewhat related: For maximum compression, temporarily
   filling the mounted filesystem with zero-bytes prior
   to chunking it might be worth it. Of course that throws out
   all benefits of `nbd-chunk-import` sparse file support.

 * If your filesystem image runs out of space, you can
   use `truncate` to extend the size of the image, then
   resize the filesystem. Sparse files take up no
   extra space on the disk and `nbd-chunk-import` knows how to
   compress them efficiently.

   The reuse of chunks should only add a few extra
   chunks as a result.

 * Chunk downloads support redirects. This might allow
   some form of cheapo load balancing.

## Out of scope

 * Vastly different encryption methods or compression.

 * Uploading to cloud targets. 'rclone' probably
   already solves that. But a custom ChunkWriter
   might implement throttling while writing out new
   chunks.

 * Using external dependencies.

## Ideas

 * To get a first release done as a proof of concept,
   I wrote this toolset in Python over a weekend. It would
   be nice to have a more performant version in another language
   once the foundation is solid and it turns out to be
   useful.

 * Background prefetching of chunks based on access patterns
   could speed up linear access. Although this might probably
   be already handled in some form in the kernel. Now sure..

 * Right now only a small memory cache of chunks is implemented.
   This is probably good enough as the Linux buffer cache already
   caches repeated file access. It might still be useful to
   implement a file based cache to avoid repeated downloads
   if the same block device is mounted repeatedly.

   This could then even allow limited offline use as long
   as the access pattern remains the same.

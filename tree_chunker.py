#
# Copyright (C) 2024 by Florian Wesch <fw@dividuum.de>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import io, hashlib, zlib, hmac, binascii, struct, os
from collections import namedtuple
try:
    from Cryptodome.Cipher import AES
except ImportError:
    import socket
    if socket.gethostname() == 'MiSTer':
        # Cryptodome not available on MiSTer FPGA's Linux installation :-(
        from mister_fpga.horrible_aes import HorribleFragileStandaloneForDecryptionOnlyAES as AES
    else:
        raise

VERSION = 1
MAGIC = b'TREECHUNK REPO\n\0'

ZERO_HASH = bytes([0]*32)

class ChunkError(Exception):
    pass

def zero_pad(data, align=AES.block_size):
    data_len = len(data)
    if data_len % align:
        data += b'\0' * (align - 1 - ((data_len-1) % align))
    return data

class ZeroSource:
    def __init__(self, size):
        self._size = size
        self._remaining = size

    def seek(self, offset):
        assert(offset < self._size)
        self._remaining = self._size - offset

    def read(self, size):
        read_size = min(size, self._remaining)
        self._remaining -= read_size
        buf = bytearray(read_size)
        return buf

class LayerShape(namedtuple('LayerShape', ['shift', 'mask', 'entry_size'])):
    @property
    def entry_cover_size(self):
        return 1 << self.shift
    def entry_offset(self, offset):
        return ((offset >> self.shift) & self.mask) * self.entry_size
    def __repr__(self):
        return f'<X >> {self.shift} & {self.mask:x} * {self.entry_size}, cover:{self.entry_cover_size}>'

def layer_shape(size_2, num_layers):
    chunk_size = 2**size_2
    upper_entry_size = 32 # sizeof(sha256 hash)
    layer_shape = [LayerShape(0, chunk_size-1, 1)]
    upper_chunk_entries = int(chunk_size / upper_entry_size)
    upper_chunk_numbits = bin(upper_chunk_entries-1).count('1')
    bit_start = size_2
    for layer in range(1, num_layers):
        layer_shape.append(LayerShape(
            bit_start, upper_chunk_entries-1, upper_entry_size
        ))
        bit_start += upper_chunk_numbits
    return layer_shape

class ChunkEncoder:
    def __init__(self, max_size):
        self._max_size = max_size
        self._free = max_size
        self._buffer = io.BytesIO()

    def write(self, data):
        written = min(len(data), self._free)
        self._buffer.write(data[:written])
        self._free -= written
        return written

    @property
    def free(self):
        return self._free

    @property
    def is_full(self):
        return self._free == 0

    @property
    def is_empty(self):
        return self._free == self._max_size

    def wrap_up(self, chunk_key, compress=True):
        content = uncompressed = uncompressed = self._buffer.getvalue()
        if compress:
            content = zlib.compress(uncompressed, 1)
            if len(content) > len(uncompressed) * 0.8:
                content = uncompressed
                compress = False
        padded_content = zero_pad(content)
        content_iv = hmac.new(
            chunk_key,
            hashlib.sha256(content).digest(),
            hashlib.sha256
        ).digest()[:16]
        header = struct.pack('<16sBBL16s',
            MAGIC,
            VERSION,
            compress,
            len(content),
            content_iv
        )
        cipher = AES.new(chunk_key, AES.MODE_CBC, iv=content_iv)
        chunk_data = header + cipher.encrypt(padded_content)
        return hashlib.sha256(chunk_data).digest(), chunk_data

class ChunkDecoder:
    @classmethod
    def from_encrypted_stream(cls, chunk_stream, content_hash, chunk_key, max_chunk_size):
        content_h = hashlib.sha256()

        fmt = '<16sBBL16s'
        header_size = struct.calcsize(fmt)
        header = chunk_stream.read(header_size)
        if len(header) != header_size:
            raise ChunkError("Short outer header")
        magic, version, compressed, content_len, content_iv = struct.unpack(fmt, header)
        if magic != MAGIC:
            raise ChunkError("Invalid chunk magic")
        if version != VERSION:
            raise ChunkError("Short version")
        if compressed not in (0, 1):
            raise ChunkError("Invalid compression flag")
        content_h.update(header)

        encrypted = chunk_stream.read(max_chunk_size)
        content_h.update(encrypted)

        if not hmac.compare_digest(content_h.digest(), content_hash):
            raise ChunkError("Invalid hash")
        if len(encrypted) % AES.block_size:
            raise ChunkError("Invalid chunk size")
        if len(encrypted) < content_len:
            raise ChunkError("Unexpected content length")

        cipher = AES.new(chunk_key, AES.MODE_CBC, iv=content_iv)
        content = cipher.decrypt(encrypted)

        if len(content) > content_len:
            content = content[:content_len]

        if 0:
            # Not sure if this adds anything useful as the
            # integrity has already been tested above.
            expected_content_iv = hmac.new(
                chunk_key,
                hashlib.sha256(content).digest(),
                hashlib.sha256
            ).digest()[:16]
            if not hmac.compare_digest(expected_content_iv, content_iv):
                raise ChunkError("Unexpected content iv")

        if compressed:
            dec = zlib.decompressobj()
            content = dec.decompress(content, max_length=max_chunk_size)

        return cls(content_hash, content)

    @classmethod
    def from_plain(cls, content_hash, content):
        return cls(content_hash, content)

    def __init__(self, content_hash, content):
        self._content_hash = content_hash
        self._content = content

    def as_intro(self):
        fmt = "<16slllQl16s32s"
        header_size = struct.calcsize(fmt)
        if len(self._content) != header_size:
            raise ChunkError("Short header")
        magic, version, size_2, num_layers, total_size, block_size, repo_key, top_chunk_hash = struct.unpack(fmt, self._content)
        if magic != MAGIC:
            raise ChunkError("Invalid repo magic. Wrong unlock key?")
        if version != VERSION:
            raise ChunkError("Invalid repo version")
        if block_size not in (4096, 8192):
            raise ChunkError("Invalid block size")
        return size_2, num_layers, total_size, block_size, repo_key, top_chunk_hash

    def as_content_stream(self):
        return io.BytesIO(self._content)

    @property
    def content(self):
        return self._content

    @property
    def content_hash(self):
        return self._content_hash


class ChunkWriter:
    def __init__(self, size_2, repo_key, unlock_key, compress_data=True):
        self._layers = []
        self._size_2 = size_2
        self._max_size = 2 ** size_2
        self._total_size = 0
        self._repo_key = hashlib.sha256(repo_key).digest()[:16]
        self._unlock_key = unlock_key
        self._compress_data = compress_data
        self._layer_shape = layer_shape(size_2, 16)
        assert(self._layer_shape[-1].shift > 64)
        self._intro_key = hmac.new(
            self._unlock_key, b'intro', hashlib.sha256
        ).digest()[:16]
        self._layer_key = hmac.new(
            self._repo_key, b'layer', hashlib.sha256
        ).digest()[:16]

        zero_chunk = ChunkEncoder(self._max_size)
        zero_chunk.write(bytearray(self._max_size))
        self._all_zero_chunk_hash, _ = zero_chunk.wrap_up(
            self._layer_key, self._compress_data
        )

    def wrap_up_layer(self, layer, write_upper_ref):
        if self._layers[layer].is_empty:
            return self._layers[layer], None
        chunk_hash, chunk_data = self._layers[layer].wrap_up(
            self._layer_key, self._compress_data
        )
        if chunk_hash == self._all_zero_chunk_hash:
            chunk_hash = ZERO_HASH
        else:
            self.persist_chunk(chunk_hash, chunk_data)
        if write_upper_ref:
            self.write_layer(layer+1, chunk_hash)
        self._layers[layer] = ChunkEncoder(self._max_size)
        return self._layers[layer], chunk_hash

    def write_layer(self, layer, data):
        if layer >= len(self._layers):
            self._layers.append(ChunkEncoder(self._max_size))
        offset, data_size = 0, len(data)
        chunk = self._layers[layer]
        while 1:
            if chunk.is_full:
                chunk, _ = self.wrap_up_layer(layer, write_upper_ref=True)
            offset += chunk.write(data[offset:offset+chunk.free])
            if offset == data_size:
                break

    def write(self, data):
        self._total_size += len(data)
        self.write_layer(0, data)

    def write_layer_zeros(self, layer, zeros):
        shape = self._layer_shape[layer]
        if zeros < shape.entry_cover_size:
            return zeros

        if layer >= len(self._layers):
            self._layers.append(ChunkEncoder(self._max_size))
        chunk = self._layers[layer]

        if zeros > 0:
            entries_free = chunk.free // shape.entry_size
            entries_needed = zeros // shape.entry_cover_size
            fill = min(entries_free, entries_needed)
            chunk.write(bytes([0] * fill * shape.entry_size))
            zeros -= fill * shape.entry_cover_size

        if chunk.is_full:
            chunk, _ = self.wrap_up_layer(layer, write_upper_ref=True)

        zeros = self.write_layer_zeros(layer+1, zeros)

        if zeros > 0:
            entries_free = chunk.free // shape.entry_size
            entries_needed = zeros // shape.entry_cover_size
            assert(entries_free >= entries_needed)
            fill = entries_needed
            chunk.write(bytes([0] * fill * shape.entry_size))
            zeros -= fill * shape.entry_cover_size

        return zeros

    def write_zeros(self, size):
        self._total_size += size
        zeros_remaining = self.write_layer_zeros(0, size)
        assert(zeros_remaining == 0)

    def wrap_up(self, block_size=4096):
        if self._total_size % block_size:
            pad = b'\0' * (block_size - 1 - ((self._total_size-1) % block_size))
            self.write(pad)

        for layer in range(len(self._layers)):
            top_layer = layer == len(self._layers) - 1
            _, chunk_hash = self.wrap_up_layer(
                layer,
                write_upper_ref = not top_layer
            )

        intro = struct.pack("<16slllQl16s32s",
            MAGIC,
            VERSION,
            self._size_2,
            len(self._layers),
            self._total_size,
            block_size,
            self._repo_key,
            chunk_hash,
        )

        intro_chunk = ChunkEncoder(len(intro))
        written = intro_chunk.write(intro)
        assert(written == len(intro))

        chunk_hash, chunk_data = intro_chunk.wrap_up(
            self._intro_key, compress=False
        )
        self.persist_chunk(chunk_hash, chunk_data)
        return self.flush(chunk_hash, self._unlock_key)

    def persist_chunk(self, chunk_hash, chunk):
        print(binascii.hexlify(chunk_hash), len(chunk))

    def flush(self, header_chunk_hash, unlock_key):
        return header_chunk_hash


class ChunkReader:
    def __init__(self, intro_hash, unlock_key, loader, cache):
        self._loader = loader
        self._cache = cache
        self._intro_hash = intro_hash
        self._intro_key = hmac.new(
            unlock_key, b'intro', hashlib.sha256
        ).digest()[:16]
        self._max_chunk_size = 256

        chunk = self.load_chunk(self._intro_hash, self._intro_key)

        size_2, num_layers, self._total_size, self._block_size, \
            repo_key, self._top_chunk_hash = chunk.as_intro()

        self._layer_key = hmac.new(
            repo_key, b'layer', hashlib.sha256
        ).digest()[:16]
        self._max_chunk_size = 2**size_2 + 256
        self._num_layers = num_layers
        self._layer_shape = layer_shape(size_2, num_layers)

    @property
    def total_size(self):
        return self._total_size

    @property
    def block_size(self):
        return self._block_size

    def load_chunk(self, chunk_hash, chunk_key):
        cached_data = self._cache.get(chunk_hash)
        if cached_data:
            return ChunkDecoder.from_plain(chunk_hash, cached_data)
        with self._loader.open_stream(chunk_hash, self._max_chunk_size) as stream:
            chunk = ChunkDecoder.from_encrypted_stream(
                stream,
                chunk_hash,
                chunk_key,
                self._max_chunk_size,
            )
        self._cache.set(chunk.content_hash, chunk.content)
        return chunk

    def get_chunk_stream(self, offset):
        assert(offset < self._total_size)
        if self._top_chunk_hash == ZERO_HASH:
            return ZeroSource(self._total_size)
        chunk_hash = self._top_chunk_hash
        for layer in reversed(range(self._num_layers)):
            if chunk_hash == ZERO_HASH:
                chunk_content = ZeroSource(
                    self._layer_shape[layer+1].entry_cover_size
                )
            else:
                chunk_content = self.load_chunk(
                    chunk_hash, self._layer_key
                ).as_content_stream()
            chunk_content.seek(self._layer_shape[layer].entry_offset(offset))
            if layer == 0:
                break
            chunk_hash = chunk_content.read(32)
            if len(chunk_hash) != 32:
                raise ChunkError("Incomplete hash ref")
        return chunk_content

    def read_at(self, offset, size):
        if offset >= self._total_size:
            return b''
        if offset + size >= self._total_size:
            size = self._total_size - offset
        assert(size > 0)
        snippets = []
        remaining = size
        while remaining:
            read = self.get_chunk_stream(offset).read(remaining)
            assert(len(read) > 0)
            snippets.append(read)
            remaining -= len(read)
            offset += len(read)
        return b''.join(snippets)


class ChunkCacheNone:
    def __init__(self):
        pass

    def set(self, content_hash, content):
        pass

    def get(self, content_hash):
        return None

class ChunkCacheMemory:
    def __init__(self, max_cached=16):
        self._cache_keys = []
        self._cache = {}
        self._max_cached = max_cached

    def set(self, content_hash, content):
        while len(self._cache_keys) > self._max_cached:
            key = self._cache_keys.pop(0)
            del self._cache[key]
        self._cache[content_hash] = content
        self._cache_keys.append(content_hash)

    def get(self, content_hash):
        return self._cache.get(content_hash)

class ChunkLoaderFile:
    def __init__(self, path):
        self._path = path

    def open_stream(self, chunk_hash, max_size):
        return open(os.path.join(self._path, binascii.hexlify(chunk_hash).decode('utf8')), "rb")

class ChunkLoaderHTTP:
    def __init__(self, base_url):
        import requests
        self._base_url = base_url
        self._session  = requests.Session()

    def open_stream(self, chunk_hash, max_size):
        url = self._base_url._replace(path=binascii.hexlify(chunk_hash).decode('utf8')).geturl()
        r = self._session.get(url, timeout=5, stream=True, allow_redirects=True, headers={
            'Accept-Encoding': 'identity',
            'User-Agent': 'tree-chunker',
        })
        r.raise_for_status()
        if 'Content-Length' in r.headers:
            if int(r.headers.get('Content-Length')) > max_size:
                raise ChunkError('Response too large')
        return r.raw

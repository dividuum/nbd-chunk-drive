#
# Completely horrible AES wrapper using only libcrypto.so.
# For machines that don't have python crypto libs installed.
# Can only decrypt and barely so. Do not use.
#
from ctypes import (
    CDLL, POINTER, Structure, c_ubyte, c_int, c_void_p, c_size_t, pointer, addressof, byref
)

libcrypto = CDLL('libcrypto.so')
class AES_KEY(Structure):
    _fields_ = [("dummy", c_ubyte * 256)] # ugh

u16_byte_type = c_ubyte*16

AES_set_decrypt_key = libcrypto.AES_set_decrypt_key
AES_set_decrypt_key.argtypes = (POINTER(u16_byte_type), c_int, POINTER(AES_KEY))
AES_set_decrypt_key.restype = c_int

AES_cbc_encrypt = libcrypto.AES_cbc_encrypt
AES_cbc_encrypt.argtypes = (c_void_p, c_void_p, c_size_t, POINTER(AES_KEY), POINTER(u16_byte_type), c_int)
AES_cbc_encrypt.restype = None

def immutable_u16(b):
    return u16_byte_type.from_buffer_copy(b)

def mutable_ubytes(b):
    ba = bytearray(b)
    return ba, (c_ubyte*len(ba)).from_buffer(ba)

class HorribleFragileStandaloneForDecryptionOnlyAES:
    MODE_CBC = "It's me. CBC mode!"
    block_size = 16

    @classmethod
    def new(cls, key, mode, iv):
        assert(mode == cls.MODE_CBC)
        assert(len(key) == 16)
        assert(len(iv) == 16)
        return cls(key, iv)

    def __init__(self, key, iv):
        self._key_buf = immutable_u16(key)
        self._iv_buf = immutable_u16(iv)
        self._key_struct = AES_KEY()
        self._key_struct_ptr = pointer(self._key_struct)
        if AES_set_decrypt_key(byref(self._key_buf), 128, self._key_struct_ptr) != 0:
            raise ValueError("Decryption key setup failed")

    def decrypt(self, buf):
        assert(len(buf) % self.block_size == 0)
        buf_ba, buf_ubytes = mutable_ubytes(buf)
        for offset in range(0, len(buf), self.block_size):
            block_ptr = addressof(buf_ubytes) + offset
            AES_cbc_encrypt(block_ptr, block_ptr, 16, self._key_struct, self._iv_buf, 0) # 0 = decrypt
        return buf_ba

if __name__ == "__main__":
    import binascii
    key = b'0123456789012345'
    iv = b'thisis16bytesiv!'
    plain = b'aaaabbbbccccddddeeeeffffgggghhhh'

    try:
        from Cryptodome.Cipher import AES as ProperAES
        cipher = ProperAES.new(key, ProperAES.MODE_CBC, iv=iv)
        encrypted = cipher.encrypt(plain)
    except ImportError:
        encrypted = binascii.unhexlify(
            b'fcd668e9b4f02f6c1cd5df55514d3ac8852af8be8fa9228899bcb1c4dbafe663'
        )

    print(binascii.hexlify(encrypted))

    AES = HorribleFragileStandaloneForDecryptionOnlyAES

    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    plain1 = cipher.decrypt(encrypted[:16])
    print(plain1, type(plain1))
    plain2 = cipher.decrypt(encrypted[16:])
    print(plain2, type(plain2))
    assert(plain == plain1+plain2)
    print('well. that worked for some reason')

"""
Contains helper classes and methods for various encryption tasks (one or two-way.)
"""

import os

from base64 import b64encode, b64decode
from binascii import hexlify
from hashlib import sha256, pbkdf2_hmac

from Crypto import Random
from Crypto.Cipher import AES
from Crypto.Cipher._mode_cbc import CbcMode as CBCModeCipher
from Crypto.Protocol.KDF import PBKDF2

from typing import Optional, Tuple, Union

from pibble.util.strings import encode, decode

__all__ = ["Password", "AESCipher"]


class Password:
    """
    A small class providing a reasonably secure hashing methods for passwords.

    >>> from pibble.util.encryption import Password
    >>> hashed = Password.hash("password")
    >>> Password.verify(hashed, "password")
    True
    >>> Password.verify(hashed, "wrong")
    False
    """

    @staticmethod
    def hash(pwd: str) -> str:
        """
        Hashes a password, returning 128 bits of salt + hash.

        :param pwd str: The plaintext password to hash.
        :returns str: The hashed salt + password.
        """
        salt = sha256(os.urandom(60)).hexdigest().encode("ASCII")
        pwdhash = pbkdf2_hmac("sha512", pwd.encode("utf-8"), salt, 100000)
        pwdhash_hexed = hexlify(pwdhash)
        return (salt + pwdhash_hexed).decode("ASCII")

    @staticmethod
    def verify(stored: str, pwd: str) -> bool:
        """
        Verifies stored password against the hash.

        :param stored str: The stored 128-bit password.
        :param pwd str: The plaintext password.
        :returns bool: Whether or not passwords match.
        """
        salt = stored[:64]
        stored = stored[64:]
        pwdhash = pbkdf2_hmac(
            "sha512", pwd.encode("UTF-8"), salt.encode("ASCII"), 100000
        )
        pwdhash_decoded = hexlify(pwdhash).decode("ASCII")
        return pwdhash_decoded == stored


class AESCipher:
    """
    A class to encode/decode using AES256.

    Accepts a small amount of combinations of initialization parameters for various use cases.

    >>> from pibble.util.encryption import AESCipher
    >>> random_cipher = AESCipher()
    >>> random_cipher.decrypt(random_cipher.encrypt("test"))
    'test'
    >>> random_cipher_2 = AESCipher()
    >>> assert random_cipher.decrypt(random_cipher_2.encrypt("test")) != "test" # should not work
    >>> keyed_cipher = AESCipher(key = "A" * 32)
    >>> keyed_cipher.decrypt(keyed_cipher.encrypt("test"))
    'test'
    >>> keyed_cipher_2 = AESCipher(key = "A" * 32)
    >>> assert keyed_cipher.decrypt(keyed_cipher_2.encrypt("test")) == "test" # should work when using same key
    """

    BLOCK_SIZE = 16
    KEY_SIZE = 32
    SALT_SIZE = 8

    def __init__(
        self,
        password: Optional[Union[str, bytes]] = None,
        salt: Optional[Union[str, bytes]] = None,
        key: Optional[Union[str, bytes]] = None,
    ) -> None:
        """
        :param password str: If passed, will use PBKDF (Password-Based Key Derivation Function) with salt.
        :param salt str: If passed along with password, no randomness will be used. Otherwise, salt will be generated randomly. Should be 8 base64-encoded bytes.
        :param key str: If passed, must be 32 base64-encoded bytes. Otherwise, will be entirely randomly generated.
        """
        if key is None and password is None:
            self.key = self.random(self.KEY_SIZE)
        elif password is not None:
            if salt is None:
                salt = self.random(self.SALT_SIZE)
            elif type(salt) is str:
                salt = b64decode(salt)
            self.salt = encode(salt)
            self.key = PBKDF2(decode(password), self.salt, self.KEY_SIZE)
        elif key is not None:
            if type(key) is str:
                self.key = b64decode(key)
            else:
                self.key = encode(key)

    @staticmethod
    def pad(string: bytes) -> bytes:
        """
        Pads a string to cipher block size.

        The pad character is the number of bytes of padding added.

        >>> from pibble.util.encryption import AESCipher
        >>> from random import randint
        >>> string_length = randint(1, AESCipher.BLOCK_SIZE - 1)
        >>> string_to_pad = AESCipher.random(string_length)
        >>> expected_pad_length = AESCipher.BLOCK_SIZE - len(string_to_pad)
        >>> expected_pad_character = chr(expected_pad_length).encode("UTF-8")
        >>> expected_pad_string = string_to_pad + (expected_pad_character * expected_pad_length)
        >>> assert expected_pad_string == AESCipher.pad(string_to_pad)

        :param string bytes: The encoded string to pad.
        :returns bytes: The bytestring, padded with null bytes.
        """
        return string + (
            AESCipher.BLOCK_SIZE - len(string) % AESCipher.BLOCK_SIZE
        ) * bytes([(AESCipher.BLOCK_SIZE - len(string) % AESCipher.BLOCK_SIZE)])

    @staticmethod
    def unpad(string: bytes) -> bytes:
        """
        Removes padding from the end of the block.

        Must be used in conjunction with pad(), as this expects the pad
        character to be the length of the padding.

        >>> from pibble.util.encryption import AESCipher
        >>> expects_one_pad_character = b"0123456789abcde"
        >>> assert AESCipher.unpad(expects_one_pad_character + b'\x01') == expects_one_pad_character

        :param string bytes: The encoded string to unpad.
        :returns bytes: Th
        """
        return string[: -ord(string[len(string) - 1 :])]

    @staticmethod
    def random(size: int, reinitialize: bool = True) -> bytes:
        """
        Generates random bytes.

        :param size int: The number of bytes to generate.
        :returns bytes: The random byte string.
        """
        try:
            return Random.new().read(size)
        except AssertionError:
            if reinitialize:
                # Likely due to new thread
                Random.atfork()
                return AESCipher.random(size, False)
            else:
                raise

    @property
    def b64key(self) -> bytes:
        """
        Simply encodes the current key in base64. Necessary if you're going to store it later.

        >>> from pibble.util.encryption import AESCipher
        >>> from base64 import b64encode
        >>> key = AESCipher.random(AESCipher.KEY_SIZE)
        >>> assert AESCipher(key=key).b64key == b64encode(key)

        :returns str: The key, encoded in base64.
        """
        return b64encode(self.key)

    def cipher(self, iv: Optional[bytes] = None) -> Tuple[bytes, CBCModeCipher]:
        """
        Gets the cipher.

        :param iv str: The initialization vector - should be BLOCK_SIZE bytes.
        :returns tuple: A 2-tuple of [initialization vector, cipher].
        """
        if iv is None:
            iv = self.random(AES.block_size)
        return iv, AES.new(self.key, AES.MODE_CBC, iv)

    def encrypt(self, raw: str, iv: Optional[bytes] = None) -> str:
        """
        Encrypts a string and returns the base64 representation.

        >>> from pibble.util.encryption import AESCipher
        >>> iv = b'0' * AESCipher.BLOCK_SIZE
        >>> key = b'0' * AESCipher.KEY_SIZE
        >>> cipher = AESCipher(key=key)
        >>> cipher.encrypt('raw', iv=iv)
        'MDAwMDAwMDAwMDAwMDAwMFLR9bzH43Otc2e61hCvYuw='

        :param raw str: The string to encrypt.
        :param iv bytes: The intialization vector - optional.
        :returns str: The base64-encoded encrypted string.
        """
        raw_padded = self.pad(encode(raw))
        iv, cipher = self.cipher(iv)
        b64encoded = b64encode(iv + cipher.encrypt(raw_padded))
        return decode(b64encoded)

    def decrypt(self, encoded: str) -> str:
        """
        Decrypts the base64-encoded string.

        >>> from pibble.util.encryption import AESCipher
        >>> key = b'0' * AESCipher.KEY_SIZE
        >>> cipher = AESCipher(key=key)
        >>> cipher.decrypt('MDAwMDAwMDAwMDAwMDAwMFLR9bzH43Otc2e61hCvYuw=')
        'raw'

        :param encoded str: The string, base64-encoded (as returned by encrypt())
        :returns str: The decrypted string, in it's original form.
        """
        b64_decoded = b64decode(encode(encoded))
        iv = b64_decoded[:16]
        iv, cipher = self.cipher(iv)
        return decode(self.unpad(cipher.decrypt(b64_decoded[16:])))

from math import log, ceil
from typing import Union

__all__ = ["r8d2o", "o2r8d", "human_size"]


def r8d2o(value: int) -> int:
    """
    Converts a radix-8 decimal value to a proper octal value.

    Probably called exactly in one scenario - to turn octal permission values
    from decimal (e.g. 755) to octal (decimal 493, or 0o755).

    >>> from pibble.util.numeric import r8d2o
    >>> r8d2o(777)
    511
    >>> "{0:o}".format(r8d2o(777))
    '777'

    :param value: A radix-8 integer.
    """

    magnitude = ceil(log(value, 10))
    o = 0
    for i in range(1, magnitude + 1):
        n = (value // (10 ** (magnitude - i))) % 10
        o |= n << ((magnitude - i) * 3)
    return o


def o2r8d(value: int) -> int:
    """
    Converts an octal integer to its radix-8 decimal value.

    Opposite of r8d20.

    >>> from pibble.util.numeric import o2r8d
    >>> o2r8d(493)
    755
    >>> o2r8d(511)
    777
    >>> o2r8d(0o777)
    777

    :param value: An octal integer.
    """
    r8d = 0
    for i in range(ceil(value.bit_length() / 3)):
        r8d += ((value & 0b111 << (i * 3)) >> (i * 3)) * (10**i)
    return r8d


def human_size(size: Union[int, float]) -> str:
    """
    Returns a human-readable size, based on a number of bytes.

    >>> from pibble.util.numeric import human_size
    >>> human_size(42)
    '42 B'
    >>> human_size(2**10)
    '1.02 KB'
    """
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    suffix_index = 0
    while size > 1000:
        size /= 1000.0
        suffix_index += 1
    if suffix_index == 0:
        return "{0:.0f} {1:s}".format(size, suffixes[suffix_index])
    else:
        return "{0:.2f} {1:s}".format(size, suffixes[suffix_index])

from typing import Literal
from PIL import ImageColor

__all__ = ["contrast_color"]


def contrast_color(color: str) -> Literal["black", "white"]:
    """
    Given a color, return the best contrasting color
    of either black or white.

    >>> from pibble.util.imaging import contrast_color
    >>> contrast_color('#E2FFC1')
    'black'
    >>> contrast_color('#004A70')
    'white'
    """
    colors = ImageColor.getrgb(color)
    r = colors[0]
    g = colors[1]
    b = colors[2]
    return "black" if (r * 0.299 + g * 0.587 + b * 0.114) > 186 else "white"

"""
The main importchecker binary doesn't report an error,
it only outputs to the console. This modification will
properly exit with a non-zero status if importcheck
fails.
"""
import sys
import io
from importchecker.importchecker import main
from typing import Any, Union, List
from typing_extensions import Self


class OutputCatcher(io.TextIOWrapper):
    """
    This small class wrapper will intercept any print()
    or stdout/stderr.write calls to write to a memory
    buffer instead.
    """

    flushed: List[bytes]
    buf: bytes

    def __init__(self) -> None:
        self.flushed = []
        self.buf = b""

    def __enter__(self) -> Self:
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = self
        sys.stderr = self
        return self

    def empty(self) -> bool:
        return len(self.flushed) == 0 and len(self.buf) == 0

    def output(self) -> str:
        return "\r\n".join(
            [string.decode(sys.getdefaultencoding()) for string in self.flushed]
        )

    def write(self, text: Union[str, bytes]) -> int:
        if isinstance(text, str):
            text = text.encode(sys.getdefaultencoding())
        self.buf += text
        return len(text)

    def flush(self) -> None:
        if self.buf.strip():
            self.flushed.append(self.buf.strip())
            self.buf = b""

    def __exit__(self, *args: Any) -> None:
        if not self.empty():
            self.flush()
        sys.stdout = self.stdout
        sys.stderr = self.stderr


if __name__ == "__main__":
    """
    The main method will just call importchecker's main(), then
    die if there is any output that would have been produced.
    """
    catcher = OutputCatcher()
    with catcher:
        main()
    if not catcher.empty():
        sys.stderr.write(catcher.output() + "\r\n")
        sys.stderr.flush()
        sys.exit(5)
    sys.exit(0)

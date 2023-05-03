import os

from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import ProcessRunner, Assertion


def main() -> None:
    with DebugUnifiedLoggingContext():
        echo = ProcessRunner("echo")
        out, err = echo.run("$HOME")
        Assertion(Assertion.EQ)(out, "$HOME")
        if os.geteuid() == 0:
            out, err = echo.run("$HOME", shell=True)
            Assertion(Assertion.EQ)(out, "/root")
            out, err = echo.run("$HOME", shell=True, user="pibble")
            Assertion(Assertion.EQ)(out, "/home/pibble")
            out, err = echo.run("$HOME", shell=True, user="testuser")
            Assertion(Assertion.EQ)(out, "/home/testuser")
        else:
            out, err = echo.run("$HOME", shell=True)
            Assertion(Assertion.EQ)(out, "/home/pibble")


if __name__ == "__main__":
    main()

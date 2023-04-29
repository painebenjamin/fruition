import time
from typing import TypedDict

from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import Assertion


class RootResult(TypedDict):
    value: int
    root: int
    result: float


server = XMLRPCServer()


@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def add(a: int, b: int) -> int:
    """
    Adds two numbers together.
    """
    return a + b


@server.register
@server.sign_request(int)
@server.sign_request(int, int)
@server.sign_response(int)
def pow(a: int, b: int = 2) -> int:
    """
    Raises a to the power of b.
    """
    return a**b


@server.register
@server.sign_named_request(value=int, root=2)
@server.sign_named_response(value=int, root=int, result=float)
def root(value: int, root: int = 2) -> RootResult:
    """
    Returns the nth root of a value.
    """
    return {"value": value, "root": root, "result": value ** (1 / float(root))}


def main() -> None:
    with DebugUnifiedLoggingContext():
        server.configure(
            **{"server": {"driver": "werkzeug", "host": "0.0.0.0", "port": 8192}}
        )
        server.start()
        time.sleep(1)

        try:
            client = XMLRPCClient()
            client.configure(**{"client": {"host": "127.0.0.1", "port": 8192}})
            Assertion(Assertion.EQ)(
                client["system.listMethods"](),
                [
                    "system.listMethods",
                    "system.methodSignature",
                    "system.methodHelp",
                    "add",
                    "pow",
                    "root",
                ],
            )
            Assertion(Assertion.EQ)(
                client["system.methodHelp"]("add"), "Adds two numbers together."
            )
            Assertion(Assertion.EQ)(client["add"](1, 2), 3)
            Assertion(Assertion.EQ)(client.pow(2), 4)
            Assertion(Assertion.EQ)(client.pow(2, 3), 8)
            Assertion(Assertion.EQ)(
                client.root(value=4), {"value": 4, "root": 2, "result": 2.0}
            )
        finally:
            server.stop()


if __name__ == "__main__":
    main()

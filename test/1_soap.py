from typing import TypedDict

from pibble.api.client.webservice.wrapper import WebServiceAPIClientWrapper
from pibble.api.client.webservice.soap import SOAPClient
from pibble.api.server.webservice.soap import SOAPServer
from pibble.util.helpers import Assertion, Pause
from pibble.util.log import DebugUnifiedLoggingContext


class SOAPClientWrapper(SOAPClient, WebServiceAPIClientWrapper):
    pass


class PowResult(TypedDict):
    result: int
    base: int
    exponent: int


server = SOAPServer()


@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def add(a: int, b: int) -> int:
    return a + b


@server.register
@server.sign_named_request(base=int, exponent=int)
@server.sign_named_response(result=int, base=int, exponent=int)
def pow(base: int, exponent: int = 2) -> PowResult:
    return {"result": base**exponent, "base": base, "exponent": exponent}


def main() -> None:
    with DebugUnifiedLoggingContext():
        server.configure(
            server={
                "driver": "werkzeug",
                "host": "0.0.0.0",
                "port": 9091,
                "name": "Calculator",
            }
        )
        try:
            for client_class in [SOAPClientWrapper, SOAPClient]:
                if client_class is SOAPClient:
                    server.start()
                    Pause.milliseconds(100)
                client = client_class()
                client.configure(
                    client={
                        "host": "127.0.0.1",
                        "port": 9091,
                        "path": "/Calculator.wsdl",
                    },
                    server={"instance": server},
                )
                Assertion(Assertion.EQ)(client.add(1, 2), 3)
                Assertion(Assertion.EQ)(
                    client.pow(base=2, exponent=2),
                    {"result": 4, "base": 2, "exponent": 2},
                )
        finally:
            server.stop()


if __name__ == "__main__":
    main()

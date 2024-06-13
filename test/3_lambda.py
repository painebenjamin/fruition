from typing import Dict

from fruition.api.server.webservice.rpc.jsonrpc import JSONRPCServer
from fruition.api.server.webservice.awslambda import WebServiceAPILambdaServer
from fruition.api.client.webservice.rpc.jsonrpc import JSONRPCClient
from fruition.api.client.webservice.wrapper import (
    WebServiceAPIClientWrapper,
    WebServiceAPILambdaTestClientWrapper,
)

from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion


class JSONRPCLambdaTestClientWrapper(
    JSONRPCClient, WebServiceAPILambdaTestClientWrapper
):
    pass


class JSONRPCLambdaServerWrapper(JSONRPCServer, WebServiceAPILambdaServer):
    pass


server = JSONRPCLambdaServerWrapper()


@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def add(a: int, b: int) -> int:
    """
    Adds two numbers together.
    """
    return a + b


@server.register
@server.sign_named_request(base=int, exponent=2)
@server.sign_named_response(result=int)
def pow(base: int, exponent: int = 2) -> Dict[str, int]:
    """
    Raises base to the power of exponent.
    """
    return {"result": base**exponent}


def main() -> None:
    with DebugUnifiedLoggingContext():
        server.configure(
            **{"server": {"driver": "werkzeug", "host": "0.0.0.0", "port": 8192}}
        )

        server.start()

        try:
            for client_class in [JSONRPCLambdaTestClientWrapper, JSONRPCClient]:
                client = client_class()
                client.configure(
                    **{
                        "client": {"host": "127.0.0.1", "port": 8192},
                        "server": {"instance": server},
                    }
                )
                Assertion(Assertion.EQ)(
                    client["system.listMethods"](),
                    [
                        "system.listMethods",
                        "system.methodSignature",
                        "system.methodHelp",
                        "add",
                        "pow",
                    ],
                )
                Assertion(Assertion.EQ)(
                    client["system.methodHelp"]("add"), "Adds two numbers together."
                )
                Assertion(Assertion.EQ)(client["add"](1, 2), 3)
                Assertion(Assertion.EQ)(client.pow(base=2), {"result": 4})
                Assertion(Assertion.EQ)(client.pow(base=2, exponent=3), {"result": 8})
        finally:
            server.stop()


if __name__ == "__main__":
    main()

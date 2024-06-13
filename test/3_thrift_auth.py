import os
import tempfile
import socket

from fruition.api.exceptions import AuthenticationError
from fruition.api.server.apachethrift import ApacheThriftServer
from fruition.api.client.apachethrift import ApacheThriftClient
from fruition.api.middleware.apachethrift.screening import (
    ScreeningApacheThriftAPIMiddleware,
)
from fruition.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion, find_executable

TEST_SERVICE = """
namespace py FruitionThiftTest

service Calculator {
  i32 add(1:i32 num1, 2:i32 num2)
}
"""
PORT = 9091


class ApacheThriftScreeningServer(
    ApacheThriftServer, ScreeningApacheThriftAPIMiddleware
):
    pass


class ApacheThriftScreeningClient(
    ApacheThriftClient, ScreeningApacheThriftAPIMiddleware
):
    pass


class CalculatorHandler(ApacheThriftHandler):
    def add(self, num1, num2):
        return num1 + num2


def main():
    try:
        find_executable("thrift")
    except ImportError:
        return
    with DebugUnifiedLoggingContext():
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        try:
            open(tmp, "w").write(TEST_SERVICE)
            FruitionApacheThriftTest = ApacheThriftCompiler(tmp).compile()
            server = ApacheThriftScreeningServer()
            server.configure(
                **{
                    "server": {
                        "host": "0.0.0.0",
                        "port": PORT,
                        "driver": "werkzeug",
                        "allowlist": [],
                        "offlist": "reject",
                    },
                    "thrift": {
                        "service": FruitionApacheThriftTest.Calculator,
                        "types": FruitionApacheThriftTest.ttypes,
                        "handler": CalculatorHandler,
                    },
                }
            )
            server.start()
            client = ApacheThriftScreeningClient()
            client.configure(
                **{
                    "client": {"host": "127.0.0.1", "port": PORT},
                    "thrift": {
                        "types": FruitionApacheThriftTest.ttypes,
                        "service": FruitionApacheThriftTest.Calculator,
                    },
                }
            )
            with client:
                try:
                    client.add(1, 2)
                except Exception as ex:
                    Assertion(Assertion.IS)(type(ex), AuthenticationError)
            server.stop()
            server.configure(
                **{
                    "server": {
                        "allowlist": [
                            "127.0.0.1",
                            socket.gethostbyname(socket.gethostname()),
                        ]
                    }
                }
            )
            server.start()
            with client:
                Assertion(Assertion.EQ)(client.add(1, 2), 3)
        finally:
            server.stop()
            os.remove(tmp)


if __name__ == "__main__":
    main()

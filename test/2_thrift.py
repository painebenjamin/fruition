import os
import tempfile

from pibble.api.server.apachethrift import ApacheThriftServer
from pibble.api.client.apachethrift import ApacheThriftClient
from pibble.api.client.apachethrift.wrapper import (
    ApacheThriftHandlerWrapper,
    ApacheThriftClientWrapper,
)
from pibble.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler

from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import Assertion, Pause, find_executable

TEST_SERVICE = """
namespace py PibbleThiftTest

service Calculator {
  i32 add(1:i32 num1, 2:i32 num2)
}
"""
PORT = 9091


class CalculatorHandler(ApacheThriftHandler):
    def add(self, num1, num2):
        return num1 + num2


def main():
    try:
        find_executable("thrift")
    except ImportError:
        return
    with DebugUnifiedLoggingContext():
        _, tmp = tempfile.mkstemp()
        try:
            open(tmp, "w").write(TEST_SERVICE)
            PibbleThriftTest = ApacheThriftCompiler(tmp).compile()
            server = ApacheThriftServer()
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": PORT},
                    "thrift": {
                        "service": PibbleThriftTest.Calculator,
                        "types": PibbleThriftTest.ttypes,
                        "handler": CalculatorHandler,
                    },
                }
            )
            for client_class in [
                ApacheThriftHandlerWrapper,
                ApacheThriftClientWrapper,
                ApacheThriftClient,
            ]:
                if client_class is ApacheThriftClient:
                    server.start()
                    Pause.milliseconds(100)
                client = client_class()
                client.configure(
                    **{
                        "client": {"host": "127.0.0.1", "port": PORT},
                        "server": {"instance": server},
                        "thrift": {
                            "service": PibbleThriftTest.Calculator,
                            "types": PibbleThriftTest.ttypes,
                            "handler": CalculatorHandler,
                        },
                    }
                )
                with client as service:
                    Assertion(Assertion.EQ)(3, service.add(2, 1))
                server.stop()
        finally:
            os.remove(tmp)


if __name__ == "__main__":
    main()

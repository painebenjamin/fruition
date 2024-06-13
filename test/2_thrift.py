import os
import tempfile

from fruition.api.server.apachethrift import ApacheThriftServer
from fruition.api.client.apachethrift import ApacheThriftClient
from fruition.api.client.apachethrift.wrapper import (
    ApacheThriftHandlerWrapper,
    ApacheThriftClientWrapper,
)
from fruition.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler

from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion, Pause, find_executable

TEST_SERVICE = """
namespace py FruitionThiftTest

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
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        try:
            open(tmp, "w").write(TEST_SERVICE)
            FruitionThriftTest = ApacheThriftCompiler(tmp).compile()
            server = ApacheThriftServer()
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": PORT},
                    "thrift": {
                        "service": FruitionThriftTest.Calculator,
                        "types": FruitionThriftTest.ttypes,
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
                            "service": FruitionThriftTest.Calculator,
                            "types": FruitionThriftTest.ttypes,
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

import os
import tempfile

from fruition.api.client.webservice.wrapper import WebServiceAPIClientWrapper
from fruition.api.server.webservice.apachethrift import ApacheThriftWebServer
from fruition.api.client.webservice.apachethrift import ApacheThriftWebClient
from fruition.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion

TEST_SERVICE = """
namespace py FruitionThiftTest

service Calculator {
  i32 add(1:i32 num1, 2:i32 num2)
}
"""
PORT = 9091


class ApacheThriftWebClientWrapper(ApacheThriftWebClient, WebServiceAPIClientWrapper):
    pass


class CalculatorHandler(ApacheThriftHandler):
    def add(self, num1, num2):
        return num1 + num2


def main():
    with DebugUnifiedLoggingContext():
        _, tmp = tempfile.mkstemp()
        server = ApacheThriftWebServer()
        try:
            open(tmp, "w").write(TEST_SERVICE)
            FruitionApacheThriftTest = ApacheThriftCompiler(tmp).compile()
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": PORT, "driver": "werkzeug"},
                    "thrift": {
                        "service": FruitionApacheThriftTest.Calculator,
                        "types": FruitionApacheThriftTest.ttypes,
                        "handler": CalculatorHandler,
                    },
                }
            )
            server.start()
            for client_class in [ApacheThriftWebClientWrapper, ApacheThriftWebClient]:
                client = client_class()
                client.configure(
                    **{
                        "client": {"host": "127.0.0.1", "port": PORT},
                        "server": {"instance": server},
                        "thrift": {
                            "types": FruitionApacheThriftTest.ttypes,
                            "service": FruitionApacheThriftTest.Calculator,
                        },
                    }
                )
                Assertion(Assertion.EQ)(client.add(1, 2), 3)
        finally:
            server.stop()
            os.remove(tmp)


if __name__ == "__main__":
    main()

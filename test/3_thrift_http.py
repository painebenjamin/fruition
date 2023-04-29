import os
import tempfile

from pibble.api.client.webservice.wrapper import WebServiceAPIClientWrapper
from pibble.api.server.webservice.apachethrift import ApacheThriftWebServer
from pibble.api.client.webservice.apachethrift import ApacheThriftWebClient
from pibble.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import Assertion

TEST_SERVICE = """
namespace py GoodyThiftTest

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
            GoodyApacheThriftTest = ApacheThriftCompiler(tmp).compile()
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": PORT, "driver": "werkzeug"},
                    "thrift": {
                        "service": GoodyApacheThriftTest.Calculator,
                        "types": GoodyApacheThriftTest.ttypes,
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
                            "types": GoodyApacheThriftTest.ttypes,
                            "service": GoodyApacheThriftTest.Calculator,
                        },
                    }
                )
                Assertion(Assertion.EQ)(client.add(1, 2), 3)
        finally:
            server.stop()
            os.remove(tmp)


if __name__ == "__main__":
    main()

import time
import logging

from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import expect_exception, Assertion
from fruition.util.files import TempfileContext

from fruition.api.exceptions import NotFoundError
from fruition.api.client.webservice.base import WebServiceAPIClientBase
from fruition.api.server.webservice.handler import WebServiceAPIHandlerRegistry

from fruition.ext.log.server import LogAggregateServer
from fruition.ext.log.client import LogAggregateClient
from fruition.ext.log.handler import LogAggregateHandler

from webob import Request, Response

def main():
    tempfiles = TempfileContext()
    with tempfiles:
        with DebugUnifiedLoggingContext() as log_context:
            server = LogAggregateServer()

            server.configure(
                server={"host": "0.0.0.0", "port": 9090, "driver": "werkzeug"},
                authentication={"driver": "configuration", "users": {"admin": "admin"}, "encryption": "plain", "digest": {"encryption": "md5-sess"}},
                application={"directory": tempfiles.directory},
            )

            server.start()

            try:

                time.sleep(0.125)

                client = LogAggregateClient()
                client.configure(
                    client={"host": "127.0.0.1", "port": "9090"},
                    authentication={"digest":{"username": "admin", "password": "admin"}},
                    interval=0.1
                )
                client.log("Hello, World!")
                client.log("Goodbye, World!")
                client.log("Another World!", tag="other")

                # Sleep a few times to allow the server to process the logs (remember we're still one process)
                for i in range(3):
                    time.sleep(0.1)

                Assertion(Assertion.EQ)(client.read(), "Hello, World!\nGoodbye, World!")
                Assertion(Assertion.EQ)(client.read(tag="other"), "Another World!")

                # Now test the log handler
                log_context.stop()

                log_handler = LogAggregateHandler(
                    url="http://127.0.0.1:9090/",
                    interval=0.1,
                    tag="test_logger",
                    authentication="digest",
                    username="admin",
                    password="admin"
                )
                log_handler.setFormatter(logging.Formatter("%(message)s"))
                test_logger = logging.getLogger("test_logger")
                test_logger.setLevel(logging.DEBUG)
                test_logger.addHandler(log_handler)

                test_logger.debug("Hello, World!")
                test_logger.debug("Goodbye, World!")

                for i in range(3):
                    time.sleep(0.1)

                Assertion(Assertion.EQ)(client.read(tag="test_logger"), "Hello, World!\nGoodbye, World!")
            finally:
                server.stop()


if __name__ == "__main__":
    main()

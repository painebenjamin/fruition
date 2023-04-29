import os
import tempfile
import sqlalchemy
import hashlib

from pibble.api.middleware.webservice.authentication.basic import (
    BasicAuthenticationMiddleware,
)
from pibble.api.server.webservice.apachethrift import ApacheThriftWebServer
from pibble.api.client.webservice.apachethrift import ApacheThriftWebClient
from pibble.api.helpers.apachethrift import ApacheThriftHandler, ApacheThriftCompiler
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import Assertion, find_executable
from pibble.database.engine import EngineFactory

TEST_SERVICE = """
namespace py GoodyThiftTest

service Calculator {
  i32 add(1:i32 num1, 2:i32 num2)
}
"""

PORT = 9091
USERNAME = "username"
PASSWORD = "password"


class BasicAuthenticationApacheThriftWebServer(
    BasicAuthenticationMiddleware, ApacheThriftWebServer
):
    pass


class BasicAuthenticationApacheThriftWebClient(
    BasicAuthenticationMiddleware, ApacheThriftWebClient
):
    pass


# The handler that performs the logic on the thrift service.
class CalculatorHandler(ApacheThriftHandler):
    def add(self, num1, num2):
        return num1 + num2


def main():
    try:
        find_executable("thrift")
    except ImportError:
        return
    with DebugUnifiedLoggingContext():
        # Create temp files.
        _, tmp = tempfile.mkstemp()
        _, tmp2 = tempfile.mkstemp()

        try:
            # Create database, add username/password
            with EngineFactory(sqlite={"database": tmp2}) as factory:
                engine = factory.sqlite[tmp2]
                metadata = sqlalchemy.MetaData(engine)
                table = sqlalchemy.Table(
                    "users",
                    metadata,
                    sqlalchemy.Column("username", sqlalchemy.String, primary_key=True),
                    sqlalchemy.Column("password", sqlalchemy.String),
                )
                table.create()
                engine.execute(
                    table.insert().values(
                        username=USERNAME,
                        password=hashlib.md5(PASSWORD.encode("UTF-8")).hexdigest(),
                    )
                )

            # Write and compile service
            open(tmp, "w").write(TEST_SERVICE)
            GoodyApacheThriftTest = ApacheThriftCompiler(tmp).compile()

            # Create server
            server = BasicAuthenticationApacheThriftWebServer()

            # Configure the server
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": PORT, "driver": "werkzeug"},
                    "thrift": {
                        "service": GoodyApacheThriftTest.Calculator,
                        "types": GoodyApacheThriftTest.ttypes,
                        "handler": CalculatorHandler,
                    },
                    "authentication": {
                        "driver": "database",
                        "database": {
                            "type": "sqlite",
                            "connection": {"database": tmp2},
                            "table": "users",
                        },
                    },
                }
            )

            # Start the server
            server.start()

            # Create the client
            client = BasicAuthenticationApacheThriftWebClient()

            # Configure the client
            client.configure(
                **{
                    "client": {"host": "127.0.0.1", "port": PORT},
                    "thrift": {
                        "service": GoodyApacheThriftTest.Calculator,
                        "types": GoodyApacheThriftTest.ttypes,
                    },
                    "authentication": {
                        "basic": {"username": USERNAME, "password": PASSWORD}
                    },
                }
            )

            # Make a function call
            Assertion(Assertion.EQ)(client.add(1, 2), 3)

            # Stop the server
            server.stop()
        finally:
            os.remove(tmp)
            os.remove(tmp2)


if __name__ == "__main__":
    main()

import os

from sqlalchemy import (
    Table,
    MetaData,
    String,
    Column,
)

from fruition.database.engine import EngineFactory
from fruition.api.middleware.webservice.authentication.digest import (
    DigestAuthenticationMiddleware,
)
from fruition.api.server.webservice.rpc.xmlrpc import XMLRPCServer
from fruition.api.client.webservice.rpc.xmlrpc import XMLRPCClient
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion
from fruition.util.files import TempfileContext


class DigestAuthenticationXMLRPCServer(DigestAuthenticationMiddleware, XMLRPCServer):
    pass


class DigestAuthenticationXMLRPCClient(DigestAuthenticationMiddleware, XMLRPCClient):
    pass


server = DigestAuthenticationXMLRPCServer()


@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def add(a, b):
    """
    Adds two numbers together.
    """
    return a + b


@server.register
@server.sign_request(int)
@server.sign_request(int, int)
@server.sign_response(int)
def pow(a, b=2):
    """
    Raises a to the power of b.
    """
    return a**b


def main():
    with DebugUnifiedLoggingContext():
        with TempfileContext() as tempfiles:
            username = "my_username"
            password = "my_password"
            tmp = next(tempfiles)

            with EngineFactory(sqlite={"database": tmp}) as factory:
                engine = factory.sqlite[tmp]
                metadata = MetaData(engine)
                table = Table(
                    "users",
                    metadata,
                    Column("username", String, primary_key=True),
                    Column("password", String),
                )
                table.create()
                engine.execute(
                    table.insert().values(username=username, password=password)
                )

            server.configure(
                **{
                    "server": {"driver": "werkzeug", "host": "0.0.0.0", "port": 8192},
                    "authentication": {
                        "driver": "database",
                        "encryption": "plain",
                        "database": {
                            "type": "sqlite",
                            "connection": {"database": tmp},
                            "table": "users",
                        },
                        "digest": {"encryption": "md5-sess"},
                    },
                }
            )
            server.start()

            try:
                client = DigestAuthenticationXMLRPCClient()
                client.configure(
                    **{
                        "client": {"host": "127.0.0.1", "port": 8192},
                        "authentication": {
                            "digest": {"username": username, "password": password}
                        },
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
                Assertion(Assertion.EQ)(client.pow(2), 4)
                Assertion(Assertion.EQ)(client.pow(2, 3), 8)
            finally:
                server.stop()


if __name__ == "__main__":
    main()

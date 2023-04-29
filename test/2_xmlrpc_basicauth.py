import sqlite3
import hashlib

from pibble.api.middleware.webservice.authentication.basic import (
    BasicAuthenticationMiddleware,
)
from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import Assertion
from pibble.util.files import TempfileContext
from pibble.util.strings import encode


class BasicAuthenticationXMLRPCServer(BasicAuthenticationMiddleware, XMLRPCServer):
    pass


class BasicAuthenticationXMLRPCClient(BasicAuthenticationMiddleware, XMLRPCClient):
    pass


server = BasicAuthenticationXMLRPCServer()


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
        with TempfileContext() as tempgen:
            username = "user"
            password = "pass"

            passwordfile = next(tempgen)

            conn = sqlite3.connect(passwordfile)
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE users (username TEXT, password TEXT, PRIMARY KEY(username))"
            )
            conn.commit()
            cursor.execute(
                "INSERT INTO users (username, password) VALUES ('{0}','{1}')".format(
                    username, hashlib.md5(encode(password)).hexdigest()
                )
            )
            conn.commit()

            server.configure(
                **{
                    "server": {"driver": "werkzeug", "host": "0.0.0.0", "port": 8192},
                    "authentication": {
                        "driver": "database",
                        "encryption": "md5",
                        "database": {
                            "type": "sqlite",
                            "connection": {"database": passwordfile},
                            "table": "users",
                        },
                    },
                }
            )

            server.start()

            try:
                client = BasicAuthenticationXMLRPCClient()
                client.configure(
                    **{
                        "client": {"host": "127.0.0.1", "port": 8192},
                        "authentication": {
                            "basic": {"username": username, "password": password}
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

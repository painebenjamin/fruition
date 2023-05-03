import sqlite3
import os
import socket
import hashlib
import random
import string

from webob import Request, Response
from typing import Any

# Utilities
from pibble.util.log import logger, DebugUnifiedLoggingContext
from pibble.util.helpers import expect_exception
from pibble.util.files import TempfileContext
from pibble.util.strings import encode

# Shared middleware, helpers
from pibble.api.middleware.webservice.authentication.basic import (
    BasicAuthenticationMiddleware,
)
from pibble.api.exceptions import AuthenticationError

# Server
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry

# Client
from pibble.api.client.webservice.base import WebServiceAPIClientBase


def randomletters(n: int = 10) -> str:
    return "".join([random.choice(string.ascii_lowercase) for i in range(n)])


class BasicAuthenticationClient(BasicAuthenticationMiddleware, WebServiceAPIClientBase):
    pass


handlers = WebServiceAPIHandlerRegistry()


class BasicAuthenticationServer(BasicAuthenticationMiddleware, WebServiceAPIServerBase):
    @classmethod
    def get_handlers(cls) -> WebServiceAPIHandlerRegistry:
        return handlers

    @handlers.methods("GET")
    @handlers.path("^[/]{0,1}$")
    def handle(self, request: Request, response: Response) -> None:
        return

    @handlers.methods("GET")
    @handlers.path("/insecure")
    @handlers.bypass(BasicAuthenticationMiddleware)
    def insecure(self, request: Request, response: Response) -> None:
        return


class ServerContext:
    def __init__(self, configuration: dict = {}) -> None:
        if "server" not in configuration:
            configuration["server"] = {}
        configuration["server"]["host"] = "0.0.0.0"
        configuration["server"]["driver"] = "werkzeug"
        configuration["server"]["port"] = 9091
        self.server = BasicAuthenticationServer()
        self.server.configure(**configuration)

    def __enter__(self) -> BasicAuthenticationServer:
        self.server.start()
        return self.server

    def __exit__(self, *args: Any) -> None:
        self.server.stop()


def main() -> None:
    test_host = os.getenv("TEST_HOST", default=None)
    with DebugUnifiedLoggingContext():
        with TempfileContext() as tempgen:
            username = "pibble"
            password = "password"

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

            client = BasicAuthenticationClient()
            client.configure(
                **{
                    "client": {
                        "host": socket.gethostbyname(socket.gethostname()),
                        "port": 9091,
                    },
                    "authentication": {
                        "basic": {"username": username, "password": password}
                    },
                }
            )

            store_server = {
                "authentication": {
                    "encryption": "md5",
                    "driver": "database",
                    "database": {
                        "type": "sqlite",
                        "connection": {"database": passwordfile},
                        "table": "users",
                    },
                }
            }

            ldap_bind = {
                "authentication": {
                    "driver": "ldap",
                    "ldap": {
                        "host": test_host,
                        "simple": False,
                        "ou": "People",
                        "dc": None if not test_host else test_host.split("."),
                        "field": "uid",
                    },
                }
            }

            ldap_search = {
                "authentication": {
                    "driver": "ldap",
                    "ldap": {
                        "method": "search",
                        "host": test_host,
                        "simple": False,
                        "ou": "People",
                        "dc": None if not test_host else test_host.split("."),
                        "field": "uid",
                        "admin": {
                            "cn": "ldapadm",
                            "dc": None if not test_host else test_host.split("."),
                            "password": "password",
                        },
                    },
                }
            }

            unix_server = {"authentication": {"driver": "unix"}}

            rsa_server = {
                "authentication": {
                    "driver": "rsa",
                    "rsa": {"authorized": "/home/{0}/.ssh/id_rsa.pub".format(username)},
                }
            }

            tests: list[dict] = [store_server]
            names = ["database"]

            if os.name != "nt" and os.geteuid() == 0:
                tests.extend([rsa_server, unix_server])
                names.extend(["rsa_server", "unix_server"])
            else:
                logger.critical("Canot run Unix or RSA test (not root)")

            if test_host is not None:
                tests.extend([ldap_bind, ldap_search])
                names.extend(["ldap_bind", "ldap_search"])
            else:
                logger.critical("Cannot run LDAP test (no test host)")

            for name, configuration in zip(names, tests):
                logger.info(
                    "Running authentication test with source '{0}'".format(name)
                )
                logger.info(configuration)
                with ServerContext(configuration) as server:
                    if configuration is rsa_server:
                        client.configure(
                            authentication={
                                "basic": {
                                    "username": username,
                                    "password": open(
                                        "/home/{0}/.ssh/id_rsa.pub".format(username),
                                        "r",
                                    ).read(),
                                }
                            }
                        )
                    else:
                        client.configure(
                            authentication={
                                "basic": {"username": username, "password": password}
                            }
                        )
                    client.get()
                    client.configure(
                        authentication={
                            "basic": {
                                "username": randomletters(),
                                "password": randomletters(),
                            }
                        }
                    )
                    expect_exception(AuthenticationError)(client.get)
                    client.get("/insecure")


if __name__ == "__main__":
    main()

import socket

from fruition.api.exceptions import AuthenticationError

from fruition.api.server.webservice.base import WebServiceAPIServerBase
from fruition.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from fruition.api.client.webservice.base import WebServiceAPIClientBase
from fruition.api.middleware.webservice.origin import (
    CrossOriginWebServiceAPIMiddleware,
)
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import expect_exception

PORT = 9091


class OriginScreeningWebServer(CrossOriginWebServiceAPIMiddleware, WebServiceAPIServerBase):
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.path("/")
    @handlers.methods("GET")
    def emptyHandler(self, request, response):
        return


def main():
    with DebugUnifiedLoggingContext():
        server = OriginScreeningWebServer()
        try:
            server.configure(
                **{
                    "server": {
                        "host": "0.0.0.0",
                        "port": PORT,
                        "driver": "werkzeug",
                        "origin": {
                            "allowlist": [
                                "test.com",
                                ".*\.test\.com"
                            ]
                        } 
                    }
                }
            )
            server.start()
            client = WebServiceAPIClientBase()
            client.configure(**{"client": {"host": "127.0.0.1", "port": PORT}})
            expect_exception(AuthenticationError)(lambda: client.get())
            expect_exception(AuthenticationError)(lambda: client.get(headers = {"Origin": "somewhere-else.com"}))
            client.get(headers = {"Origin": "test.com"})
            client.get(headers = {"Origin": "www.test.com"})
            client.get(headers = {"Referer": "https://www.test.com/my/link"})
            server.stop()
            server.configure(
                **{
                    "server": {
                        "origin": {
                            "allow_missing": True
                        }
                    }
                }
            )
            server.start()
            client.get()
        finally:
            server.stop()


if __name__ == "__main__":
    main()

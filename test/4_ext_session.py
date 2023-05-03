import time

from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import expect_exception, Assertion
from pibble.util.files import TempfileContext

from pibble.api.exceptions import NotFoundError
from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry

from pibble.ext.session.server.base import SessionExtensionServerBase

from webob import Request, Response


class TestExtensionServer(SessionExtensionServerBase):
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.path("^/?$")
    @handlers.methods("GET")
    @handlers.format()
    def greet(self, request: Request, response: Response) -> str:
        try:
            if hasattr(request, "session"):
                return "Hello, {0}!".format(request.session["name"])
            else:
                raise Exception("Something went wrong.")
        except KeyError:
            raise NotFoundError("I don't know your name!")

    @handlers.methods("GET")
    @handlers.path("^/(?P<name>\w+)$")
    def set_name(self, request: Request, response: Response, name: str) -> None:
        request.session["name"] = name
        response.status_code = 301
        response.location = "/"


def main():
    with TempfileContext() as temp:
        with DebugUnifiedLoggingContext():
            database = next(temp)
            server = TestExtensionServer()
            server.configure(
                server={"host": "0.0.0.0", "port": 9090, "driver": "werkzeug"},
                orm={"type": "sqlite", "connection": {"database": database}},
            )

            server.start()

            try:

                time.sleep(0.125)

                client = WebServiceAPIClientBase()
                client.configure(client={"host": "127.0.0.1", "port": "9090"})

                expect_exception(NotFoundError)(client.get)
                Assertion(Assertion.EQ)(client.get("/Billy").text, "Hello, Billy!")
                Assertion(Assertion.EQ)(client.get().text, "Hello, Billy!")

                client2 = WebServiceAPIClientBase()
                client2.configure(client={"host": "127.0.0.1", "port": "9090"})

                expect_exception(NotFoundError)(client2.get)

                Assertion(Assertion.EQ)(client2.get("/Bobby").text, "Hello, Bobby!")
                Assertion(Assertion.EQ)(client2.get().text, "Hello, Bobby!")
                Assertion(Assertion.NEQ)(client.get().text, client2.get().text)

            finally:
                server.stop()


if __name__ == "__main__":
    main()

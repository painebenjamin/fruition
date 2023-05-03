import os
import tempfile
import shutil
import socket

from pibble.util.helpers import expect_exception, ignore_exceptions, Assertion
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.api.exceptions import NotFoundError
from pibble.api.exceptions import PermissionError
from pibble.api.server.webservice.template import (
    TemplateServer,
    TemplateServerHandlerRegistry,
)
from pibble.api.client.webservice.base import WebServiceAPIClientBase


class TestTemplateServer(TemplateServer):
    handlers = TemplateServerHandlerRegistry()

    @handlers.reverse("Base", "/base.html")
    @handlers.methods("GET")
    @handlers.template("context.html.j2")
    @handlers.path("/base.html")
    def base(self, request, response):
        return {"context": "success", "url": self.resolve("Base")}

    @handlers.template("no-template.html.j2")
    @handlers.path("/none")
    @handlers.methods("GET")
    def this_will_error(self, request, response):
        return {}

    @handlers.path("/error_404")
    @handlers.methods("GET")
    def error_404(self, request, response):
        raise NotFoundError()

    @handlers.path("/error_403")
    @handlers.methods("GET")
    def error_403(self, request, response):
        raise PermissionError()

    @handlers.errors(404)
    @handlers.methods("GET")
    @handlers.template("context.html.j2")
    def error_404_response(self, request, response):
        return {"context": "error"}


def main() -> None:
    with DebugUnifiedLoggingContext():
        server = TestTemplateServer()
        tempdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tempdir, "context.html.j2"), "w") as template_file:
                template_file.write("{{ context }}{{ url }}")

            server.configure(
                server={
                    "host": "0.0.0.0",
                    "port": 9091,
                    "driver": "werkzeug",
                    "template": {"directories": [tempdir]},
                }
            )
            server.start()

            client = WebServiceAPIClientBase()
            client.configure(
                client={
                    "host": socket.gethostbyname(socket.gethostname()),
                    "port": 9091,
                }
            )

            Assertion(Assertion.EQ)(client.get("/base.html").text, "success/base.html")
            Assertion(Assertion.EQ)(
                client.get("/error_404", raise_status=False).text, "error"
            )
            expect_exception(PermissionError)(lambda: client.get("/error_403"))
            expect_exception(Exception)(lambda: client.get("/none"))

        finally:
            ignore_exceptions(server.stop)
            shutil.rmtree(tempdir)


if __name__ == "__main__":
    main()

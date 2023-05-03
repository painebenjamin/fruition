import tempfile
import os

from webob import Request, Response

from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.client.webservice.wrapper import WebServiceAPIClientWrapper
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.strings import random_string
from pibble.util.helpers import Assertion, Pause
from pibble.util.files import TempfileContext

class TestServer(WebServiceAPIServerBase):
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.methods("GET")
    @handlers.path("^/download$")
    @handlers.download()
    def download_test_file(self, request: Request, response: Response) -> str:
        _, path = tempfile.mkstemp()
        with open(path, "w") as fh:
            fh.write(self.configuration.get("contents"))
        return path


def main() -> None:
    context = TempfileContext()
    random_contents = "\n".join([random_string() for i in range(10)])
    with context as tempfile_generator:
        with DebugUnifiedLoggingContext():
            server = TestServer()
            server.configure(
                contents=random_contents,
                server={"driver": "werkzeug", "host": "0.0.0.0", "port": 8192},
            )

            try:
                for client_class in [
                    WebServiceAPIClientWrapper,
                    WebServiceAPIClientBase,
                ]:
                    if client_class is WebServiceAPIClientBase:
                        server.start()
                        Pause.milliseconds(100)
                    client = client_class()
                    client.configure(
                        client={"host": "127.0.0.1", "port": 8192},
                        server={"instance": server},
                    )
                    path = client.download(
                        "GET", "download", directory=context.directory
                    )
                    Assertion(Assertion.EQ)(
                        open(os.path.join(context.directory, path), "r").read(),
                        random_contents,
                    )
                    os.remove(path)
            finally:
                server.stop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import time
import sys
import lxml.etree as ET
import multiprocessing

from werkzeug.serving import run_simple
from webob import Request, Response
from selenium.webdriver.common.by import By
from lxml.builder import E

from pibble.web.scraper import WebScraper
from pibble.util.helpers import Assertion
from pibble.util.log import DebugUnifiedLoggingContext

from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication, WSGIEnvironment, StartResponse

# we don't use the platform API structure, we'll just make a quick
# WSGI app and serve it with werkzeug.


def application(
    environ: WSGIEnvironment, start_response: StartResponse
) -> Iterable[bytes]:

    request = Request(environ)
    response = Response()
    response.status_code = 200
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "Access-Control-Allow-Origin"
    response.headers[
        "Access-Control-Allow-Headers"
    ] = "Origin, X-Requested-Width, Content-Type, Accept, Authorization, X-CSRFToken"

    if request.method == "OPTIONS":
        return response(environ, start_response)
    elif request.method != "GET":
        response.status_code = 405
        return response(environ, start_response)

    response.content_type = "text/html"
    response.content_type_params["charset"] = sys.getdefaultencoding()
    response.body = ET.tostring(
        E.html(
            E.head(
                E.script(
                    "body_on_load = function(){document.getElementById('event').innerHTML = 'event'; }"
                )
            ),
            E.body(
                E.div("static", id="static"),
                E.div("static", id="dynamic"),
                E.div("static", id="event"),
                E.script("document.getElementById('dynamic').innerHTML = 'dynamic';"),
                onload="body_on_load()",
            ),
        )
    )
    return response(environ, start_response)


class ServerProcess(multiprocessing.Process):
    def __init__(self, host: str, port: int, application: WSGIApplication):
        super(ServerProcess, self).__init__()
        self.host = host
        self.port = port
        self.application = application

    def run(self) -> None:
        run_simple(self.host, int(self.port), self.application)


def main() -> None:
    with DebugUnifiedLoggingContext():
        server = ServerProcess("0.0.0.0", 9090, application)
        server.start()
        time.sleep(0.125)
        try:
            with WebScraper() as scraper:
                scraper.get("http://localhost:9090/")

                static = scraper.find_element(By.CSS_SELECTOR, "div#static")
                dynamic = scraper.find_element(By.CSS_SELECTOR, "div#dynamic")
                event = scraper.find_element(By.CSS_SELECTOR, "div#event")

                Assertion(Assertion.EQ)(static.text, "static")
                Assertion(Assertion.EQ)(dynamic.text, "dynamic")
                Assertion(Assertion.EQ)(event.text, "event")
        finally:
            server.terminate()


if __name__ == "__main__":
    main()

import math
import datetime
import logging

from webob import Request, Response

from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.api.middleware.webservice.limit import RateLimitedWebServiceAPIMiddleware
from pibble.util.log import LevelUnifiedLoggingContext, logger
from pibble.util.helpers import Assertion


class RateLimitedServer(RateLimitedWebServiceAPIMiddleware, WebServiceAPIServerBase):
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.methods("GET")
    @handlers.path("^/$")
    def download_test_file(self, request: Request, response: Response) -> None:
        response.text = "Well done."


class RateLimitedClient(RateLimitedWebServiceAPIMiddleware, WebServiceAPIClientBase):
    pass


RATE_LIMIT = 100


def main() -> None:
    with LevelUnifiedLoggingContext(logging.INFO):
        server = RateLimitedServer()
        server.configure(
            server={
                "driver": "werkzeug",
                "host": "0.0.0.0",
                "port": 8192,
                "rate": {"limit": RATE_LIMIT, "period": 1},
            }
        )
        server.start()

        try:
            client = RateLimitedClient()
            client.configure(client={"host": "127.0.0.1", "port": 8192})

            requests_per_second = [0] * 5
            time_start = datetime.datetime.now()
            seconds_elapsed = 0.0

            while seconds_elapsed < 5:
                index = math.floor(seconds_elapsed)
                requests_per_second[index] += 1
                client.get()
                seconds_elapsed = (datetime.datetime.now() - time_start).total_seconds()

            logger.info(f"Final requests are {requests_per_second}")

            for rps in requests_per_second:
                Assertion(Assertion.LTE)(rps, RATE_LIMIT)
        finally:
            server.stop()


if __name__ == "__main__":
    main()

import datetime
from typing import Optional, Union

from requests import (
    Request as RequestsRequest,
    Response as RequestsResponse,
)
from webob import (
    Request as WebobRequest,
    Response as WebobResponse,
)
from pibble.api.helpers.wrappers import (
    RequestWrapper,
    ResponseWrapper,
)

from pibble.util.helpers import Pause
from pibble.util.log import logger
from pibble.api.exceptions import TooManyRequestsError
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase


class RateLimitedWebServiceAPIMiddleware(WebServiceAPIMiddlewareBase):
    """
    This middleware allows servers to limit the number of requests that can come
    through at any given time.

    It also allows a client to extend it, and if so, it can wait for the reset before
    trying again.
    """

    rate_reset: datetime.datetime
    rate_quota: int
    rate_limit: int
    rate_period: int

    def on_configure(self) -> None:
        """
        On configuration, initialize rate quotas.
        """
        self.rate_limit = self.configuration.get("server.rate.limit", 60)
        self.rate_period = self.configuration.get("server.rate.period", 60)

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        If we're running a server, set our current quota and reset time.

        If we're running a client, and we've been given a `429`,
        see if we know when to wait until. If so, wait, then try.
        """
        if isinstance(response, WebobResponse) or isinstance(response, ResponseWrapper):
            if self.rate_limit <= 0:
                return  # Unmetered
            now = datetime.datetime.now()
            if not hasattr(self, "rate_reset") or self.rate_reset < now:
                self.rate_reset = now + datetime.timedelta(seconds=self.rate_period)
                self.rate_quota = self.rate_limit
            self.rate_quota -= 1
            if self.rate_quota <= 0:
                raise TooManyRequestsError()
        elif isinstance(response, RequestsResponse):
            if response.status_code == 429 and "X-RateLimit-Reset" in response.headers:
                reset_time = datetime.datetime.fromisoformat(
                    response.headers["X-RateLimit-Reset"]
                )
                logger.info(f"Pausing until {reset_time}")
                Pause.until(reset_time)
                self.retry = True

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        If we're running a server, pass rate limit data in headers of all responses.
        """
        if isinstance(response, WebobResponse) or isinstance(response, ResponseWrapper):
            if hasattr(self, "rate_quota"):
                response.headers["X-RateLimit-Remaining"] = max([self.rate_quota, 0])
                response.headers["X-RateLimit-Reset"] = self.rate_reset.isoformat()

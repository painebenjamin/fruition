import re
from typing import Optional, Union
from urllib.parse import urlparse
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

from pibble.api.exceptions import AuthenticationError
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase
from pibble.util.log import logger


class CrossOriginWebServiceAPIMiddleware(WebServiceAPIMiddlewareBase):
    """
    Extends the base WebServiceAPIMiddlewareBase to read origins from requests
    and send necessary headers to permit or disallow requests.
    """

    def on_configure(self) -> None:
        self.origins = self.configuration.get("server.origin.allowlist", [])
        self.allow_missing = self.configuration.get(
            "server.origin.allow_missing", False
        )

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        if isinstance(request, WebobRequest) or isinstance(request, RequestWrapper):
            origin: Optional[str] = None
            if "Origin" in request.headers:
                origin = request.headers["Origin"]
            elif "Referer" in request.headers:
                origin = request.headers["Referer"]
            elif not self.allow_missing:
                raise AuthenticationError(
                    "Your request does not indicate where it came from, and network policy rejects unknown origins."
                )
            if origin is not None:
                if "/" in origin:
                    origin = urlparse(origin).netloc
                for allowed_origin in self.origins:
                    if re.match(allowed_origin, origin):
                        return
                logger.warning(
                    f"Request received from {origin}, but this is not in the list of allowed origins. Screening request."
                )
                raise AuthenticationError(
                    "Your request was screened by network policy."
                )

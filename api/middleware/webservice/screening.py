import ipaddress

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

from pibble.util.log import logger
from pibble.api.exceptions import AuthenticationError
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase
from pibble.api.middleware.screening import ScreeningAPIMiddlewareBase


class ScreeningWebServiceAPIMiddleware(
    WebServiceAPIMiddlewareBase, ScreeningAPIMiddlewareBase
):
    """
    Extends the base ScreeningAPIMiddlewareBase to get necessary details
    from requests.
    """

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        if isinstance(request, WebobRequest) or isinstance(request, RequestWrapper):
            peer = ipaddress.IPv4Address(request.remote_addr)
            if any([peer in network for network in self.blocklist]):
                logger.warning(
                    f"Request from {request.remote_addr} on blocklist, rejecting."
                )
                raise AuthenticationError(
                    "Your request was screened by network policy."
                )
            if any([peer in network for network in self.allowlist]):
                return
            if self.offlist == "reject":
                logger.warning(
                    f"Request from {request.remote_addr} not on allowlist, and offlist policy is rejection."
                )
                raise AuthenticationError(
                    "Your request was screened by network policy."
                )

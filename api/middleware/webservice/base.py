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
from pibble.api.middleware.base import APIMiddlewareBase


class WebServiceAPIMiddlewareBase(APIMiddlewareBase):
    """
    A base class for webservice middleware.

    When used with a client, middleware will ``prepare`` requests, and ``parse`` responses.
    When used with a server, middleware will ``parse`` requests, and ``prepare`` responses.

    Implementing classes can pass on either or both of these options, effectively making them non-active middleware.

    Classes that utilize middleware should be aware that method
    resolution order is ***not reliable*** unless strictly enforced
    during object creation - it's generally safer to assume there
    is no specific order in which these requests are performed, but
    ***all*** ``prepare()`` and ``parse()`` methods will be ran.
    """

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        pass

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        pass

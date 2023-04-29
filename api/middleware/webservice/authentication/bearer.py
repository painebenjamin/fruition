from typing import Optional, Union

from webob import (
    Request as WebobRequest,
    Response as WebobResponse,
)
from requests.models import (
    Request as RequestsRequest,
    Response as RequestsResponse,
)
from pibble.api.helpers.wrappers import (
    RequestWrapper,
    ResponseWrapper,
)

from pibble.api.exceptions import AuthenticationError
from pibble.api.helpers.authentication import APIAuthenticationSource
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase
from pibble.api.middleware.webservice.authentication.header import AuthorizationHeader


class TokenAuthenticationMiddleware(WebServiceAPIMiddlewareBase):
    """
    Middleware for token HTTP authentication.

    This is generic, mostly for use by clients to pass along tokens in requests.
    """

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        Used to parse a request object for servers.

        :param request webob.Request: The request. This can also be a :class:`requests.models.Request`, in which case we pass.
        :param response webob.Response: The prepared response. We don't bother with it here.
        :raises TypeError: When passed an unparseable object.
        :raises pibble.api.exceptions.AuthenticationError: When authentication is missing or incorrect.
        :raises pibble.api.exceptions.ConfigurationError: When unable to determine source of authentication data.
        """
        if isinstance(request, WebobRequest) or isinstance(request, RequestWrapper):
            """
            Server code. First ascertain source of authentication data, then perform checks.
            """
            if not hasattr(self, "authentication_source"):
                self.authentication_source = APIAuthenticationSource(self.configuration)
            try:
                try:
                    authorization = AuthorizationHeader(request)
                    if authorization.method != "Basic":
                        raise AuthenticationError(
                            "Incorrect authentication type - must be 'Basic', got '{0}'.".format(
                                authorization.method
                            )
                        )
                    self.authentication_source.validate(
                        authorization.username, authorization.password
                    )
                except ValueError:
                    raise AuthenticationError(
                        "Could not parse username and password from Authorization header."
                    )
            except AuthenticationError as ex:
                if isinstance(response, WebobResponse) or isinstance(
                    response, ResponseWrapper
                ):
                    response.headers["WWW-Authenticate"] = "Basic realm={0}".format(
                        self.configuration.get(
                            "authentication.basic.realm", "Authentication Required"
                        )
                    )
                raise

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        Used to prepare a request for clients.

        :param request requests.models.Request: The request. This can also be a :class:`webob.Request`, in which case we pass.
        :param response requests.models.Response: The response. This should be None when using a client.
        :raises pibble.api.exceptions.ConfigurationError: When username and/or password are not configured.
        """
        if isinstance(request, RequestsRequest):
            """
            Client code. Gather token and token type from configuration, and encode it.
            """

            token_type = self.configuration.get("authentication.token.type", None)
            token = self.configuration["authentication.token.value"]
            header_value = token if not token_type else f"{token_type} {token}"
            request.headers["Authorization"] = header_value

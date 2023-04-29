from typing import Optional, Union

from webob import (
    Request as WebobRequest,
    Response as WebobResponse,
)
from requests import (
    Request as RequestsRequest,
    Response as RequestsResponse,
)
from pibble.api.helpers.wrappers import (
    RequestWrapper,
    ResponseWrapper,
)
from requests.auth import HTTPBasicAuth

from pibble.api.helpers.authentication import APIAuthenticationSource
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase
from pibble.api.middleware.webservice.authentication.header import AuthorizationHeader
from pibble.api.exceptions import AuthenticationError, ConfigurationError


class BasicAuthenticationMiddleware(WebServiceAPIMiddlewareBase):
    """
    Middleware for basic HTTP authentication.

    This is not marvelously secure, so should be used sparingly. The gist is:
      * Requests ***must*** come in with an `Authentication` header in the form of `Basic: <credentials>`, where `<credentials>` is a base64-encoded, comma-delimited string of `username:password`.
      * Responses, when authentication error occurs, response with a `WWW-Authenticate` header indicating the ***realm*** of the authentication, e.g., `WWW-Authenticate: realm=secured`.

    The source of the username/password data is configurable. Options are:
      1. `htpasswd`. This is a file created using the command-line `htpasswd` tool, where there is one entry per line in the form of `username:<encrypted-password>`. The encrypted password is in one of two formats: md5 (default), or bcrypt. When using bcrypt, you can also specify the compute time for bcrypt to a number between 4 and 31, with 5 being the default.
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
                if isinstance(response, WebobResponse):
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
            Client code. Gather username and password from configuration, and encode it.
            """
            try:
                request.auth = HTTPBasicAuth(
                    self.configuration.get("authentication.basic.username"),
                    self.configuration.get("authentication.basic.password"),
                )
            except KeyError as ex:
                raise ConfigurationError(str(ex))

import grpc
import datetime

from pibble.api.middleware.googlerpc.base import GRPCAPIMiddlewareBase
from pibble.api.helpers.googlerpc import GRPCRequest, GRPCService
from pibble.api.meta.base import MetaService
from pibble.api.exceptions import ConfigurationError


class GRPCOAuthAuthenticationMiddleware(GRPCAPIMiddlewareBase):
    """
    A middleware class for OAuth authentication on GRPC clients.

    Since the OAuth standard doesn't allow for non-HTTP requests, we maintain
    a separate channel that ensures a valid access token is included in all requests.

    Required configuration is the same as standard OAuth required configuration, but
    also `authentication.client`, which points toward the base HTTP endpoint. Usually
    this will be an endpoint for validating a token, i.e., a /me endpoint.
    """

    service: GRPCService
    address: str

    def prepare(self, request: GRPCRequest) -> None:
        """
        This is called when a client is prepared to make a request.

        We make sure the authentication client exists. If it doesn't, we make it, then
        use it to get the token. We then ensure the channel credentials are properly
        instantiated.

        :param request pibble.api.helpers.grpc.GRPCRequest: The request object.
        """
        if getattr(self, "_grpc_authentication_client", None) is None:
            self._grpc_authentication_client = MetaService(
                "GRPCAuthenticationClient",
                [
                    "pibble.api.client.webservice.base.WebServiceAPIClientBase",
                    "pibble.api.middleware.webservice.authentication.oauth.OAuthAuthenticationMiddleware",
                ],
                {
                    "authentication": self.configuration["authentication"],
                    "client": self.configuration["authentication.client"],
                    "session": self.configuration.get("session", None),
                },
            )
            self._grpc_authentication_client.get()

        token = self._grpc_authentication_client._instance().GetOAuthTokenData()
        if token["expires_at"] <= datetime.datetime.now():
            self._grpc_authentication_client.get()
            token = self._grpc_authentication_client._instance().GetOAuthTokenData()

        if token["access_token"] != getattr(self, "_grpc_last_oauth_token", None):
            if not self.configuration.get("client.secure", False):
                raise ConfigurationError(
                    "Cannot use OAuth credentials over an insecure channel."
                )

            credentials = grpc.composite_channel_credentials(
                grpc.ssl_channel_credentials(),
                grpc.access_token_call_credentials(token["access_token"]),
            )

            self.channel = grpc.secure_channel(self.address, credentials)
            self.client = self.service.stub(self.channel)

            self._grpc_last_oauth_token = token["access_token"]

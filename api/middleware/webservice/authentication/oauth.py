import datetime
import datetime

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

from requests_oauthlib import OAuth1Session
from requests_oauthlib import OAuth2Session

# from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2 import LegacyApplicationClient
from oauthlib.oauth2 import BackendApplicationClient


from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase

from pibble.api.helpers.store import APISessionStore

from pibble.api.exceptions import (
    AuthorizationError,
    ConfigurationError,
)

from pibble.util.strings import Serializer
from pibble.util.log import logger


class OAuthAuthenticationMiddleware(WebServiceAPIMiddlewareBase):
    """
    Middleware for OAuth authentication.

    This is a meta-class for implementation by OAuth1 and OAuth 2.

    Using OAuth authentication **requires** some state to be stored by API clients, which mostly violates our stateless design.
    So, to minimialize the impact this has, we use the session store to hold tokens. When dealing with resource holder authorization, you need a callback address using the same session store as the client.

    See the extended documentation for details on how to achieve this.
    """

    session: APISessionStore
    requests_session: Union[OAuth1Session, OAuth2Session]

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        if isinstance(request, WebobRequest):
            """
            Server code. Currently unimplemented.
            """
            raise NotImplementedError()

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        if isinstance(request, RequestsRequest) and isinstance(
            response, RequestsResponse
        ):
            if self.session is None:
                raise ConfigurationError(
                    "A session state store is required for OAuth authentication flows."
                )
            try:
                oauth_version = int(
                    self.configuration.get("authentication.oauth.version")
                )
                if oauth_version == 1:
                    self.OAuth1ClientAuthentication(request, response)
                elif oauth_version == 2:
                    grant_type = self.configuration.get(
                        "authentication.oauth.grant_type", "authorization_code"
                    ).lower()
                    if grant_type == "authorization_code":
                        self.OAuth2ClientWebAuthentication(request, response)
                    elif grant_type == "password":
                        self.OAuth2ClientLegacyAuthentication(request, response)
                    elif grant_type == "client_credentials":
                        self.OAuth2ClientBackendAuthentication(request, response)
                    else:
                        raise ConfigurationError(
                            "Unknown or unimplemented OAuth2 grant type '{0}'.".format(
                                grant_type
                            )
                        )
                else:
                    raise ConfigurationError("OAuth version must be 1 or 2.")
            except KeyError as ex:
                raise ConfigurationError(str(ex))
            access_token = self.session.get("oauth_access_token", None)
            if access_token is not None:
                request.headers["Authorization"] = "{0} {1}".format(
                    self.session.get("oauth_token_type", "Bearer"), access_token
                )

    def OAuth1ClientAuthentication(
        self, request: RequestsRequest, response: RequestsResponse
    ) -> None:
        """
        OAuth1 client authentication flow.

        States:
          0. cast session.
          1. generate request token.
          2. generate authorization url, waiting on authorization
          3. generate access token.
          99. authorized.
        """

        if (
            type(self.requests_session) is not OAuth1Session
            or "oauth_state" not in self.session
        ):
            state = 0
            self.session["oauth_state"] = 0
        else:
            state = int(self.session["oauth_state"])

        if state == 99:
            logger.debug("OAuth1 session already authorized, continuing.")
            return

        elif state == 3:
            logger.debug("OAuth1 fetching access token.")
            self.requests_session.fetch_access_token(
                self.configuration["authentication.oauth.access_token_url"]
            )
            self.session["oauth_access_token"] = self.requests_session.token[
                "oauth_token"
            ]
            self.session["oauth_access_token_secret"] = self.requests_session.token[
                "oauth_token_secret"
            ]
            self.session["oauth_state"] = 99

            del self.session["oauth_authorization_response"]

            return

        elif state == 2:
            logger.debug("OAuth1 generating authorization URL.")
            if "oauth_authorization_response" in self.session:
                self.requests_session.parse_authorization_response(
                    self.session["oauth_authorization_response"]
                )
                self.session["oauth_state"] = 3
                return self.OAuth1ClientAuthentication(request, response)
            else:
                raise AuthorizationError(
                    self.requests_session.authorization_url(
                        self.configuration["authentication.oauth.authorization_url"]
                    )
                )

        elif state == 1:
            logger.debug("OAuth1 fetching request token.")
            self.requests_session.fetch_request_token(
                self.configuration["authentication.oauth.request_token_url"]
            )
            self.session["oauth_state"] = 2
            return self.OAuth1ClientAuthentication(request, response)

        elif state == 0:
            logger.debug("OAuth1 initializing session.")

            if "oauth_authorization_response" in self.session:
                del self.session["oauth_authorization_response"]

            access_token = self.session.get("oauth_access_token", None)
            access_token_secret = self.session.get("oauth_access_token_secret", None)

            self.requests_session = OAuth1Session(
                self.configuration["authentication.oauth.client_key"],
                self.configuration["authentication.oauth.client_secret"],
                resource_owner_key=access_token,
                resource_owner_secret=access_token_secret,
                callback_uri=self.configuration.get(
                    "authentication.oauth.redirect_url", None
                ),
            )

            if access_token is not None and access_token_secret is not None:
                logger.info(
                    "OAuth1 found stored access information, will set authentication to re-use credentials."
                )
                # Existing access token loaded, don't go down waterfall.
                self.session["oauth_state"] = 99
                return

            else:
                self.session["oauth_state"] = 1
                return self.OAuth1ClientAuthentication(request, response)
        else:
            # Unknown state, reset to 0.
            logger.error("OAuth1 unknown state '{0}', resetting to 0.".format(state))
            self.session["oauth_state"] = 0
            return self.OAuth1ClientAuthentication(request, response)

    def OAuth2ClientWebAuthentication(
        self, request: RequestsRequest, response: RequestsResponse
    ) -> None:
        """
        OAuth2 Web Application (authorization_code) flow.

        States:
          0. cast session.
          1. generate authorization url, waiting on authorization
          2. generate access token.
          99. authorized.
        """

        if (
            type(self.requests_session) is not OAuth2Session
            or "oauth_state" not in self.session
        ):
            state = 0
            self.session["oauth_state"] = 0
        else:
            state = int(self.session["oauth_state"])

        logger.debug(
            "OAuth2 (authorization_code) processing called with state {0}.".format(
                state
            )
        )

        if state == 99:
            # Already authorized
            refresh_token = self.session.get("oauth_refresh_token", None)
            expires_at = self.session.get(
                "oauth_expires_at",
                datetime.datetime.now() - datetime.timedelta(seconds=30),
            )

            if not isinstance(expires_at, datetime.datetime):
                expires_at = Serializer.deserialize(expires_at)

            if expires_at <= datetime.datetime.now() and refresh_token:
                logger.debug("OAuth2 (authorization_code) expired, refreshing.")
                refreshed = self.requests_session.refresh_token(
                    self.configuration.get("authentication.oauth.refresh_url", None),
                    client_id=self.configuration["authentication.oauth.client_id"],
                    client_secret=self.configuration[
                        "authentication.oauth.client_secret"
                    ],
                )
                self.OAuth2TokenSaver(refreshed)
            logger.debug("OAuth2 (authorization_code) already authorized, continuing.")
            return

        elif state == 2:
            # Get access token

            logger.debug("OAuth2 (authorization_code) generating access token.")

            access_token = self.requests_session.fetch_token(
                self.configuration["authentication.oauth.access_token_url"],
                client_secret=self.configuration.get(
                    "authentication.oauth.client_secret", None
                ),
                authorization_response=self.session["oauth_authorization_response"],
            )

            del self.session["oauth_authorization_response"]
            del self.session["oauth_authorization_url"]

            self.OAuth2TokenSaver(access_token)
            self.session["oauth_state"] = 99
            return

        elif state == 1:
            if "oauth_authorization_response" in self.session:
                logger.debug("OAuth2 (authorization_code) received callback.")
                self.session["oauth_state"] = 2
                return self.OAuth2ClientWebAuthentication(request, response)
            elif "oauth_authorization_url" in self.session:
                logger.warning(
                    "OAuth2 (authorization_code) received follow-up request while still waiting on callback."
                )
                raise AuthorizationError(self.session["oauth_authorization_url"])

            else:
                logger.debug(
                    "Oauth2 (authorization_code) generating authorization URL."
                )
                authorization_url, state = self.requests_session.authorization_url(
                    self.configuration["authentication.oauth.authorization_url"],
                    **self.configuration.get(
                        "authentication.oauth.authorization_kwargs", {}
                    )
                )
                self.session["oauth_authorization_state"] = state
                self.session["oauth_authorization_url"] = authorization_url
                raise AuthorizationError(authorization_url)

        elif state == 0:
            if "oauth_authorization_response" in self.session:
                del self.session["oauth_authorization_response"]
            if "oauth_authorization_url" in self.session:
                del self.session["oauth_authorization_url"]

            logger.debug("OAuth2 (authorization_code) initializing session.")

            access_token = self.session.get("oauth_access_token", None)
            refresh_token = self.session.get("oauth_refresh_token", None)
            token_type = self.session.get("oauth_token_type", "Bearer")
            expires_at = self.session.get(
                "oauth_expires_at",
                datetime.datetime.now() - datetime.timedelta(seconds=30),
            )

            if not isinstance(expires_at, datetime.datetime):
                expires_at = Serializer.deserialize(expires_at)
            expires_in = int((expires_at - datetime.datetime.now()).total_seconds())

            if access_token is not None:
                logger.info(
                    "OAuth2 (authorization_code) found stored access information, will set authentication to re-use credentials."
                )

                token = {"access_token": access_token, "token_type": token_type}

                if refresh_token is not None:
                    token["refresh_token"] = refresh_token
                    token["expires_in"] = expires_in

                self.session["oauth_state"] = 99

            else:
                token = None
                self.session["oauth_state"] = 1

            self.requests_session = OAuth2Session(
                self.configuration["authentication.oauth.client_id"],
                redirect_uri=self.configuration.get(
                    "authentication.oauth.redirect_url", None
                ),
                auto_refresh_url=self.configuration.get(
                    "authentication.oauth.refresh_url", None
                ),
                scope=self.configuration.get("authentication.oauth.scope", None),
                token_updater=self.OAuth2TokenSaver,
                token=token,
                auto_refresh_kwargs=self.configuration.get(
                    "authentication.oauth.refresh_kwargs", {}
                ),
            )

            return self.OAuth2ClientWebAuthentication(request, response)

        else:
            # Unknown state, reset to 0.
            logger.error(
                "OAuth2 (authorization_code) unknown state '{0}', resetting to 0.".format(
                    state
                )
            )
            self.session["oauth_state"] = 0
            return self.OAuth2ClientWebAuthentication(request, response)

    def OAuth2ClientLegacyAuthentication(
        self, request: RequestsRequest, response: RequestsResponse
    ) -> None:
        """
        OAuth2 Legacy (password) authentication flow.

        No states.
        """

        if type(self.requests_session) is not OAuth2Session:
            logger.info("OAuth2 (password) initializing authentication.")

            self.requests_session = OAuth2Session(
                client=LegacyApplicationClient(
                    client_id=self.configuration["authentication.oauth.client_id"]
                )
            )
            self.requests_session.fetch_token(
                token_url=self.configuration["authentication.oauth.access_token_url"],
                username=self.configuration["authentication.oauth.username"],
                password=self.configuration["authentication.oauth.password"],
                client_id=self.configuration["authentication.oauth.client_id"],
                client_secret=self.configuration["authentication.oauth.client_secret"],
            )

    def OAuth2ClientBackendAuthentication(
        self, request: RequestsRequest, response: RequestsResponse
    ) -> None:
        """
        OAuth Backend (client_credentials) authentication flow.
        """
        if type(self.requests_session) is not OAuth2Session:
            logger.info("OAuth2 (client_credentials) initialization authentication.")
            self.requests_session = OAuth2Session(
                client=BackendApplicationClient(
                    client_id=self.configuration["authentication.oauth.client_id"]
                )
            )
            self.requests_session.fetch_token(
                token_url=self.configuration["authentication.oauth.access_token_url"],
                auth=HTTPBasicAuth(
                    self.configuration["authentication.oauth.client_id"],
                    self.configuration["authentication.oauth.client_secret"],
                ),
            )

    def OAuth2TokenSaver(self, token: dict) -> None:
        logger.debug("OAuth2 saving token {0}".format(token))
        self.session["oauth_access_token"] = token["access_token"]
        self.session["oauth_token_type"] = token["token_type"]
        self.session["oauth_expires_at"] = datetime.datetime.now() + datetime.timedelta(
            seconds=token.get("expires_in", 3600)
        )
        if "refresh_token" in token:
            self.session["oauth_refresh_token"] = token["refresh_token"]

    def GetOAuthTokenData(self) -> dict:
        return {
            "access_token": self.session.get("oauth_access_token", None),
            "token_type": self.session.get("oauth_token_type", None),
            "expires_at": Serializer.deserialize(
                self.session.get("oauth_expires_at", None)
            ),
            "refresh_token": self.session.get("oauth_refresh_token", None),
        }

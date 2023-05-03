from __future__ import annotations

import datetime
import uuid
import hashlib

from typing import Optional, Union, List

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
from requests.auth import HTTPDigestAuth

from pibble.api.helpers.authentication import APIAuthenticationSource
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase
from pibble.api.middleware.webservice.authentication.header import AuthorizationHeader
from pibble.api.exceptions import AuthenticationError, ConfigurationError
from pibble.util.strings import encode, decode


class DigestAuthenticationMiddleware(WebServiceAPIMiddlewareBase):
    """
    Middleware for digest HTTP authentication.

    Digest authentication validates requests based on a number of variables in the request. A few important things to remember:
      1. Storing passwords MUST be either plaintext passwords (not recommended), OR an MD5-hashed version of the password that is "username:realm:password". Simply hashing the password is not possible due to the nature of digesting content.
      2. Python "requests" library does not currenty support "auth-int" quality-of-protection. For this reason, it's recommended to always use "auth".

    Digest authentication uses "nonces", which are randomly generated values that must be present during the challenge-response cycle. Some libraries refuse to reuse nonces, whereas we permit it here. See :class:`pibble.api.middleware.webservice.authentication.digest.NonceList` and :class:`pibble.api.middleware.webservice.authentication.digest.NonceList.Nonce` for how these are kept and checked.
    """

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        if isinstance(request, WebobRequest) or isinstance(request, RequestWrapper):
            """
            Server code.
            """
            if not hasattr(self, "authentication_source"):
                self.authentication_source = APIAuthenticationSource(self.configuration)
            if not hasattr(self, "nonces"):
                self.nonces = NonceList()
            if not hasattr(self, "opaque"):
                self.opaque = uuid.uuid4().hex
            try:
                # This checks the configuration values for valid configuration. No configuration is actually required,
                # as the defaults will work.

                qop = self.configuration.get("authentication.digest.qop", "auth")
                realm = self.configuration.get("authentication.digest.realm", "default")
                algorithm = self.configuration.get(
                    "authentication.digest.algorithm", "md5"
                ).lower()

                if qop not in ["auth", "auth-int"]:
                    raise ConfigurationError(
                        "Invalid qop - valid values are auth or auth-int."
                    )
                if algorithm not in ["md5", "md5-sess"]:
                    raise ConfigurationError(
                        "Invalid algorithm - valid values are md5 or md5-sess."
                    )
                if self.authentication_source.encryption not in ["md5", "plain"]:
                    raise ConfigurationError(
                        "Can only use digest authentication with an authentication source with encryption of md5 or plain."
                    )
                if (
                    algorithm == "md5-sess"
                    and self.authentication_source.encryption != "plain"
                ):
                    raise ConfigurationError(
                        "Cannot use session-based MD5 hashes without also storing plaintext passwords."
                    )

            except KeyError as ex:
                raise ConfigurationError(
                    "Required configuration values not present: {0}".format(ex)
                )
            nonce = None
            authorization = None
            try:
                try:
                    authorization = AuthorizationHeader(request)
                    if authorization.method != "Digest":
                        raise AuthenticationError(
                            "Incorrect authentication type - must be 'Digest', got '{0}'.".format(
                                authorization.method
                            )
                        )

                    nonce = self.nonces.get(authorization.variables["nonce"])

                    if not nonce:
                        # Client sent an authorization header, but no nonce.
                        raise AuthenticationError("No nonce provided.")
                    if authorization.variables["uri"] != request.path:
                        # Client sent an authorization header with the wrong URI.
                        raise AuthenticationError("Authorization URI is incorrect.")
                    if int(authorization.variables["nc"], 16) != nonce.uses:
                        # Client did not increment nonce count, could be a replay attack.
                        raise AuthenticationError(
                            "Replay attack detected, nc was not incremented."
                        )
                    if "cnonce" not in authorization.variables:
                        # Client did not generate their own nonce.
                        raise AuthenticationError(
                            "Client nonce not sent, possible plaintext attack detected."
                        )

                    # Stored password is either plaintext password, or md5 hash of "username:realm:password".
                    stored = self.authentication_source[
                        authorization.variables["username"]
                    ]

                    # The below code calculates "HA1", a portion of the overall response.
                    if algorithm.lower() == "md5-sess":
                        ha1 = decode(
                            hashlib.md5(
                                encode(
                                    "{0}:{1}:{2}".format(
                                        hashlib.md5(
                                            encode(
                                                "{0}:{1}:{2}".format(
                                                    authorization.variables["username"],
                                                    realm,
                                                    stored,
                                                )
                                            )
                                        ).hexdigest(),
                                        nonce.value,
                                        authorization.variables["cnonce"],
                                    )
                                )
                            ).hexdigest()
                        )
                    elif self.authentication_source.encryption == "plain":
                        ha1 = decode(
                            hashlib.md5(
                                encode(
                                    "{0}:{1}:{2}".format(
                                        authorization.variables["username"],
                                        realm,
                                        stored,
                                    )
                                )
                            ).hexdigest()
                        )
                    else:
                        ha1 = stored

                    # This code calculates HA2, another portion of the overall response.
                    if qop == "auth":
                        ha2 = decode(
                            hashlib.md5(
                                encode("{0}:{1}".format(request.method, request.path))
                            ).hexdigest()
                        )
                    elif qop == "auth-int":
                        body = "" if request.body is None else request.body
                        ha2 = decode(
                            hashlib.md5(
                                encode(
                                    "{0}:{1}:{2}".format(
                                        request.method,
                                        request.path,
                                        hashlib.md5(encode(body)).hexdigest(),
                                    )
                                )
                            ).hexdigest()
                        )

                    # Using HA1 and HA2, calculate the final response hash.
                    response_hash = decode(
                        hashlib.md5(
                            encode(
                                "{0}:{1}:{2}:{3}:{4}:{5}".format(
                                    ha1,
                                    nonce.value,
                                    authorization.variables["nc"],
                                    authorization.variables["cnonce"],
                                    qop,
                                    ha2,
                                )
                            )
                        ).hexdigest()
                    )

                    # Compare the response hash to what was sent.
                    if response_hash != authorization.variables["response"]:
                        raise AuthenticationError("Invalid response sent.")

                except KeyError as ex:
                    raise AuthenticationError(
                        "Authorization header missing required component '{0}'".format(
                            ex
                        )
                    )
            except AuthenticationError as ex:
                # In the event of an exception, generate a new challenge.
                response_variables = {
                    "realm": realm,
                    "qop": qop,
                    "algorithm": algorithm.upper(),
                    "nonce": self.nonces.generate(),
                    "opaque": self.opaque,
                    "stale": str(hasattr(authorization, "nonce") and not nonce).lower(),
                }
                if isinstance(response, WebobResponse):
                    response.headers["WWW-Authenticate"] = "Digest {0}".format(
                        ", ".join(
                            [
                                '{0}="{1}"'.format(key, response_variables[key])
                                for key in response_variables
                            ]
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
            Client code. Gather username and password from configuration, and passes it to the Requests library. Requests will properly handle the challenge/response cycle.
            """
            try:
                request.auth = HTTPDigestAuth(
                    self.configuration.get("authentication.digest.username"),
                    self.configuration.get("authentication.digest.password"),
                )
            except KeyError as ex:
                raise ConfigurationError(str(ex))


class NonceList:
    """
    A class to hold a list of nonces.

    :param ttl int: The time a nonce is valid, in seconds.
    :param max_uses int: The number of times a nonce can be used before a new one must be generated.
    """

    nonces: List[NonceList.Nonce]

    def __init__(self, ttl: int = 60 * 60 * 24, max_uses: int = 25):
        self.ttl = ttl
        self.max_uses = max_uses
        self.nonces = []

    def clear(self) -> None:
        now = datetime.datetime.now()
        self.nonces = [
            nonce
            for nonce in self.nonces
            if nonce.expiration >= now and nonce.uses < self.max_uses
        ]

    def generate(self) -> str:
        nonce = NonceList.Nonce(self.ttl)
        self.nonces.append(nonce)
        return nonce.value

    def get(self, value: str) -> Optional[NonceList.Nonce]:
        self.clear()
        nonce = [nonce for nonce in self.nonces if nonce.value == value]
        if nonce:
            return nonce[0]
        return None

    class Nonce:
        """
        The nonce itself.

        :param ttl int: The time this nonce is valid, in seconds.
        """

        def __init__(self, ttl: int):
            self.uses = 1

            self.expiration = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
            self.value = uuid.uuid4().hex

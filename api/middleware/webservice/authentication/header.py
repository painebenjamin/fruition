import re
import base64

from webob import Request

from pibble.util.strings import decode
from pibble.api.exceptions import AuthenticationError


class AuthorizationHeader:
    """
    Parses an authentication header into its component parts.

    :param header str: The "Authorization" header from a request.

    >>> from pibble.api.middleware.webservice.authentication.header import AuthorizationHeader
    >>> from pibble.util.helpers import AttributeDictionary
    >>> import base64
    >>> header1 = AuthorizationHeader(AttributeDictionary(HTTP_AUTHORIZATION = "Basic {0}".format(base64.b64encode(b"myusername:mypassword").decode("UTF-8"))))
    >>> header1.method
    'Basic'
    >>> header1.username
    'myusername'
    >>> header1.password
    'mypassword'
    >>> header2 = AuthorizationHeader(AttributeDictionary(HTTP_AUTHORIZATION = 'Digest username="myusername", nonce="mynonce"'))
    >>> header2.method
    'Digest'
    >>> header2.variables["username"]
    'myusername'
    >>> header2.variables["nonce"]
    'mynonce'
    """

    values_regex = re.compile('(\w+)[=] ?"?([^\s",]+)"?')

    def __init__(self, request: Request):
        if "Authorization" in getattr(request, "headers", {}):
            header = request.headers["Authorization"]
        elif hasattr(request, "HTTP_AUTHORIZATION"):
            header = request.HTTP_AUTHORIZATION
        else:
            raise AuthenticationError("No Authorization header present.")
        if header.startswith("Basic"):
            self.method = "Basic"
            decoded = decode(base64.b64decode(header.split()[1]))
            self.username, self.password = decoded.split(":")
        elif header.startswith("Digest"):
            self.method = "Digest"
            self.variables = dict(AuthorizationHeader.values_regex.findall(header))
        elif header.startswith("Bearer"):
            raise NotImplementedError("Bearer authentication is not yet supported.")
        else:
            raise ValueError(
                "Unsupported or unknown authentication method '{0}'.".format(
                    header.split()[0]
                )
            )

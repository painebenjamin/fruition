import ipaddress

from pibble.api.exceptions import AuthenticationError
from pibble.api.middleware.apachethrift.base import ApacheThriftAPIMiddlewareBase
from pibble.api.middleware.screening import ScreeningAPIMiddlewareBase
from pibble.api.helpers.apachethrift import ApacheThriftRequest
from pibble.api.server.apachethrift import ApacheThriftServer


class ScreeningApacheThriftAPIMiddleware(
    ApacheThriftAPIMiddlewareBase, ScreeningAPIMiddlewareBase
):
    """
    Extends the base ScreeningAPIMiddleware to get necessary details
    from a thrift request.
    """

    def prepare(self, request: ApacheThriftRequest) -> None:
        if isinstance(self, ApacheThriftServer):
            peer_address, peer_port = self.tfactory.client.handle.getpeername()
            peer = ipaddress.IPv4Address(peer_address)
            if any([peer in network for network in self.blocklist]):
                raise AuthenticationError(
                    "Your request was screened by network policy."
                )
            if any([peer in network for network in self.allowlist]):
                return
            if self.offlist == "reject":
                raise AuthenticationError(
                    "Your request was screened by network policy."
                )

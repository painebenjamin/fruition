import ipaddress

from fruition.api.exceptions import AuthenticationError
from fruition.api.middleware.apachethrift.base import ApacheThriftAPIMiddlewareBase
from fruition.api.middleware.screening import ScreeningAPIMiddlewareBase
from fruition.api.helpers.apachethrift import ApacheThriftRequest
from fruition.api.server.apachethrift import ApacheThriftServer


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

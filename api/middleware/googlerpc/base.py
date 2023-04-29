from pibble.api.middleware.base import APIMiddlewareBase
from pibble.api.helpers.googlerpc import GRPCRequest, GRPCResponse


class GRPCAPIMiddlewareBase(APIMiddlewareBase):
    """
    A base class for GRPC middleware.

    Classes that utilize middleware should be aware that method
    resolution order is ***not reliable*** unless strictly enforced
    during object creation - it's generally safer to assume there
    is no specific order in which these requests are performed, but
    ***all*** ``prepare()`` and ``parse()`` methods will be ran.
    """

    def prepare(self, request: GRPCRequest) -> None:
        """
        Servers: prepares a request for processing.
        Clients: prepares a request for sending. Context is unavailable.

        :param request pibble.api.helpers.grpc.GRPCRequest: The request method, message and args.
        """
        pass

    def parse(self, response: GRPCResponse) -> None:
        """
        Servers: prepares a response for sending.
        Clients: parses a response from the server. Context is unavailable.

        :param response pibble.api.helpers.grpc.GRPCResponse: The response object.
        """
        pass

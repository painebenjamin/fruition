from pibble.api.middleware.base import APIMiddlewareBase
from pibble.api.helpers.apachethrift import ApacheThriftRequest, ApacheThriftResponse


class ApacheThriftAPIMiddlewareBase(APIMiddlewareBase):
    """
    A base class for thrift service middleware.

    Implementing classes can pass on either or both of prepare() and parse() functions.

    Classes that utilize middleware should be aware that method
    resolution order is ***not reliable*** unless strictly enforced
    during object creation - it's generally safer to assume there
    is no specific order in which these requests are performed, but
    ***all*** ``prepare()`` and ``parse()`` methods will be ran.
    """

    def prepare(self, request: ApacheThriftRequest) -> None:
        """
        Prepares a request (before processor handling.)

        :param request pibble.api.helpers.apachethrift.ApacheThriftRequest: The request.
        """
        pass

    def parse(self, response: ApacheThriftResponse) -> None:
        """
        Parses a response (after processor handling.)

        :param request pibble.api.helpers.apachethrift.ApacheThriftResponse: The response.
        """
        pass

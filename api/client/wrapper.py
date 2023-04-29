from typing import Optional

from pibble.api.server.base import APIServerBase
from pibble.api.client.base import APIClientBase

__all__ = ["APIClientWrapperBase"]


class APIClientWrapperBase(APIClientBase):
    """
    A client wrapper that 'fakes' requests.

    This will directly call the relevant server methods, attempting
    to abstract the protocol on which the server received a request.
    """

    server: Optional[APIServerBase] = None

    def on_configure(self) -> None:
        server = self.configuration.get("server.instance", None)
        if isinstance(server, APIServerBase):
            self.server = server

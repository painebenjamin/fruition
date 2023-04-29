from typing import Any

from pibble.api.helpers.apachethrift import ApacheThriftRequest
from pibble.api.client.wrapper import APIClientWrapperBase
from pibble.api.client.apachethrift import ApacheThriftClientBase
from pibble.api.server.apachethrift import ApacheThriftServer

__all__ = ["ApacheThriftClientWrapper", "ApacheThriftHandlerWrapper"]


class ApacheThriftClientWrapper(ApacheThriftClientBase, APIClientWrapperBase):
    """
    A wrapper around the client class of a thrift service that doesn't instantiate any kind of protocol,
    instead directly calling the server instance.

    See `pibble.api.helpers.apachethrift.ApacheThriftService` for required service arguments.
    """

    def _execute(self, request: ApacheThriftRequest) -> Any:
        if not isinstance(self.server, ApacheThriftServer):
            raise TypeError(
                "ApacheThriftClientWrapper can only be used wrapping around an ApacheThriftServer."
            )
        return getattr(self.server.thrift.handler, request.method)(
            *request.args, **request.kwargs
        )


class ApacheThriftHandlerWrapper(ApacheThriftClientBase):
    """
    A wrapper around the client class of a thrift service that doesn't instantiate any kind of protocol,
    instead directly calling the server instance.

    See `pibble.api.helpers.apachethrift.ApacheThriftService` for required service arguments.
    """

    def _execute(self, request: ApacheThriftRequest) -> Any:
        if self.thrift.handler is None:
            raise ValueError(
                "Handler not defined; cannot use ApacheThriftHandlerWrapper."
            )
        if type(self.thrift.handler) is type:
            self.thrift.handler = self.thrift.handler(self.configuration)
        return getattr(self.thrift.handler, request.method)(
            *request.args, **request.kwargs
        )

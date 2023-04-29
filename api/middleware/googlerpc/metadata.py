from pibble.util.log import logger
from pibble.api.middleware.googlerpc.base import GRPCAPIMiddlewareBase
from pibble.api.helpers.googlerpc import GRPCRequest


class GRPCMetadataMiddleware(GRPCAPIMiddlewareBase):
    """
    This class allows for pushing static or callable metadata into a
    GRPC request.

    All configuration values are in `grpc.metadata`.
    """

    def prepare(self, request: GRPCRequest) -> None:
        """
        Either add to or create the metadata argument for function calls.

        :param request pibble.api.helpers.grpc.GRPCRequest: The request object.
        """

        if "metadata" not in request.kwargs:
            request.kwargs["metadata"] = tuple()
        metadata = self.configuration.get("grpc.metadata", {})
        for key in metadata:
            value = metadata[key]
            if callable(value):
                value = value(request)
            logger.debug("Adding metadata '{0}' to request.".format(key))
            request.kwargs["metadata"] += ((key, value),)

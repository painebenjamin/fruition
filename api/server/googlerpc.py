import grpc

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Optional, Any

from pibble.api.server.base import APIServerBase
from pibble.api.helpers.googlerpc import (
    GRPCConfiguration,
    GRPCRequest,
    GRPCResponse,
)
from pibble.util.log import logger
from pibble.util.helpers import resolve, Pause


class GRPCAPIServer(APIServerBase):
    """
    An object that wraps around TServer, to abstract the protocol and transport.

    Required configuration:
      1. ``server.host`` The host to listen on.
      2. ``server.port`` The port to listen on.
      3. ``grpc.handler`` The handler class, which is a simple object for handling requests.

    Optional configuration:
      1. ``server.threads`` The number of threads to run the server on. Defaults to 10.

    See :class:`pibble.api.helpers.GRPC.GRPCService` for required arguments for the GRPC service.
    """

    def __init__(self) -> None:
        super(GRPCAPIServer, self).__init__()

    def on_configure(self) -> None:
        """
        Builds the server.
        """

        self.host = self.configuration["server.host"]
        self.port = int(self.configuration["server.port"])
        self.address = "{0}:{1}".format(self.host, self.port)
        self.grpc = GRPCConfiguration(self.configuration)

        self.service = self.grpc.service
        self.messages = self.service.messages

        self.handler = self.configuration["grpc.handler"]
        if isinstance(self.handler, str):
            self.handler = resolve(self.handler)
        if isinstance(self.handler, type):
            self.handler = self.handler()

        self.servicer = self.service.servicer()
        for method in self.service.descriptor.methods:
            setattr(
                self.servicer,
                method.name,
                partial(self._handle_method, method.name),
            )

        self.server = grpc.server(
            ThreadPoolExecutor(max_workers=self.configuration.get("server.threads", 10))
        )
        self.service.assigner(self.servicer, self.server)

        if self.configuration.get("server.secure", False):
            raise NotImplementedError("Server security not yet implemented.")

        self.server.add_insecure_port(self.address)

    def _prepare(self, request: GRPCRequest) -> None:
        """
        Executes all `prepare()` methods.
        """
        for cls in type(self).mro():
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                cls.prepare(self, request)  # type: ignore

    def _parse(self, response: GRPCResponse) -> None:
        """
        Executes all `parse()` methods.
        """
        for cls in type(self).mro():
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                cls.parse(self, response)  # type: ignore

    def _handle_method(self, method: str, message: Any, context: Any = None) -> Any:
        """
        Handles the underlying method by calling the handler and then casting the response.

        :param method str: The method name.
        :param message obj: The compiled message object.
        :param context grpc._server._Context: The context object from GRPC.
        """

        request = GRPCRequest(self.service, method, context=context)
        request.fields.update(
            dict(
                [
                    (field.name, getattr(message, field.name, None))
                    for field in request.input.fields
                ]
            )
        )
        response = GRPCResponse(request)

        self._prepare(request)
        response_message = getattr(self.handler, request.method)(
            *[getattr(message, field.name) for field in request.input.fields]
        )

        if isinstance(response_message, dict):
            response.fields.update(response_message)
        else:
            if not isinstance(response_message, list) and not isinstance(
                response_message, tuple
            ):
                response_message = [response_message]
            response.fields.update(
                dict(
                    [
                        (field.name, response_message[i])
                        for i, field in enumerate(request.output.fields)
                    ]
                )
            )

        self._parse(response)
        return response()

    def serve(self) -> None:
        """
        Serves the GRPC service synchronosly.
        """
        logger.info(
            "Starting GRPC server for service '{0}' synchronously on {1}:{2}.".format(
                self.grpc.service.name, self.host, self.port
            )
        )
        self.start()
        while True:
            Pause.milliseconds(250)

    def start(self) -> None:
        """
        Serves the GRPC service asynchonously.
        """
        logger.info(
            "Starting GRPC server for service '{0}' asynchronously on {1}:{2}.".format(
                self.grpc.service.name, self.host, self.port
            )
        )
        self.server.start()

    def stop(self, graceful: Optional[bool] = True) -> None:
        """
        Stops serving the asynchronous GRPC service.
        """
        logger.info(
            "Stopping GRPC server for service '{0}' asynchronously on {1}:{2}.".format(
                self.grpc.service.name, self.host, self.port
            )
        )
        self.server.stop(graceful)

import grpc

from typing import Callable, Any, List
from functools import partial

from pibble.api.client.base import APIClientBase
from pibble.api.helpers.googlerpc import (
    GRPCConfiguration,
    GRPCRequest,
    GRPCResponse,
)


class GRPCAPIClient(APIClientBase):
    """
    An API client for GRPC services.

    Required configuration is `client.host` at a minimum. `client.port` can be configured, or defaults to 80/443. `client.secure` is a boolean which tells whether to use an SSL channel or not.

    The rest of the required configuration can be seen in the details for `pibble.api.helpers.grpc.GRPCConfiguration`.
    """

    def on_configure(self) -> None:
        self.grpc = GRPCConfiguration(self.configuration)
        self.service = self.grpc.service
        self.messages = self.service.messages

        self.address = "{0}:{1}".format(
            self.configuration["client.host"],
            self.configuration.get(
                "client.port",
                443 if self.configuration.get("client.secure", False) else 80,
            ),
        )
        if self.configuration.get("client.secure", False):
            self.channel = grpc.secure_channel(
                self.address, grpc.ssl_channel_credentials()
            )
        else:
            self.channel = grpc.insecure_channel(self.address)
        self.client = self.service.stub(self.channel)

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

    def _call_method(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """
        Calls the underlying method.

        We cast the arguments into a `pibble.api.helpers.grpc.GRPCRequest` so that we can run it
        through middleware processors.

        :param method str: The method name.
        :param message object: The compiled message. You should use `client.messages` to instantiate.
        :param kwargs dict: Any keyword arguments to pass into the client call.
        """

        if "fields" in kwargs:
            fields = kwargs.pop("fields")
        else:
            fields = None

        request = GRPCRequest(self.service, method, **kwargs)
        if fields is not None:
            request.fields.update(fields)
        else:
            request.fields.update(
                dict(
                    [
                        (field.name, None if len(args) < i else args[i])
                        for i, field in enumerate(request.input.fields)
                    ]
                )
            )

        response = GRPCResponse(request)
        self._prepare(request)

        response_message = getattr(self.client, request.method)(
            request(), **request.kwargs
        )
        response.load(response_message)

        self._parse(response)

        if len(response.fields.keys()) == 1:
            return list(response.fields.values())[0]
        return response.fields

    def __getitem__(self, key: str) -> Callable:
        """
        Allows for client[method] calls.
        """
        if key in self.listMethods():
            return partial(self._call_method, key)
        raise KeyError(key)

    def __getattr__(self, key: str) -> Callable:
        """
        Allows for client.method calls.
        """
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def listMethods(self) -> List[str]:
        """
        Lists all methods present in the stub.
        """
        return [
            method
            for method in dir(self.client)
            if not method.startswith("_") and callable(getattr(self.client, method))
        ]

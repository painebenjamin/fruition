import functools

from typing import Callable, Any, List

from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol

from pibble.api.client.base import APIClientBase

from pibble.api.helpers.apachethrift import (
    ApacheThriftService,
    ApacheThriftRequest,
    ApacheThriftResponse,
)

from pibble.util.helpers import resolve

__all__ = ["ApacheThriftClientBase", "ApacheThriftClient"]


class ApacheThriftClientBase(APIClientBase):
    """
    A small wrapper around the client class of a thrift service, to abstract the instantiation
    of the service.
    """

    def on_configure(self) -> None:
        """
        Instantiate the service.
        """
        self.thrift = ApacheThriftService(self.configuration)

    def listMethods(self) -> List[str]:
        """
        List methods in the interface.
        """
        return [
            func
            for func in dir(self.thrift.interface)
            if callable(getattr(self.thrift.interface, func))
            and not func.startswith("_")
        ]

    def _prepare(self, request: ApacheThriftRequest) -> None:
        """
        Iterate through method resolution order and prepare a request.
        """
        for cls in type(self).mro():
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                cls.prepare(self, request)

    def _parse(self, response: ApacheThriftResponse) -> None:
        """
        Iterate through method resolution order and parse a response.
        """
        for cls in type(self).mro():
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                cls.parse(self, response)

    def _execute(self, request: ApacheThriftRequest) -> Any:
        """
        Call the underlying transport method.
        """
        raise NotImplementedError(
            "The base class does not provide the means to execute."
        )

    def _call_method(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Handles taking the method, args and kwargs and instantiating them into
        request/response objects, then calls self._execute.

        :param method str: The method to call.
        :param args tuple: Arguments to pass into the function.
        :param kwargs dict: Keyword arguments to pass into the function.
        :returns object: The response from the thrift service.
        """
        request = ApacheThriftRequest(self, method_name, *args, **kwargs)
        try:
            self._prepare(request)
            response_body = self._execute(request)
            response_type = ApacheThriftResponse.OK
        except Exception as ex:
            response_body = ex
            response_type = ApacheThriftResponse.ERROR

        response = ApacheThriftResponse(self, request, response_type, response_body)
        self._parse(response)

        if response.response_type == ApacheThriftResponse.ERROR:
            err = response.response
            if str(response.response).startswith("pibble.api.exceptions"):
                error_parts = str(response.response).split(":")
                try:
                    err = resolve(error_parts[0])(":".join(error_parts[1:]))
                except:
                    pass
            raise err
        return response.response

    def __getattr__(self, key: str) -> Callable:
        """
        A simple wrapper around self[key].
        """
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __getitem__(self, key: str) -> Callable:
        """
        Returns partial functions on the client.

        :returns functools.partial: The partial function to call self._call_method.
        """
        if key in self.listMethods():
            return functools.partial(self._call_method, key)
        raise KeyError(key)


class ApacheThriftClient(ApacheThriftClientBase):
    """
    A small wrapper around the client class of a thrift service, to abstract the transport and protocol.

    This is a context manager, so use thusly::
      client = ApacheThriftClient()
      client.configure(client = {"host": "127.0.0.1". "port": 9090, "thrift": {"service": MyService}})
      with client as service:
        response = service.function(*args)

    Required configuration:
      1. ``client.host`` the host the connect to.
      2. ``client.port`` the port to connect to.

    See `pibble.api.helpers.apachethrift.ApacheThriftService` for required service arguments.
    """

    def on_configure(self) -> None:
        self.host = self.configuration["client.host"]
        self.port = self.configuration["client.port"]
        self.transport = TSocket.TSocket(self.host, self.port)
        self.buffered_transport = TTransport.TBufferedTransport(self.transport)
        self.protocol = TBinaryProtocol.TBinaryProtocol(self.buffered_transport)
        self.client = self.thrift.service.Client(self.protocol)

    def _execute(self, request: ApacheThriftRequest) -> Any:
        """
        The client is configured to serialize and deserialize.
        """
        try:
            return getattr(self.client, request.method)(*request.args, **request.kwargs)
        except:
            self.buffered_transport.close()
            raise

    def _call_method(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Makes sure the transport is open before trying to call the _execute method.
        """
        if not self.buffered_transport.isOpen():
            self.buffered_transport.open()
        return super(ApacheThriftClient, self)._call_method(
            method_name, *args, **kwargs
        )

    def __enter__(self) -> Any:
        """
        When used as a context manager, opens the buffered transport.
        """
        self.buffered_transport.open()
        return self.client

    def __exit__(self, *args: Any) -> None:
        """
        When used as a context manager, closes the buffered transport.
        """
        if hasattr(self, "buffered_transport"):
            try:
                self.buffered_transport.close()
            except:
                pass

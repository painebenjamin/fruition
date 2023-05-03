from functools import partial
from typing import Callable, Any, List

from pibble.util.log import logger
from pibble.util.helpers import resolve
from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.helpers.apachethrift import (
    TTransitiveMemoryBuffer,
    ApacheThriftService,
)
from pibble.api.protocol.apachethrift import TJSONProtocol  # type: ignore


class ApacheThriftWebClient(WebServiceAPIClientBase):
    """
    A client for thrift web services.

    Whenever possible, you should use the regular client and server, as there is significant overhead
    in running the web client and server. However, for access from a browser, a web client and
    server is necessary.

    Required configuration:
      1. ``client.host`` the host the connect to.
      2. ``client.port`` the port to connect to.

    Optional configuration:
      1. ``client.introspect`` If true, will assign partial functions to client object. Default true.

    See :class:`pibble.api.helpers.thrift.ThriftService` for required service arguments.
    See superclass :class:`pibble.api.client.webservice.base.WebServiceAPIClientBase` for additional required arguments.
    """

    BUFFER_SIZE = 2**15

    def __init__(self) -> None:
        super(ApacheThriftWebClient, self).__init__()

        # Generate input and output protocols.
        # These protocols essentially just write binary data to a bytearray.
        self.input_transport = TTransitiveMemoryBuffer()
        self.input_protocol = TJSONProtocol(self.input_transport)

        self.output_transport = TTransitiveMemoryBuffer()
        self.output_protocol = TJSONProtocol(self.output_transport)

    def on_configure(self) -> None:
        self.thrift = ApacheThriftService(self.configuration)

        # Instantiate the client with the transports we made.
        self.client = self.thrift.service.Client(
            self.input_protocol, self.output_protocol
        )
        self.interface = self.thrift.service.Iface()

    def listMethods(self) -> List[str]:
        """
        Lists methods in the interface.
        """
        return [
            method
            for method in dir(self.interface)
            if callable(getattr(self.interface, method)) and not method.startswith("_")
        ]

    def __getattr__(self, method_name: str) -> Callable:
        """
        Overrides client.methodName calls.

        :returns partial: The function to call the underlying method.
        :raises AttributeError:
        """
        try:
            return self[method_name]
        except KeyError:
            raise AttributeError(method_name)

    def __getitem__(self, method_name: str) -> Callable:
        """
        Overrides client[methodName] calls. Effectively exposes methods to external services.

        :returns partial: The function to call the underlying method.
        """
        if method_name in self.listMethods():
            return partial(self._call_method, method_name)
        raise KeyError("Unknown or disallowed method '{0}'.".format(method_name))

    def _call_method(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        This class will call methods against the client.

        First calls "send_<method_name>", which writes binary data to the output transport.
        Will then post the binary data from the output transport to the designated endpoint.
        Upon receiving data, the raw binary is written into the input transport, and then
        calls "recv_<method_name>", which will parse the data and return the final result.

        :param method_name str: The method name.
        :param args tuple: The arguments to pass into the function. An ArgumentError will arise
                           if they are incorrect.
        """
        _send_method = "send_{0}".format(method_name)
        _recv_method = "recv_{0}".format(method_name)

        logger.debug(
            "Thrift web client sending request for method {0}, args {1}".format(
                method_name, args
            )
        )

        getattr(self.client, _send_method)(*args)

        data = self.output_transport.read(ApacheThriftWebClient.BUFFER_SIZE)
        response = self.post(
            data=data,
            headers={
                "Content-Type": "application/x-thrift",
                "Content-Length": str(len(data)),
            },
        )
        self.input_transport.write(response.content)
        try:
            return getattr(self.client, _recv_method)()
        except Exception as ex:
            try:
                ex = resolve(str(ex).split(":")[0])(":".join(str(ex).split(":")[1:]))
            except:
                pass
            raise ex

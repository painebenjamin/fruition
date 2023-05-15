from webob import Request, Response

from thrift.transport import TTransport

from typing import Any

from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.api.protocol.apachethrift import TJSONProtocol  # type: ignore
from pibble.api.exceptions import ApacheThriftError
from pibble.api.helpers.apachethrift import (
    ApacheThriftService,
    ApacheThriftServerHandler,
)


class ApacheThriftWebServer(WebServiceAPIServerBase):
    """
    A webservice for handling thrift services.

    What this achieves is simple; there is an underlying layer of a thrift processor, which is called when
    receiving a POST request. This is less performant than a raw thrift server (due to HTTP overhead), but
    still more performant than other web services due to binary encoding.

    Required configuration:
      1. `thrift.handler` The handler for the thrift service. Can be a string, in which case a resolution will be attempted.

    One of the following:
      A.
        1. `thrift.service` The compiled thrift module, or a string to resolve.
      B.
        1. `thrift.compile` The thrift IDL.
        2. `thrift.service` The service name.
    """

    handlers = WebServiceAPIHandlerRegistry()

    def on_configure(self) -> None:
        self.thrift = ApacheThriftService(self.configuration, True)
        self.processor = self.thrift.service.Processor(
            ApacheThriftServerHandler(self, self.thrift.interface, self.thrift.handler)
        )

    @handlers.path("^.*$")
    @handlers.methods("POST")
    @handlers.compress()
    def process(self, request: Request, response: Response) -> Any:
        input_transport = TTransport.TBufferedTransport(
            TTransport.TFileObjectTransport(request.body_file),
            request.content_length,
        )
        output_transport = TTransport.TMemoryBuffer()
        input_protocol = TJSONProtocol(input_transport)
        output_protocol = TJSONProtocol(output_transport)
        try:
            self.processor.process(input_protocol, output_protocol)
        except ApacheThriftError as ex:
            raise ex.cause
        response.content_type = "application/x-thrift"
        return output_transport.getvalue()

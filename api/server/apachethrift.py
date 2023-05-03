from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer
from pibble.api.server.base import APIServerBase
from pibble.api.helpers.apachethrift import (
    ApacheThriftService,
    ApacheThriftServerHandler,
    ApacheThriftBufferedTransportFactory,
)
from pibble.util.log import logger


class ApacheThriftServer(APIServerBase):
    """
    An object that wraps around TServer, to abstract the protocol and transport.

    Required configuration:
      1. ``server.host`` The host to listen on.
      2. ``server.port`` The port to listen on.
      3. ``thrift.handler`` The handler class, which is a simple object for handling requests.

    Optional configuration:
      1. ``server.type`` The type of server. One of "simple", "threaded", or "forking."

    See :class:`pibble.api.helpers.thrift.ApacheThriftService` for required arguments for the thrift service.
    """

    SIMPLE = 0
    THREADED = 1
    FORKING = 2

    def __init__(self) -> None:
        super(ApacheThriftServer, self).__init__()

    def on_configure(self) -> None:
        """
        Builds the server.
        """

        self.host = self.configuration["server.host"]
        self.port = int(self.configuration["server.port"])

        self.thrift = ApacheThriftService(self.configuration, True)

        self.processor = self.thrift.service.Processor(
            ApacheThriftServerHandler(self, self.thrift.interface, self.thrift.handler)
        )
        self.transport = TSocket.TServerSocket(host=self.host, port=self.port)
        self.tfactory = ApacheThriftBufferedTransportFactory()
        self.pfactory = TBinaryProtocol.TBinaryProtocolFactory()

        self.server = {
            "simple": TServer.TSimpleServer,
            "threaded": TServer.TThreadPoolServer,
            "forking": TServer.TForkingServer,
        }.get(
            self.configuration.get("server.type", "simple").lower(),
            TServer.TSimpleServer,
        )(
            self.processor, self.transport, self.tfactory, self.pfactory
        )

    def serve(self) -> None:
        """
        Serves the thrift service synchronosly.
        """
        logger.info(
            "Starting thrift server for service '{0}' synchronously on {1}:{2}.".format(
                self.thrift.service.__name__, self.host, self.port
            )
        )
        self.server.serve()

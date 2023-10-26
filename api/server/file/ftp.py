import os

try:
    from pyftpdlib.authorizers import UnixAuthorizer
except ImportError:
    UnixAuthorizer = object

try:
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.handlers import TLS_FTPHandler
    from pyftpdlib.servers import FTPServer as PYFTPServer
except ImportError:
    raise ImportError("Couldn't find pyftpdlib. Run `pip install pibble[ftp]` to get it.")

from pibble.api.server.base import APIServerBase
from pibble.api.exceptions import ConfigurationError


class FTPServer(APIServerBase):
    """
    A small wrapper pyftpdlib server.

    Does not provide any additional functionality beyond the normal capabilities.

    Required configuration:
      - ``server.host``

    Optional configuiration:
      - ``server.port`` - default 20
      - ``server.secure`` - default False
    """

    def on_configure(self) -> None:
        if os.name == "nt":
            raise ConfigurationError("Cannot use FTP server on Windows.")
        self.authorizer = UnixAuthorizer()
        if self.configuration.get("server.secure", False):
            self.handler = TLS_FTPHandler
        else:
            self.handler = FTPHandler
        self.handler.authorizer = self.authorizer
        self.server = PYFTPServer(
            (
                self.configuration["server.host"],
                self.configuration.get("server.port", 20),
            ),
            self.handler,
        )

    def serve(self) -> None:
        """
        Runs the server synchronously.
        """
        self.server.serve_forever()

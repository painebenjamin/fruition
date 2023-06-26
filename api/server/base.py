from __future__ import annotations

from typing import Optional, Dict, Any

from multiprocessing import Process
from pibble.api.base import APIBase
from pibble.util.helpers import Pause
from pibble.util.log import logger


class APIServerProcess(Process):
    """
    A small class that will run the server process in the background.
    """

    def __init__(
        self, server: APIServerBase, configuration: Optional[Dict[str, Any]] = None
    ) -> None:
        super(APIServerProcess, self).__init__()
        self.server = server
        self.configuration = configuration

    def run(self) -> None:
        if self.configuration is not None:
            self.server.configure(**self.configuration)
        try:
            self.server.serve()
        except Exception as ex:
            logger.critical("{0}(): {1}".format(type(ex).__name__, str(ex)))
            raise


class APIServerBase(APIBase):
    """
    A base server class, from which all server implementations will inherit.
    """

    _process: APIServerProcess

    def __init__(self) -> None:
        super(APIServerBase, self).__init__()

    def serve(self) -> None:
        """
        The main serve() method will _synchronously_ perform the server functions.

        There is no base serving ability, so implementing classes _must_ override this.
        """
        raise NotImplementedError()

    def running(self) -> bool:
        """
        Determines if the server is currently running (when used asynchronously.)
        """
        return hasattr(self, "_process") and self._process.is_alive()

    def configure_start(self, **configuration: Any) -> None:
        """
        Starts the server, configuring itself after.
        """
        if hasattr(self, "_process"):
            if self._process.is_alive():
                logger.warning(
                    "start() was called while process is still alive. Ignoring."
                )
                return
            del self._process
        self._process = APIServerProcess(self, configuration)
        self._process.start()
        Pause.milliseconds(250)

    def start(self) -> None:
        """
        Starts the server, which will serve asynchronously.
        """
        if hasattr(self, "_process"):
            if self._process.is_alive():
                logger.warning(
                    "start() was called while process is still alive. Ignoring."
                )
                return
            del self._process
        self._process = APIServerProcess(self)
        self._process.start()
        Pause.milliseconds(250)

    def stop(self) -> None:
        """
        Stops the server.
        """
        if hasattr(self, "_process"):
            self._process.terminate()
            self._process.join()
            self._process.close()
            del self._process

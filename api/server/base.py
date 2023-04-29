from multiprocessing import Process
from pibble.api.base import APIBase
from pibble.util.helpers import Pause
from pibble.util.log import logger


class APIServerProcess(Process):
    """
    A small class that will run the server process in the background.
    """

    def __init__(self, server):
        super(APIServerProcess, self).__init__()
        self.server = server

    def run(self):
        try:
            self.server.serve()
        except Exception as ex:
            logger.critical("{0}(): {1}".format(type(ex).__name__, str(ex)))
            raise


class APIServerBase(APIBase):
    """
    A base server class, from which all server implementations will inherit.
    """

    def __init__(self):
        super(APIServerBase, self).__init__()

    def serve(self):
        """
        The main serve() method will _synchronously_ perform the server functions.

        There is no base serving ability, so implementing classes _must_ override this.
        """
        raise NotImplementedError()

    def running(self):
        """
        Determines if the server is currently running (when used asynchronously.)
        """
        return hasattr(self, "_process") and self._process.is_alive()

    def start(self):
        """
        Starts the server, which will serve asynchronously.
        """
        if getattr(self, "_process", None) is not None:
            if self._process.is_alive():
                logger.warning(
                    "start() was called while process is still alive. Ignoring."
                )
                return
            self._process = None
        self._process = APIServerProcess(self)
        self._process.start()
        Pause.milliseconds(250)

    def stop(self):
        """
        Stops the server.
        """
        if getattr(self, "_process", None) is not None:
            self._process.terminate()
            self._process.join()
            self._process.close()
            self._process = None

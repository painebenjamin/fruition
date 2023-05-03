from pibble.api.middleware.base import APIMiddlewareBase
from pibble.util.files import TempfileContext


class APITempfileMiddleware(APIMiddlewareBase):
    """
    A simple middleware that generates tempfile context on configuration,
    and deletes it on destruction.
    """

    def on_configure(self) -> None:
        self.tempfiles = TempfileContext()
        self.tempfiles.start()

    def on_destroy(self) -> None:
        self.tempfiles.stop()

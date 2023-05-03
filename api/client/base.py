from __future__ import annotations

from typing import Any, List

from pibble.util.log import logger
from pibble.api.base import APIBase


class APIClientBase(APIBase):
    """
    A base client class, from which all implementing clients will inherit.
    """

    def __init__(self) -> None:
        logger.debug("Initializing API Client Base.")
        super(APIClientBase, self).__init__()

    def __enter__(self) -> APIClientBase:
        """
        A small context manager to use the close() function.
        """
        return self

    def __exit__(self, *args: Any) -> None:
        try:
            self.close()
        except Exception as ex:
            logger.error(
                "Could not close API Client, ignoring. {0}() {1}".format(
                    type(ex).__name__, str(ex)
                )
            )
            pass

    def close(self) -> None:
        """
        Closes a client. This may or may not be meaningful, depending on the
        client type (namely, whether or not a persistent client is created).
        """
        pass

    def listMethods(self) -> List[str]:
        """
        Lists methods, if available. Implementing clients should override these.

        :raises NotImplementedError: When the implementing class does not override.
        """
        raise NotImplementedError()

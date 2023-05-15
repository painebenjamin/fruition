from typing import Optional, Union

from webob import Request as WebobRequest, Response as WebobResponse
from requests import Request as RequestsRequest, Response as RequestsResponse
from pibble.api.helpers.wrappers import RequestWrapper, ResponseWrapper
from pibble.api.middleware.base import APIMiddlewareBase
from pibble.database.orm import ORM, ORMBuilder, ORMSession
from pibble.util.log import logger


class ORMMiddlewareBase(APIMiddlewareBase):
    """
    A client/server with an ORM attached to it.
    """

    orm: ORM

    def on_configure(self) -> None:
        """
        On configuration, establish ORM.
        """
        if "orm" in self.configuration:
            logger.debug("Establishing configured ORM.")
            self.orm = ORMBuilder.from_configuration(self.configuration)
        else:
            logger.warning(
                "No ORM configuration present, cannot create client/server ORM."
            )

    @property
    def database(self) -> ORMSession:
        """
        Getter for the database ensures we only instantiate when we need it.
        """
        if not hasattr(self, "_database"):
            logger.debug("Database requested, connecting to ORM")
            self._database = self.orm.session()
        return self._database

    @database.deleter
    def database(self) -> None:
        """
        Only remove the database if necessary.
        """
        if hasattr(self, "_database"):
            try:
                logger.debug("Closing ORM session")
                self._database.close()
                del self._database
            except Exception as ex:
                logger.warning(f"Ignoring exception during database close: {ex}")

    def on_destroy(self) -> None:
        """
        On destruction, close ORM.
        """
        if hasattr(self, "orm"):
            logger.debug("Disposing of configured ORM.")
            self.orm.dispose()

    def parse(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        Either open or a close a database session, depending on client or server.
        """
        if isinstance(request, RequestsRequest) or isinstance(request, RequestWrapper):
            del self.database

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        If server, close database session after responding.
        """
        if isinstance(request, WebobRequest) or isinstance(request, RequestWrapper):
            del self.database

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
    database: ORMSession

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
        if hasattr(self, "orm"):
            if isinstance(request, RequestsRequest):
                # Client parsing a response, close database
                if hasattr(self, "database"):
                    logger.debug("Closing client ORM session.")
                    try:
                        self.database.close()
                    except Exception as ex:
                        logger.debug(
                            "Ignoring exception during database close {0}: {1}".format(
                                type(ex).__name__, ex
                            )
                        )
            elif isinstance(request, WebobRequest) or isinstance(
                request, RequestWrapper
            ):
                # Server parsing a request, open database
                logger.debug("Opening server ORM session.")
                self.database = self.orm.session(expire_on_commit=False)

    def prepare(
        self,
        request: Optional[Union[WebobRequest, RequestsRequest, RequestWrapper]] = None,
        response: Optional[
            Union[WebobResponse, RequestsResponse, ResponseWrapper]
        ] = None,
    ) -> None:
        """
        Either open or a close a database session, depending on client or server.
        """
        if hasattr(self, "orm"):
            if isinstance(request, RequestsRequest):
                # Client preparing a request, open database
                logger.debug("Opening client ORM session.")
                self.database = self.orm.session(expire_on_commit=False)
            elif isinstance(request, WebobRequest) or isinstance(
                request, RequestWrapper
            ):
                # Server preparing a response, close database
                if hasattr(self, "database"):
                    logger.debug("Closing server ORM session.")
                    try:
                        self.database.close()
                    except Exception as ex:
                        logger.debug(
                            "Ignoring exception during database close {0}: {1}".format(
                                type(ex).__name__, ex
                            )
                        )

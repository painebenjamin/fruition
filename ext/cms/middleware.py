from typing import Dict
from webob import Request, Response

from pibble.util.log import logger
from pibble.api.exceptions import ConfigurationError
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase


class CMSExtensionContextMiddleware(WebServiceAPIMiddlewareBase):
    """
    This mixin passes through any base context configured
    on the server.
    """

    BASE_CONTEXT_KEY = "server.cms.context.base"

    def prepare_context(self, request: Request, response: Response) -> Dict:
        """
        On context preparation, read the configuration for base (static) context
        """
        try:
            context_base = self.configuration[
                CMSExtensionContextMiddleware.BASE_CONTEXT_KEY
            ]
            if not isinstance(context_base, dict):
                raise ConfigurationError(
                    "Configuration key '{0}' expected to be dictionary, but found {1} instead.".format(
                        CMSExtensionContextMiddleware.BASE_CONTEXT_KEY,
                        type(context_base),
                    )
                )
            return context_base
        except KeyError:
            logger.debug(
                "No base context at '{0}'".format(
                    CMSExtensionContextMiddleware.BASE_CONTEXT_KEY
                )
            )
            return {}

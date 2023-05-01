from webob import Request, Response
from typing import Any

from pibble.util.strings import Serializer
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.middleware.database.orm import ORMMiddlewareBase


class ORMWebServiceAPIServer(WebServiceAPIServerBase, ORMMiddlewareBase):
    """
    Overrides format_response to perform a format() on the results.
    """

    def format_response(
        self,
        result: Any,
        request: Request,
        response: Response,
    ) -> str:
        if isinstance(result, list):
            return Serializer.serialize(
                [
                    r.format(include=request.GET.getall("include"))
                    for r in result
                    if r is not None
                ]
            )
        if result is not None:
            return Serializer.serialize(
                result.format(include=request.GET.getall("include"))
            )
        return ""

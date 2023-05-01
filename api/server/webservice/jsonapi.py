import json

from webob import Request, Response

from typing import Any, Optional

from pibble.database.orm import ORMObject
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.util.strings import Serializer


class JSONWebServiceAPIServer(WebServiceAPIServerBase):
    """
    A small extension of the API Server base for JSONAPI's.

    Parses JSON requests, and formats per JSONAPI spec.
    """

    def format_response(
        self,
        result: Any,
        request: Request,
        response: Response,
    ) -> str:
        """
        Override format_response to respond per JSONAPI spec.
        """

        if result is not None:
            if type(result) is list:
                for i in range(len(result)):
                    if isinstance(result[i], ORMObject):
                        result[i] = result[i].format(
                            include=request.GET.getall("include"),
                            show=request.GET.getall("show"),
                        )
            elif isinstance(result, ORMObject):
                result = result.format(  # type: ignore
                    include=request.GET.getall("include"),
                    show=request.GET.getall("show"),
                )

        response_meta = {
            "params": dict(
                [(param, request.GET.getall(param)) for param in request.GET]
            )
        }

        if hasattr(response, "meta"):
            response_meta.update(response.meta)

        return json.dumps(
            {"meta": response_meta, "data": result}, default=Serializer.serialize
        )

    def format_exception(
        self,
        exception: Exception,
        request: Request,
        response: Response,
    ) -> str:
        """
        Formats exception per jsonapi spec.
        """
        if hasattr(exception, "cause"):
            exception = exception.cause

        error_code = 500
        for error_class in WebServiceAPIServerBase.EXCEPTION_CODES:
            if isinstance(exception, error_class):
                error_code = WebServiceAPIServerBase.EXCEPTION_CODES[error_class]
                break

        return json.dumps(
            {
                "errors": [
                    {
                        "status": str(error_code),
                        "title": type(exception).__name__,
                        "detail": str(exception),
                    }
                ]
            },
            default=Serializer.serialize,
        )

    def parse(
        self,
        request: Optional[Request] = None,
        response: Optional[Response] = None,
    ) -> None:
        """
        Parses the request and sets content type on the response.
        """
        if request is not None:
            if request.body:
                try:
                    setattr(request, "parsed", Serializer.deserialize(request.json))
                except json.JSONDecodeError:
                    setattr(request, "parsed", {})
            else:
                setattr(request, "parsed", {})
        if response is not None:
            response.content_type = "application/vnd.api+json"

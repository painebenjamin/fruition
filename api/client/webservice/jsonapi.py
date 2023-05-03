import json

from io import IOBase
from requests import Response
from typing import Any, Union, Dict

from pibble.util.strings import Serializer
from pibble.api.helpers.wrappers import ResponseWrapper
from pibble.api.client.webservice.base import WebServiceAPIClientBase

__all__ = ["JSONWebServiceAPIClient"]


class JSONWebServiceAPIClient(WebServiceAPIClientBase):
    def post(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        files: Dict[str, IOBase] = {},
        data: Any = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends a POST request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        if data:
            formatted_data = json.dumps(data, default=Serializer.serialize)
            headers["Content-Type"] = "application/vnd.api+json"
        else:
            formatted_data = None
        return super(JSONWebServiceAPIClient, self).post(
            url, parameters, headers, files, formatted_data, **kwargs
        )

    def put(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        files: Dict[str, IOBase] = {},
        data: Any = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        if data:
            formatted_data = json.dumps(data, default=Serializer.serialize)
            headers["Content-Type"] = "application/vnd.api+json"
        else:
            formatted_data = None
        return super(JSONWebServiceAPIClient, self).put(
            url, parameters, headers, files, formatted_data, **kwargs
        )

    def patch(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        files: Dict[str, IOBase] = {},
        data: Any = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        if data:
            formatted_data = json.dumps(data, default=Serializer.serialize)
            headers["Content-Type"] = "application/vnd.api+json"
        else:
            formatted_data = None
        return super(JSONWebServiceAPIClient, self).patch(
            url, parameters, headers, files, formatted_data, **kwargs
        )

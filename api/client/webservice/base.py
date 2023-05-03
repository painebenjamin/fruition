import re
import os
from io import IOBase
from typing import Optional, Callable, Any, Union, Type, Dict, List, cast

from pibble.util.helpers import url_join, resolve
from pibble.util.log import logger
from pibble.util.strings import Serializer

from pibble.api.exceptions import (
    NotFoundError,
    UnsupportedMethodError,
    AuthenticationError,
    PermissionError,
    BadRequestError,
    ConfigurationError,
    TooManyRequestsError,
)
from pibble.api.helpers.wrappers import RequestWrapper, ResponseWrapper, SessionWrapper
from pibble.api.client.base import APIClientBase

from requests import Request, Response, Session


class WebServiceAPIClientBase(APIClientBase):
    """
    A base API Client for web services.

    The constructor is intended to be called by implementing classes, as the main class should generally not be instantiated.

    Required configuration:
      1. ``client.host`` The host to connect to.

    Optional configuration:
      1. ``client.port`` The port to connect to. Defaults to 80 for HTTP and 443 for HTTPS.
      2. ``client.schema`` Either HTTP or HTTPS. Defaults to HTTP.
      3. ``client.path`` The base path to query. Defaults to "/".
      4. ``client.serializer`` The method to serialize parameters.
    """

    retry: bool
    http_session: Union[Session, SessionWrapper]

    session_class: Type[Union[Session, SessionWrapper]] = Session
    request_class: Type[Union[Request, RequestWrapper]] = Request
    response_class: Type[Union[Response, ResponseWrapper]] = Response

    def __init__(self) -> None:
        super(APIClientBase, self).__init__()
        self.headers = {"Accept-Encoding": "gzip"}

    def on_configure(self) -> None:
        """
        Builds the configuration.
        """
        self.host = self.configuration["client.host"]
        self.schema = self.configuration.get(
            "client.schema",
            "https" if self.configuration.get("client.secure", False) else "http",
        )
        self.port = int(
            self.configuration.get("client.port", 80 if self.schema == "http" else 443)
        )
        self.path = self.configuration.get("client.path", "/")
        self.base = "{0}://{1}:{2}".format(self.schema, self.host, self.port)
        self.url = url_join(self.base, self.path)
        self.requests_session = self.session_class()

    def prepare_all(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
    ) -> None:
        """
        Runs all ``prepare()`` methods.

        :param request Request: The request before it goes out.
        :param response Response: The response before it goes out.
        """
        for cls in type(self).mro():
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                cls.prepare(self, request, response)

    def parse_all(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
        raise_errors: Optional[bool] = True,
    ) -> None:
        """
        Runs all ``parse()`` methods.

        :param request Request: Tne request after it goes out.
        :param response Response: The response after it goes out.
        """
        for cls in type(self).mro():
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                if cls is type(self) and not raise_errors:
                    continue
                cls.parse(self, request, response)

    def prepare(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
    ) -> None:
        """
        This base ``prepare()`` method formats query parameters into strings. We don't use the
        default requests formatting - mostly because it doesn't obey ISO8601 for date times.

        URL Encoding is still left to be handled by the requests library, however, so there's
        no need to encode them in the serializer (just make them strings.)

        :param request Request: The request before it goes out.
        :param response Response: The response before it goes out.
        """
        if not hasattr(self, "serializer"):
            if "client.serializer" in self.configuration:
                self.serializer = self.configuration["client.serializer"]
            else:
                self.serializer = Serializer.serialize
            if type(self.serializer) in [str, bytes] and not callable(self.serializer):
                try:
                    self.serializer = resolve(self.serializer)
                except ImportError:
                    raise ConfigurationError(
                        "Cannot resolve serializer name {0}.".format(self.serializer)
                    )

        if request is not None and request.params:
            for key in request.params:
                if isinstance(request.params[key], list):
                    request.params[key] = [
                        self.serializer(param_part)
                        for param_part in request.params[key]
                    ]
                else:
                    request.params[key] = self.serializer(request.params[key])

    def raise_for_status(self, response: Union[Response, ResponseWrapper]) -> None:
        """
        Raises any status codes as exceptions.
        :param response Response: The response to the request.
        """
        if response is not None and response.status_code >= 400:
            if response.status_code == 400:
                raise BadRequestError(response.text)
            elif response.status_code == 401:
                raise AuthenticationError(response.text)
            elif response.status_code == 403:
                raise PermissionError(response.text)
            elif response.status_code == 404:
                raise NotFoundError(response.text)
            elif response.status_code == 405:
                raise UnsupportedMethodError(response.text)
            elif response.status_code == 429:
                raise TooManyRequestsError(response.text)
            else:
                raise Exception(
                    "Unhandled error code {0}.\n{1}".format(
                        response.status_code, response.text
                    )
                )

    def query(
        self,
        method: str,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        files: Dict[str, IOBase] = {},
        data: Any = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends a request using method "METHOD", with a couple caveats:
          * ``parameters`` is only used in GET, DELETE, HEAD, and OPTIONS
          * ``files`` and ``data`` is only used in PUT, POST, and PATCH

        :param url str: The URL. Will be concatenated to the end of the base URL. Defaults to "/" (i.e., the base URL)
        :param parameters dict: Parameters to be used in the URL. E.g., self.get("/home", parameters = {"user_id": 1}) will send a GET request with the URL /home?user_id=1
        :param headers dict: Headers to be used in the request. These are merged with the default headers list.
        :param data object: The data to pass in to the request. The requests module will automatically form-encode data if passed in a dictionary. Otherwise, a bytes-like object should be passed.
        :param files dict: A dictionary containing the ``file`` keyword, pointing toward either a file handle (e.g., returned from ``open()``, or a tuple containing (file_name, file_handle, content_type). These are passed as a multipart-encoded request. Note that this class does **not** support streaming files out of the gate, so this should be used sparingly, if at all.
        :returns requests.model.Response: The response to the request.
        """
        if not url.startswith("http"):
            url = url_join(self.url, url)

        raise_errors = kwargs.pop("raise_status", True)

        send_kwargs = {"stream": kwargs.pop("stream", False)}

        request_kwargs = {"headers": {**self.headers, **headers}, "params": parameters}

        if method.upper() in ["POST", "PUT", "PATCH"]:
            request_kwargs["data"] = data
            request_kwargs["files"] = files

        if self.schema == "https":
            if self.configuration.has("client.cert", "client.key"):
                logger.debug(
                    "Setting request certificate to {0}, key to {1}".format(
                        self.configuration["client.cert"],
                        self.configuration["client.key"],
                    )
                )
                send_kwargs["cert"] = (
                    self.configuration["client.cert"],
                    self.configuration["client.key"],
                )
            elif self.configuration.has("client.cert"):
                logger.debug(
                    "Setting request certificate to {0}".format(
                        self.configuration["client.cert"]
                    )
                )
                send_kwargs["cert"] = self.configuration["client.cert"]
            elif self.configuration.has("client.ca"):
                logger.debug(
                    "Setting request CA Bundle to {0}".format(
                        self.configuration["client.ca"]
                    )
                )
                send_kwargs["verify"] = self.configuration["client.ca"]
            else:
                logger.debug(
                    "No certificate/key pair of CA bundle passed, using defaults."
                )

        request = self.request_class(method.upper(), url, **request_kwargs)
        self.prepare_all(request)

        prepared = self.requests_session.prepare_request(request)  # type: ignore
        response = self.requests_session.send(prepared, **send_kwargs)  # type: ignore
        self.retry = False
        self.parse_all(request, response, raise_errors)
        if self.retry:
            return self.query(method, url, parameters, headers, files, data, **kwargs)
        elif raise_errors:
            self.raise_for_status(response)
        return response

    def download(
        self,
        method: str,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        files: Dict[str, IOBase] = {},
        data: Any = {},
        filename: Optional[str] = None,
        directory: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Uses query(), but streams the result to a local file.

        If unspecified, the filename will attempt to be parsed from the Content-Disposition header of the response. If that is absent, then the base file of the URL will be used.

        If no directory is specified, will download to cwd().

        See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query` for more information.
        """
        if "stream" in kwargs:
            del kwargs["stream"]
        result = self.query(
            method, url, parameters, headers, files, data, stream=True, **kwargs
        )

        if filename is None:
            content_disposition = result.headers.get("Content-Disposition", None)
            if content_disposition:
                logger.debug(
                    "Parsing filename from content disposition: {0}".format(
                        content_disposition
                    )
                )
                filename = (
                    re.findall("filename=(.+)", content_disposition)[0]
                    .split(";")[0]
                    .strip(" \"'")
                )
            else:
                filename = os.path.basename(url)
        if directory is None:
            directory = os.getcwd()
        if not os.path.isabs(filename):
            abs_path = os.path.abspath(os.path.join(directory, filename))
        else:
            abs_path = filename
        logger.debug(f"Writing downloaded content to {abs_path}")
        with open(abs_path, "wb") as fh:
            for chunk in result.iter_content(
                chunk_size=self.configuration.get("client.chunkSize", 8192)
            ):
                fh.write(chunk)
        return abs_path

    def get(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends a GET request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "GET", url=url, parameters=parameters, headers=headers, **kwargs
        )

    def delete(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends a DELETE request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "DELETE", url=url, parameters=parameters, headers=headers, **kwargs
        )

    def head(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends a HEAD request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "HEAD", url=url, parameters=parameters, headers=headers, **kwargs
        )

    def options(
        self,
        url: str = "/",
        parameters: Dict[str, Any] = {},
        headers: Dict[str, Any] = {},
        **kwargs: Any,
    ) -> Union[Response, ResponseWrapper]:
        """
        Sends an OPTIONS request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "OPTIONS", url=url, parameters=parameters, headers=headers, **kwargs
        )

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
        return self.query(
            "POST",
            url=url,
            parameters=parameters,
            data=data,
            files=files,
            headers=headers,
            **kwargs,
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
        """
        Sends a PUT request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "PUT",
            url=url,
            parameters=parameters,
            data=data,
            files=files,
            headers=headers,
            **kwargs,
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
        """
        Sends a PATCH request. See :func:`pibble.api.client.webservice.base.WebServiceAPIClientBase.query`
        """
        return self.query(
            "PATCH", url=url, data=data, files=files, headers=headers, **kwargs
        )

    def listMethods(self) -> List[str]:
        """
        Unless overridden, this will list the default functions.
        """
        return [
            "get",
            "post",
            "put",
            "delete",
            "patch",
            "options",
            "head",
            "query",
            "download",
        ]

    def __getitem__(self, method_name: str) -> Callable:
        """
        Overrides object[item] calls. This is used for exposing methods to external services, and can be overridden.

        :raises KeyError: when method is not exposed.
        """
        func = {
            "get": self.get,
            "post": self.post,
            "put": self.put,
            "delete": self.delete,
            "patch": self.patch,
            "head": self.head,
            "options": self.options,
        }.get(method_name.lower(), None)
        if not func:
            raise KeyError(method_name)
        return cast(Callable, func)

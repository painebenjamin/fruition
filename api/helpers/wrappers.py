import io
import os
import json
import zlib
import tempfile
import datetime

from typing import Any, Union, Iterator, Optional, Literal, List
from urllib.parse import urlencode
from http.cookies import SimpleCookie

from pibble.api.client.base import APIClientBase
from pibble.api.server.base import APIServerBase
from pibble.util.strings import decode, encode, parse_url_encoded, parse_multipart
from pibble.util.helpers import (
    DecompressedIterator,
    CaseInsensitiveDict,
    FlexibleJSONDecoder,
)

__all__ = [
    "RequestWrapper",
    "ResponseWrapper",
    "SessionWrapper",
    "WSGIEnvironmentWrapper",
    "StartResponseWrapper",
]


class NoDefault:
    pass


class POSTWrapper:
    """
    Used for the request.POST wrapper provided by webob.

    >>> wrapper = POSTWrapper('email=benjamin%40pibble.com&password=mypassword')
    >>> wrapper['email']
    'benjamin@pibble.com'
    >>> wrapper['password']
    'mypassword'
    """

    def __init__(self, body: str, content_type: Optional[str] = None):
        self.body = body
        if content_type is not None and "json" in content_type:
            self.decoded = json.loads(body, cls=FlexibleJSONDecoder)
        elif content_type is not None and "multi" in content_type:
            self.decoded = parse_multipart(f"Content-Type: {content_type}\r\n{body}")
        else:
            self.decoded = parse_url_encoded(body)

    def __getitem__(self, key: str) -> Any:
        """
        Allows for POST[x] calls.
        """
        if isinstance(self.decoded, dict):
            return self.decoded[key]
        raise ValueError("No key-value pairs present.")

    def __iter__(self) -> Iterator[str]:
        """
        Allows for iterating over keys.
        """
        if not isinstance(self.decoded, dict):
            raise ValueError("No key-value pairs present.")
        for key in self.decoded:
            yield key

    def __contains__(self, key: str) -> bool:
        """
        Allows for 'x in POST' calls.
        """
        if not isinstance(self.decoded, dict):
            raise ValueError("No key-value pairs present.")
        return key in self.decoded

    def get(self, key: str, default: Any = NoDefault) -> Any:
        """
        Allows a dict-list .get().
        """
        try:
            return self[key]
        except KeyError:
            if default is NoDefault:
                raise
            return default


class GETWrapper:
    """
    Used for the request.GET wrapper provided by webob.

    This works almost exactly like a dictionary, with the excetion of the
    `getall` method, which returns a list for each key.
    """

    def __init__(self, params: dict):
        self.params = params

    def get(self, item: str, default: Any = NoDefault) -> Any:
        try:
            return self[item]
        except KeyError:
            if default is not NoDefault:
                return default
            raise

    def getall(self, item: str) -> list:
        try:
            value = self[item]
            if not isinstance(value, list):
                return [value]
            return value
        except KeyError:
            return []

    def __getitem__(self, item: str) -> Any:
        return self.params[item]

    def __iter__(self) -> Iterator[str]:
        for key in self.params:
            yield key


class RequestWrapper:
    """
    The RequestWrapper class lets us create a request that behaves like
    a normal API request, but is instantiated by the programmer as needed.
    """

    client: Optional[APIClientBase]
    server: Optional[APIServerBase]
    body: Optional[bytes]
    user_agent: Optional[str]

    method: str
    headers: CaseInsensitiveDict
    params: dict
    url: str
    remote_addr: str

    def __init__(self, method: str, url: str, **kwargs: Any):
        self.method = method
        self.url = url
        self.remote_addr = kwargs.get("remote_addr", "")

        self.headers = CaseInsensitiveDict()

        headers = kwargs.get("headers", {})
        params = kwargs.get("params", {})
        body = kwargs.get("body", None)
        data = kwargs.get("data", None)
        files = kwargs.get("files", None)

        self.user_agent = kwargs.get("user_agent", "pibble")

        if isinstance(headers, dict):
            for key in headers:
                self.headers[key] = headers[key]

        if isinstance(params, dict):
            self.params = params
        else:
            self.params = {}

        if isinstance(body, str):
            self.body = encode(body)
        elif isinstance(body, bytes):
            self.body = body
        elif isinstance(data, dict):
            if "json" in headers.get("Content-Type", "application/json").lower():
                self.body = encode(json.dumps(data))
            else:
                self.body = encode(urlencode(data))
        elif data is not None:
            if isinstance(data, bytes):
                self.body = data
            else:
                self.body = encode(data)
        else:
            self.body = None

    @property
    def GET(self) -> GETWrapper:
        """
        Wraps the params dict in a GETWrapper.
        """
        return GETWrapper(self.params)

    @property
    def POST(self) -> POSTWrapper:
        """
        Wraps the body in a POSTWrapper.
        """
        if self.body is not None:
            return POSTWrapper(decode(self.body), self.content_type)
        return POSTWrapper("")

    @property
    def cookies(self) -> dict:
        """
        Turns the cookie header into a dict.
        """
        cookie: SimpleCookie = (
            SimpleCookie()
        )  # Why do I have to type annotate this, mypy?
        cookie.load(self.headers.get("cookie", ""))
        return {k: v.value for k, v in cookie.items()}

    @property
    def body_file(self) -> io.BufferedReader:
        """
        We don't always write to a file, since we aren't actually reading from a
        socket. However, some methods want to read the file itself, so when requested,
        we write the contents to a tempfile.
        """
        if not hasattr(self, "_body_file"):
            fd, self._body_file = tempfile.mkstemp()
            os.close(fd)
            if self.body is not None:
                open(self._body_file, "wb").write(self.body)
            self._body_file_handle = open(self._body_file, "rb")
        return self._body_file_handle

    @property
    def text(self) -> str:
        """
        Decodes body bytes, if set.
        """
        if self.body is None:
            return ""
        return decode(self.body)

    @property
    def json(self) -> dict:
        """
        Decodes body as dict, if set.
        """
        if self.body is not None:
            decoded = self.POST.decoded
            if type(decoded) is dict:
                return decoded
        return {}

    @property
    def path(self) -> str:
        """
        Gets the path part of the request.
        """
        if getattr(self, "client", None) is not None:
            base = getattr(self.client, "base", "")
            if self.url.startswith(base):
                return self.url[len(base) :]
        return self.url

    @property
    def content_type(self) -> Any:
        """
        Gets the content-type header.
        """
        return self.headers.get("content-type", None)

    @property
    def content_length(self) -> int:
        """
        Gets the content-length header.
        """
        return int(self.headers.get("content-length", 0))

    def __str__(self) -> str:
        """
        Writes the RequestWrapper to a string for debugging.
        """
        return f"{self.method.upper()} {self.path}?{urlencode(self.params)}, headers: {json.dumps(self.headers)}, body: {self.text}"


class ResponseWrapper:
    """
    Similar to the RequestWrapper, this acts like a webob Response but is
    instantiated by the programmer.
    """

    client: Optional[APIClientBase]
    server: Optional[APIServerBase]
    status_code: int
    headers: CaseInsensitiveDict
    content_length: int
    app_iter: Iterator[bytes]  # server sending response
    body: bytes
    content_cache: List[bytes]

    def __init__(self) -> None:
        self.headers = CaseInsensitiveDict()
        self.content_cache = []

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        """
        Just iterates over the content set by the server and yields it.
        Ignores chunk size, but follows content encoding.

        :param chunk_size int: Ignored.
        :returns Iterable[bytes]: The response set by the server.
        """
        if self.content_cache:
            for chunk in self.content_cache:
                yield chunk
        else:
            gzipped = self.content_encoding == "gzip"
            if gzipped:
                for chunk in DecompressedIterator(self.app_iter):
                    self.content_cache.append(chunk)
                    yield chunk
            else:
                for chunk in self.app_iter:
                    self.content_cache.append(chunk)
                    yield chunk

    def set_cookie(
        self,
        cookie_name: str,
        cookie_value: Any,
        secure: bool = False,
        max_age: Optional[Union[int, datetime.timedelta]] = None,
        path: str = "/",
        domain: Optional[str] = None,
        samesite: Optional[Literal["strict", "lax", "none"]] = None,
        expires: Optional[Union[datetime.datetime, datetime.timedelta]] = None,
    ) -> None:
        """
        Uses SimpleCookie to add a cookie to the cookie header.
        """
        cookie: SimpleCookie = SimpleCookie()
        cookie[cookie_name] = cookie_value
        cookie[cookie_name]["secure"] = secure
        cookie[cookie_name]["path"] = path
        if domain is not None:
            cookie[cookie_name]["domain"] = domain
        if samesite is not None:
            cookie[cookie_name]["samesite"] = samesite
        if max_age is not None:
            if isinstance(max_age, datetime.timedelta):
                cookie[cookie_name]["max_age"] = max_age.total_seconds()
            else:
                cookie[cookie_name]["max_age"] = max_age
        elif expires is not None:
            if isinstance(expires, datetime.datetime):
                cookie[cookie_name]["expires"] = expires.strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )
            else:
                cookie[cookie_name]["expires"] = (
                    datetime.datetime.utcnow() + expires
                ).strftime("%a, %d %b %Y %H:%M:%S GMT")
        cookie_text = cookie.output(header="").strip()
        existing_cookies = self.headers.get("set-cookie", None)
        if existing_cookies is not None:
            if isinstance(existing_cookies, list):
                self.headers["set-cookie"].append(cookie_text)
            else:
                self.headers["set-cookie"] = [existing_cookies, cookie_text]
        else:
            self.headers["set-cookie"] = cookie_text

    @property
    def text(self) -> str:
        """
        Returns the body content as a unicode string.
        """
        gzipped = self.content_encoding == "gzip"
        if hasattr(self, "body"):
            if gzipped:
                return decode(zlib.decompress(self.body))
            return decode(self.body)
        elif hasattr(self, "app_iter"):
            return "".join([decode(chunk) for chunk in self.iter_content()])
        return ""

    @text.setter
    def text(self, new_text: str) -> None:
        """
        When setting text, just encode the new text to the body.
        """
        self.body = encode(new_text)

    @property
    def content(self) -> bytes:
        if hasattr(self, "body"):
            return self.body
        elif hasattr(self, "app_iter"):
            return b"".join([chunk for chunk in self.iter_content()])
        return b""

    @property
    def content_type(self) -> Any:
        return self.headers.get("content-type", None)

    @content_type.setter
    def content_type(self, new_content_type: str) -> None:
        self.headers["content-type"] = new_content_type

    @property
    def content_encoding(self) -> Any:
        return self.headers.get("content-encoding", None)

    @content_encoding.setter
    def content_encoding(self, new_content_encoding: str) -> None:
        self.headers["content-encoding"] = new_content_encoding

    @property
    def location(self) -> Any:
        return self.headers.get("location", None)

    @location.setter
    def location(self, new_location: str) -> None:
        self.headers["location"] = new_location

    def json(self) -> Any:
        """
        Loads the text as JSON. Doesn't use the Serializer, since this is
        emulating a requests.Response in this context.
        """
        return json.loads(self.text)

    def __str__(self) -> str:
        stringified = f"ResponseWrapper<{self.status_code}>"
        if self.status_code < 400:
            if self.status_code in [301, 302, 308]:
                stringified += f" Location: {self.location}"
            else:
                try:
                    stringified += f" {self.text}"
                except:
                    pass
        return stringified


class SessionWrapper:
    def send(self, request: RequestWrapper, **kwargs: Any) -> ResponseWrapper:
        """
        Each type of client has to implement this themselves.
        """
        raise NotImplementedError()

    def prepare_request(self, request: RequestWrapper) -> RequestWrapper:
        """
        Pass through the prepare_request method, which does `not` actually
        call the pibble prepare(), it is just a method required with requests.
        """
        return request


class WSGIEnvironmentWrapper:
    pass


class StartResponseWrapper:
    pass

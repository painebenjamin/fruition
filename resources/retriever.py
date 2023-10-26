from __future__ import annotations

import os

from io import IOBase
from urllib.parse import urlparse, ParseResult
from typing import Optional, Iterator, Type, Sequence, Union, List, Dict

from pibble.util.log import logger

from pibble.api.meta.base import MetaService
from pibble.api.client.webservice.base import WebServiceAPIClientBase

from pibble.api.middleware.webservice.authentication.basic import (
    BasicAuthenticationMiddleware,
)
from pibble.api.middleware.webservice.authentication.digest import (
    DigestAuthenticationMiddleware,
)
from pibble.api.middleware.webservice.authentication.oauth import (
    OAuthAuthenticationMiddleware,
)

from pibble.api.client.file.ftp import FTPClient
from pibble.api.client.file.sftp import SFTPClient

from pibble.api.configuration import APIConfiguration
from pibble.api.exceptions import ConfigurationError
from pibble.api.exceptions import NotFoundError


class Retriever:
    """
    The 'Retriever' is an abstraction for parsing and retrieving data in a standardized
    way from a URL that matches {scheme}://{path}. The scheme will determine what child
    class is instantiated, and those classes will simply implement the __iter__ method so
    that they can be iterated over.

    This is a parent class that each kind of retriever should extend from.

    Each retriever has a class variable `SCHEMES`, which determines what kind of URI
    schemas the retriever can handle.

    :param url str: The URL to retrieve, including scheme (http, ftp, file, etc.)
    :param configuration dict: Any configuration variables to pass to the instantiated client.
    """

    CHUNK_SIZE = 8192
    SCHEMES: Sequence[Union[str, None]] = []
    extension: Optional[str] = None

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        self.url = url
        self.configuration = configuration
        try:
            _, self.extension = os.path.splitext(url.path)
        except:
            self.extension = None

    def __str__(self) -> str:
        return str(self.url)

    def __iter__(self) -> Iterator[bytes]:
        raise NotImplementedError()

    @staticmethod
    def get(url: str, configuration: Optional[dict] = None) -> Retriever:
        """
        Hunts for subclasses that can handle a URL, and instantiates it.
        """
        parsed = urlparse(url)
        for cls in Retriever.__subclasses__():
            if parsed.scheme in cls.SCHEMES:
                logger.debug(
                    "Retrieving URI {0} with class {1}".format(url, cls.__name__)
                )
                return cls(parsed, configuration)
        raise NotImplementedError(
            "No retriever for URL scheme {0}".format(parsed.scheme)
        )

    def all(self) -> bytes:
        """
        Retrieves the entire contents of `self`.
        """
        buf = bytes()
        for chunk in self:
            buf += bytes(chunk)
        return buf


class HTTPRetriever(Retriever):
    """
    This retriever gets data over HTTP/HTTPS using requests.
    """

    SCHEMES = ["http", "https"]

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        super(HTTPRetriever, self).__init__(url, configuration)

        configuration_dict = {
            "client": {
                "schema": self.url.scheme,
                "host": self.url.hostname,
            }
        }

        if self.url.port:
            configuration_dict["client"]["port"] = str(self.url.port)

        api_configuration = APIConfiguration(**configuration_dict)

        if self.configuration is not None:
            api_configuration.update(**self.configuration)

        classes: List[Type] = [WebServiceAPIClientBase]
        if self.configuration is not None:
            authentication_type = api_configuration.get("authentication.type", None)
            if authentication_type == "oauth":
                classes.append(OAuthAuthenticationMiddleware)
            elif authentication_type == "basic":
                classes.append(BasicAuthenticationMiddleware)
            elif authentication_type == "digest":
                classes.append(DigestAuthenticationMiddleware)
            elif authentication_type is not None:
                raise ConfigurationError(
                    "Unknown or unsupported authentication type {0}".format(
                        authentication_type
                    )
                )

        if self.url.username and self.url.password:
            api_configuration.update(
                authentication={
                    "basic": {
                        "username": self.url.username,
                        "password": self.url.password,
                    }
                }
            )
            if BasicAuthenticationMiddleware not in classes:
                classes.append(BasicAuthenticationMiddleware)

        self.client = MetaService(
            "HTTPRetrieverClient", classes, api_configuration.configuration
        )

    def __iter__(self) -> Iterator[bytes]:
        kwargs = {}
        if self.url.params:
            kwargs["parameters"] = self.url.params

        with self.client.get(self.url.path, stream=True, **kwargs) as response:
            for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                yield chunk


class FileRetriever(Retriever):
    """
    This retriever is used for files. It allows for explicit file:// URI's,
    but it also is the default handler when a scheme is not provided.
    """

    SCHEMES = ["file", "", None]

    file_path: str

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        super(FileRetriever, self).__init__(url, configuration)
        if self.url.netloc:
            self.file_path = self.url.netloc
        elif self.url.path:
            self.file_path = self.url.path
        else:
            raise IOError("No path found at URL {0}".format(self.url))
        if not os.path.exists(self.file_path):
            raise NotFoundError("Could not find file at {0}".format(self.file_path))

    def __iter__(self) -> Iterator[bytes]:
        fp = open(self.file_path, "rb")
        try:
            while True:
                data = fp.read(self.CHUNK_SIZE)
                if not data:
                    break
                yield data
        finally:
            fp.close()


class FTPRetriever(Retriever):
    """
    Gets data from FTP, optionally secured.
    """

    SCHEMES = ["ftp", "ftps"]

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        super(FTPRetriever, self).__init__(url, configuration)

        client_config: Dict[str, Union[dict, str, int, None]] = {
            "host": self.url.hostname,
            "secure": self.url.scheme == "ftps",
            "ftp": {
                "username": self.url.username,
                "password": self.url.password,
                "chunksize": self.CHUNK_SIZE,
            },
        }

        if self.url.port:
            client_config["port"] = self.url.port

        self.client = FTPClient()
        self.client.configure(client=client_config)

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.client.readFile(self.url.path):
            yield chunk.encode("UTF-8")


class SFTPRetriever(Retriever):
    """
    Gets data from SFTP (FTP over SSH.)
    """

    SCHEMES = ["sftp"]

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        super(SFTPRetriever, self).__init__(url, configuration)

        client_config: Dict[str, Union[dict, str, int, None]] = {
            "host": self.url.hostname,
            "sftp": {
                "username": self.url.username,
                "password": self.url.password,
                "chunksize": self.CHUNK_SIZE,
            },
        }

        if self.url.port:
            client_config["port"] = self.url.port

        self.client_config = client_config

    def __iter__(self) -> Iterator[bytes]:
        client = SFTPClient()
        client.configure(client=self.client_config)
        try:
            for chunk in client.readFile(self.url.path):
                yield chunk.encode("UTF-8")
        finally:
            logger.warning("Closing client.")
            try:
                client.close()
            except:
                pass


class S3Retriever(Retriever):
    """
    Gets data from AWS S3 (Simple Storage Solution).
    """

    SCHEMES = ["s3"]

    def __init__(self, url: ParseResult, configuration: Optional[dict] = None):
        super(S3Retriever, self).__init__(url, configuration)
        try:
            import boto3
        except ImportError:
            raise ImportError("Couldn't import boto3. Run `pip install pibble[aws]` to get it.")
        self.s3 = boto3.client("s3")

    def __iter__(self) -> Iterator[bytes]:
        logger.debug(
            f"Getting data from S3 bucket {self.url.hostname},key {self.url.path[1:]}"
        )
        data = self.s3.get_object(Bucket=self.url.hostname, Key=self.url.path[1:])
        for chunk in data["Body"].iter_chunks(chunk_size=self.CHUNK_SIZE):
            yield chunk


class RetrieverIO(IOBase):
    """
    Inherit IOBase for use by anything that expects a file-like - can wrap
    around any Retriever.

    :param url str: The URL to retrieve.
    """

    def __init__(self, url: str):
        self.url = url
        self.retriever = Retriever.get(url)
        self.iterator = self.retriever.__iter__()

        self.retrieved = bytes()
        self.index = 0
        self.retrieved_all = False

    def __str__(self) -> str:
        return self.url

    def __repr__(self) -> str:
        return self.url

    def tell(self) -> int:
        return self.index

    def seek(self, offset: int, whence: Optional[int] = 0) -> int:
        if whence == 0:
            self.index = offset
        elif whence == 1:
            self.index += offset
        elif whence == 2:
            if not self.retrieved_all:
                self.read()
            self.index = len(self.retrieved) + offset
        return self.index

    def read(self, nbytes: Optional[int] = -1) -> bytes:
        read_bytes = bytes()

        if nbytes is None or nbytes < 0:
            nbytes = 1 << 64  # Set to a large amount

        if not self.retrieved_all:
            while len(self.retrieved) < self.index + nbytes:
                try:
                    next_parts = next(self.iterator)
                    self.retrieved += next_parts
                except StopIteration:
                    self.retrieved_all = True
                    break
        read_bytes = self.retrieved[self.index : self.index + nbytes]
        self.index = min(len(self.retrieved), self.index + nbytes)
        return read_bytes

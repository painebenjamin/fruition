from __future__ import annotations

import types
import subprocess
import tempfile
import os
import sys
import shutil
import copy
import functools
import datetime
import traceback

from pibble.api.base import APIBase
from pibble.api.client.base import APIClientBase
from pibble.api.configuration import APIConfiguration
from pibble.api.exceptions import ConfigurationError, ApacheThriftError

from pibble.util.log import logger
from pibble.util.strings import decode, encode
from pibble.util.helpers import find_executable, resolve

from thrift.transport import TTransport, TSocket
from thrift.protocol import TBinaryProtocol

from typing import Type, Optional, Any, Union, List
from types import ModuleType


class ApacheThriftHandler:
    """
    A meta class from which handlers should inherit.

    :param configuration pibble.api.configuration.APIConfiguration: The configuration. If passed as a dict, will be instantiated to APIConfiguration.
    """

    def __init__(self, configuration: Union[dict, APIConfiguration]):
        if isinstance(configuration, dict):
            self.configuration = APIConfiguration(**configuration)
        else:
            self.configuration = configuration


class ApacheThriftBufferedTransportFactory(TTransport.TBufferedTransportFactory):  # type: ignore
    """
    A small class that wraps around the buffered transport factory.

    The point of this is to retrieve the socket so we can do logic based on the local or remote
    address. Normally this is hidden to the handler.

    :param client thrift.TSocket.TSocket: The input/output socket used by the transport factory.
    :returns TTransport.TBufferedTransport: The transport, instantiated by the superclass :class:`TTransport.TBufferedTransportFactory`.
    """

    def getTransport(self, client: TSocket.TSocket) -> TTransport:
        self.client = client
        return super(ApacheThriftBufferedTransportFactory, self).getTransport(client)


class ApacheThriftRequest:
    """
    A wrapper for a thrift request, to be passed to middleware.

    :param handler ThriftHandler: The handler.
    :param method str: The method name.
    :param args tuple: Arguments passed into the function.
    :param kwargs tuple: Keyword arguments passed into the function.
    """

    def __init__(
        self,
        handler: Union[ApacheThriftServerHandler, APIClientBase],
        method: str,
        *args: Any,
        **kwargs: Any,
    ):
        self.handler = handler
        self.method = method
        self.args = args
        self.kwargs = kwargs


class ApacheThriftResponse:
    """
    A wrapper for a thrift response, to be passed to middleware.

    :param handler ThriftHandler: The handler.
    :param request ThriftRequest: The request.
    :param response_type int: Indicates where an error occurred or not.
    :param response object: Either an exception, or the response type.
    """

    OK = 0
    ERROR = 1

    def __init__(
        self,
        handler: Union[ApacheThriftServerHandler, APIClientBase],
        request: ApacheThriftRequest,
        response_type: int,
        response: Any,
    ):
        self.handler = handler
        self.request = request
        self.response_type = response_type
        self.response = response


class ApacheThriftServerHandler:
    """
    A small wrapper that will catch exceptions raised by a handler, then wrap then in a
    :class:`pibble.api.exceptions.ThriftError` which is itself a wrapper of a `thrift.transport.TTransport.TTransportException`.

    The reason we go through this is so we can actually get the exception raised by the handler during the *process* step, rather than it being eaten up by the thrift handler.
    """

    def __init__(self, server: APIBase, interface: Any, handler: Any):
        self.server = server
        self.interface = interface
        self.handler = handler
        for method in dir(self.interface):
            if callable(getattr(self.interface, method)) and not method.startswith("_"):
                setattr(self, method, functools.partial(self._call_method, method))

    def _prepare(self, request: ApacheThriftRequest) -> None:
        for cls in reversed(type(self.server).mro()):
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                logger.debug(
                    "Preparing request/response in class {0}".format(cls.__name__)
                )
                cls.prepare(self.server, request)

    def _parse(self, response: ApacheThriftResponse) -> None:
        for cls in reversed(type(self.server).mro()):
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                logger.debug(
                    "Parsing request/response in class {0}".format(cls.__name__)
                )
                cls.parse(self.server, response)

    def _call_method(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """
        Calls the underlying handler method, and will wrap any exceptions in an ApacheThriftError.

        :param method str: The method name.
        :param args tuple: The arguments to pass in.
        :param kwargs dict: The keyword arguments to pass in.
        :raises ThriftError: When **any** exception occurs in the handler layer.
        """

        logger.debug(
            "Thrift server received call for method '{0}', arguments are {1}.".format(
                method, ", ".join([str(arg) for arg in args])
            )
        )
        request = ApacheThriftRequest(self, method, *args, **kwargs)
        try:
            self._prepare(request)
            logger.debug(
                "Calling {0} with args {1}, kwargs {2}".format(
                    method, request.args, request.kwargs
                )
            )
            response_body = getattr(self.handler, method)(
                *request.args, **request.kwargs
            )
            response_type = ApacheThriftResponse.OK
        except Exception as ex:
            logger.debug(traceback.format_exc())
            response_body = ex
            response_type = ApacheThriftResponse.ERROR

        response = ApacheThriftResponse(self, request, response_type, response_body)
        self._parse(response)

        if response.response_type == ApacheThriftResponse.ERROR:
            logger.error(
                "Final response from thrift server is error {0}({1})".format(
                    type(response.response).__name__, str(response.response)
                )
            )
            if not isinstance(response.response, ApacheThriftError):
                raise ApacheThriftError(response.response)
            raise response.response
        return response.response


class TTransitiveMemoryBuffer(TTransport.TTransportBase):  # type: ignore
    """
    A class for holding thrift messages in memory until read.

    Basically just a wrapper around a bytearray(). This is implemented
    because TMemoryBuffer() is read OR write, not both.

    >>> from pibble.api.helpers.apachethrift import TTransitiveMemoryBuffer
    >>> buf = TTransitiveMemoryBuffer([1,2,3])
    >>> buf.read(1)
    b'\\x01'
    >>> buf.read(2)
    b'\\x02\\x03'
    """

    def __init__(self, data: Optional[bytearray] = None):
        if data is None:
            self.buf = bytearray()
        else:
            self.buf = bytearray(data)

    def write(self, buf: Union[bytes, int, str]) -> None:
        if isinstance(buf, int):
            self.buf.append(buf)
        elif isinstance(buf, str):
            self.buf.extend(encode(buf))
        elif isinstance(buf, bytes):
            self.buf.extend(buf)

    def read(self, sz: int) -> bytes:
        chunk = copy.copy(self.buf[:sz])
        self.buf = self.buf[sz:]
        return bytes(chunk)

    def flush(self) -> None:
        pass

    def isOpen(self) -> bool:
        return True

    def close(self) -> None:
        pass


class ApacheThriftPickler:
    """
    Converts or reverts a thrift object into a serialized bytestream.

    :param protocol type: Change the protocol from binary to something else.
    """

    BUFFER_SIZE = 1024

    def __init__(
        self,
        protocol: Type[
            TBinaryProtocol.TBinaryProtocol
        ] = TBinaryProtocol.TBinaryProtocol,
    ):
        self.transport = TTransitiveMemoryBuffer()
        self.protocol = protocol(self.transport)

    def pickle(self, thrift_object: Any) -> bytes:
        """
        Converts a compiled thrift object into a byte string.

        :param thrift_object object: A compiled thrift object.
        :returns bytes: The byte stream encoding of the response.
        """

        thrift_object.write(self.protocol)
        converted = bytes()

        data = self.transport.read(ApacheThriftPickler.BUFFER_SIZE)
        while data:
            converted += data
            data = self.transport.read(ApacheThriftPickler.BUFFER_SIZE)

        return converted

    def unpickle(self, thrift_type: Type, pickled: Any) -> Any:
        """
        Converts a byte string into the pickled object.

        :param thrift_type type: The object type, uninstantiated.
        :param pickled bytes: The byte string returned from .pickle().
        :returns thrift_type: The instantiated type, with values from the pickled string.
        """
        self.transport.write(pickled)
        thrift_object = thrift_type()
        thrift_object.read(self.protocol)

        return thrift_object


class ApacheThriftCompiler:
    """
    An on-the-fly thrift compiler.

    Should probably not be used in production.
    """

    def __init__(self, thrift_file: str):
        self.thrift_file = thrift_file
        # Try to find namespace
        for line in open(self.thrift_file, "r").readlines():
            if line.strip().startswith("namespace"):
                try:
                    split = line.split()
                    if split[1] == "py":
                        self.namespace = split[2]
                        return
                except IndexError:
                    continue
        # Couldn't find namespace, set to basename of thrift file
        self.namespace, _ = os.path.splitext(os.path.basename(self.thrift_file))

    def compile(self) -> types.ModuleType:
        logger.info("On-the-fly compiling thrift IDL {0}".format(self.thrift_file))
        thriftbin = str(find_executable("thrift"))
        tmpdir = tempfile.mkdtemp()
        try:
            process = subprocess.Popen(
                [thriftbin, "-r", "--gen", "py", self.thrift_file],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = process.communicate()
            if process.returncode != 0:
                raise ConfigurationError(
                    "Could not compile thrift file {0}. Return code {1}\nstdout: {2}stderr: \n{3}".format(
                        self.thrift_file, process.returncode, decode(out), decode(err)
                    )
                )
            path = copy.deepcopy(sys.path)
            try:
                logger.debug(
                    "Importing thrift IDL {0} namespace {1}".format(
                        self.thrift_file, self.namespace
                    )
                )
                sys.path.append(os.path.join(tmpdir, "gen-py"))
                module = __import__(self.namespace, locals(), globals())

                def recurse(module: ModuleType, fromlist: List[str] = []) -> None:
                    for submodule_name in getattr(module, "__all__", []):
                        logger.debug(
                            "Importing thrift IDL {0} namespace {1}".format(
                                self.thrift_file,
                                ".".join(fromlist + [module.__name__, submodule_name]),
                            )
                        )
                        setattr(
                            module,
                            submodule_name,
                            __import__(
                                ".".join(fromlist + [module.__name__, submodule_name]),
                                locals(),
                                globals(),
                                fromlist=[".".join(fromlist)],
                            ),
                        )
                        recurse(getattr(module, submodule_name))

                recurse(module)
                return module
            finally:
                sys.path = path
        finally:
            shutil.rmtree(tmpdir)


class ApacheThriftService:
    """
    A helper class to be instantiated by utilizing APIs.
    """

    def __init__(
        self,
        configuration: APIConfiguration,
        instantiate_handler: Optional[bool] = False,
    ):
        self.configuration = configuration
        import_definition = self.configuration.get("thrift.import", None)

        if import_definition:
            self.definition = resolve(
                import_definition, local=dict(locals(), **globals())
            )
        else:
            self.definition = self.configuration.get("thrift.compile", None)

        if self.definition is not None:
            module = ApacheThriftCompiler(self.definition).compile()
            self.service = getattr(module, self.configuration["thrift.service"])
            self.types = module.ttypes
            self.configuration["thrift.types"] = self.types
            logger.debug(
                "Service defined as {0} imported from module as {1}".format(
                    self.configuration["thrift.service"], self.service
                )
            )
        else:
            self.service = self.configuration["thrift.service"]
            self.types = self.configuration["thrift.types"]

            if type(self.service) is str:
                try:
                    self.service = resolve(
                        self.service, local=dict(locals(), **globals())
                    )
                    self.configuration["thrift.service"] = self.service
                except ImportError as ex:
                    raise ConfigurationError(str(ex))

            if type(self.types) is str:
                try:
                    self.types = resolve(self.types, local=dict(locals(), **globals()))
                    self.configuration["thrift.types"] = self.types
                except ImportError as ex:
                    raise ConfigurationError(str(ex))

        try:
            self.interface = self.service.Iface
        except:
            logger.error(
                "Couldn't find auto-generated 'IFace' object in service {0}".format(
                    self.service
                )
            )
            raise

        self.handler = self.configuration.get("thrift.handler", None)

        if self.handler is not None:
            if type(self.handler) is str:
                try:
                    self.handler = resolve(
                        self.handler, local=dict(locals(), **globals())
                    )
                except ImportError as ex:
                    raise ConfigurationError(str(ex))

            if type(self.handler) is type:
                if instantiate_handler:
                    self.handler = self.handler(self.configuration)
        else:
            logger.info(
                "No handler specified for thrift service. This configuration will not function as a server."
            )

    class ApacheThriftServiceError:
        """
        Wraps around an error to keep track of when it happened.
        """

        def __init__(self, error: str) -> None:
            self.error = error
            self.time = datetime.datetime.now()

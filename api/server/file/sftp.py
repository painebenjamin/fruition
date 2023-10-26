from __future__ import annotations

import socket
import os
import errno

try:
    from paramiko import (  # type: ignore
        AUTH_SUCCESSFUL,
        AUTH_FAILED,
        OPEN_SUCCEEDED,
        SFTP_OK,
        ServerInterface as ParamikoServerInterface,
        SFTPServerInterface as ParamikoSFTPParamikoServerInterface,
        SFTPServer as ParamikoSFTPServer,
        SFTPHandle as ParamikoSFTPHandle,
        SFTPAttributes,
        RSAKey,
        Transport,
    )
except ImportError:
    raise ImportError("Couldn't find paramiko. Run `pip install pibble[ftp]` to get it.")

from typing import Callable, Any, Union, Optional, List

from pibble.util.log import logger
from pibble.api.server.base import APIServerBase
from pibble.api.exceptions import AuthenticationError
from pibble.api.configuration import APIConfiguration
from pibble.api.helpers.authentication import APIAuthenticationSource


class SFTPRequest:
    """
    A wrapper around each request for processing.
    """

    def __init__(self, server: APIServerBase, fn: Callable, *args: Any) -> None:
        self.server = server
        self.fn = fn
        self.args = args

    def __call__(self) -> Any:
        return self.fn(self.server, *self.args)


class SFTPResponse:
    """
    A wrapper around each response for processing.
    """

    def __init__(self, request: Any, response: Any) -> None:
        self.request = request
        self.response = response

    def __call__(self) -> Any:
        return self.response


class SFTPProcessor:
    """
    A wrapper around requests and responses for processing.
    """

    def wrap(self, fn: Callable) -> Callable:
        def wrapper(stub: Any, *args: Any) -> Any:
            request = SFTPRequest(stub, fn, *args)
            stub.server.server.parse_all(request)
            response = SFTPResponse(request, request())
            stub.server.server.prepare_all(response)
            return response()

        return wrapper


class StubServer(ParamikoServerInterface):
    """
    This is the server instantiated for the paramiko transport.

    Adapted from https://github.com/rspivak/sftpserver

    See :class:pibble.api.server.file.sftp.ParamikoSFTPServer for more information.
    """

    publickey: Optional[APIAuthenticationSource]
    password: Optional[APIAuthenticationSource]

    def __init__(self, server: Any) -> None:
        super(StubServer, self).__init__()
        self.server = server
        self.configuration = self.server.configuration
        if isinstance(self.configuration.get("authentication.driver", None), list):
            if "rsa" in self.configuration["authentication.driver"]:
                rsa_configuration = APIConfiguration(
                    authentication=self.configuration["authentication"]
                )
                rsa_configuration["authentication.driver"] = "rsa"
                self.publickey = APIAuthenticationSource(rsa_configuration)
            else:
                self.publickey = None
            self.configuration["authentication.driver"] = [
                drivername
                for drivername in self.configuration["authentication.driver"]
                if drivername != "rsa"
            ][0]
            self.password = APIAuthenticationSource(self.configuration)
        elif self.configuration.get("authentication.driver", None) == "rsa":
            self.publickey = APIAuthenticationSource(self.configuration)
            self.password = None
        elif self.configuration.get("authentication.driver", None) is not None:
            self.publickey = None
            self.password = APIAuthenticationSource(self.configuration)
        else:
            self.password = None
            self.publickey = None

    def get_allowed_auths(self, username: str) -> str:
        allowed = []
        if self.publickey is not None:
            allowed.append("publickey")
        if self.password is not None:
            allowed.append("password")
        return ",".join(allowed)

    def check_auth_publickey(self, username: str, key: Any) -> Any:
        if self.publickey is not None:
            try:
                self.publickey.validate(username, key)
                return AUTH_SUCCESSFUL
            except AuthenticationError:
                pass
        return AUTH_FAILED

    def check_auth_password(self, username: str, password: str) -> Any:
        if self.password is not None:
            try:
                self.password.validate(username, password)
                return AUTH_SUCCESSFUL
            except AuthenticationError:
                pass
        return AUTH_FAILED

    def check_channel_request(self, kind: Any, chanid: int) -> Any:
        return OPEN_SUCCEEDED


class SFTPStubHandler(ParamikoSFTPHandle):
    """
    This is the handler instantiated for the paramiko transport.

    Adapted from https://github.com/rspivak/sftpserver

    See :class:pibble.api.server.file.sftp.ParamikoSFTPServer for more information.
    """

    def stat(self) -> Union[SFTPAttributes, int]:
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))  # type: ignore
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)

    def chattr(self, attr: Union[SFTPAttributes, int]) -> Any:
        try:
            ParamikoSFTPServer.set_file_attr(self.filename, attr)  # type: ignore
            return SFTP_OK
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)


class SFTPStubServer(ParamikoSFTPParamikoServerInterface):
    """
    This is the SFTP server instantiated for the paramiko transport.

    Adapted from https://github.com/rspivak/sftpserver

    See :class:pibble.api.server.file.sftp.ParamikoSFTPServer for more information.
    """

    processor = SFTPProcessor()
    _root = os.getcwd()

    def __init__(self, server: Any) -> None:
        super(SFTPStubServer, self).__init__(server)
        self.server = server
        self._root = server.configuration.get("server.sftp.root.directory", os.getcwd())
        self._relative = server.configuration.get("server.sftp.root.relative", True)

    def _realpath(self, path: str) -> str:
        if os.path.isabs(path) and not self._relative:
            _path = path
        else:
            _path = os.path.join(self._root, self.canonicalize(path.strip("/")))
        if os.path.commonprefix([self._root, _path]) != self._root:
            raise OSError(errno.EACCES, "Access denied.")
        return _path

    @processor.wrap
    def list_folder(self, path: str) -> Union[List[SFTPAttributes], int]:
        try:
            path = self._realpath(path)
            out = []
            flist = os.listdir(path)
            for fname in flist:
                attr = SFTPAttributes.from_stat(os.stat(os.path.join(path, fname)))
                attr.filename = fname
                out.append(attr)
            return out
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)

    @processor.wrap
    def stat(self, path: str) -> Union[SFTPAttributes, int]:
        try:
            path = self._realpath(path)
            return SFTPAttributes.from_stat(os.stat(path))
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)

    @processor.wrap
    def lstat(self, path: str) -> Union[SFTPAttributes, int]:
        try:
            path = self._realpath(path)
            return SFTPAttributes.from_stat(os.lstat(path))
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)

    @processor.wrap
    def open(
        self, path: str, flags: int, attr: SFTPAttributes
    ) -> Union[SFTPStubHandler, int]:
        try:
            path = self._realpath(path)
            binary_flag = getattr(os, "O_BINARY", 0)
            flags |= binary_flag
            mode = getattr(attr, "st_mode", None)
            if mode is not None:
                fd = os.open(path, flags, mode)
            else:
                fd = os.open(path, flags, 0o666)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS  # type: ignore
            ParamikoSFTPServer.set_file_attr(path, attr)
        if flags & os.O_WRONLY:
            if flags & os.O_APPEND:
                fstr = "ab"
            else:
                fstr = "wb"
        elif flags & os.O_RDWR:
            if flags & os.O_APPEND:
                fstr = "a+b"
            else:
                fstr = "r+b"
        else:
            fstr = "rb"
        try:
            f = os.fdopen(fd, fstr)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        fobj = SFTPStubHandler(flags)
        fobj.filename = path  # type: ignore
        fobj.readfile = f  # type: ignore
        fobj.writefile = f  # type: ignore
        return fobj

    @processor.wrap
    def remove(self, path: str) -> Any:
        try:
            path = self._realpath(path)
            os.remove(path)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def rename(self, oldpath: str, newpath: str) -> Any:
        try:
            oldpath = self._realpath(oldpath)
            newpath = self._realpath(newpath)
            os.rename(oldpath, newpath)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def mkdir(self, path: str, attr: SFTPAttributes) -> Any:
        try:
            path = self._realpath(path)
            os.mkdir(path)
            if attr is not None:
                ParamikoSFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def rmdir(self, path: str) -> Any:
        try:
            path = self._realpath(path)
            os.rmdir(path)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def chattr(self, path: str, attr: SFTPAttributes) -> Any:
        try:
            path = self._realpath(path)
            ParamikoSFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def symlink(self, target_path: str, path: str) -> Any:
        try:
            path = self._realpath(path)
            if (len(target_path) > 0) and (target_path[0] == "/"):
                target_path = os.path.join(self._root, target_path[1:])
                if target_path[:2] == "//":
                    target_path = target_path[1:]
            else:
                abspath = os.path.join(os.path.dirname(path), target_path)
                if abspath[: len(self._root)] != self._root:
                    target_path = "<error>"
            os.symlink(target_path, path)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        return SFTP_OK

    @processor.wrap
    def readlink(self, path: str) -> Union[str, int]:
        try:
            path = self._realpath(path)
            symlink = os.readlink(path)
        except OSError as e:
            return ParamikoSFTPServer.convert_errno(e.errno)
        if os.path.isabs(symlink):
            if symlink[: len(self._root)] == self._root:
                symlink = symlink[len(self._root) :]
                if (len(symlink) == 0) or (symlink[0] != "/"):
                    symlink = "/" + symlink
            else:
                symlink = "<error>"
        return symlink


class SFTPServer(APIServerBase):
    """
    A server that handles SFTP connections.

    This uses the Paramiko SFTP servre to handle protocol connections. You have some
    limited control on how this works using configuration.

    Required configuration:
      - server.host
      - server.port

    Optional configuration:
      - server.sftp.keyfile: The server key file.
      - server.sftp.keybits: When not using a key file, the number of bits to generate for the server key.
      - server.sftp.root.directory: The root directory.
      - server.sftp.root.relative: Force all requests to be relative to the root, rather than absolute.

    For authentication, there is a unique feature in the SFTP server that you can use two types of
    authentication simultaneously, these can be passed as an array into `authentication.driver`.

    For example:

    authentication.driver = "rsa" - only use key authentication
    authentication.driver = "<anything but rsa>" - only use username/password authentication
    authentication.driver = ["rsa", "<anything but rsa>"] - use both.

    :see:pibble.api.helpers.authentication.APIAuthenticationSource
    """

    def on_configure(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        self.socket.bind(
            (self.configuration["server.host"], int(self.configuration["server.port"]))
        )
        self.keyfile = self.configuration.get("server.sftp.keyfile", None)
        if self.keyfile is not None:
            self.key = RSAKey.from_private_key_file(self.keyfile)
        else:
            self.key = RSAKey.generate(
                self.configuration.get("server.sftp.keybits", 1024)
            )

    @classmethod
    def parse(cls, request: SFTPRequest) -> None:
        """
        A log interrupt for debugging purposes.
        """
        logger.info(
            "Executing command {0} with arguments {1}".format(
                request.fn.__name__, ", ".join([str(arg) for arg in request.args])
            )
        )

    def parse_all(self, request: SFTPRequest) -> None:
        """
        Run all parse() methods.
        """
        for cls in type(self).mro():
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                cls.parse(request)  # type: ignore

    def prepare_all(self, response: SFTPResponse) -> None:
        """
        Run all prepare() methods.
        """
        for cls in type(self).mro():
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                cls.prepare(response)  # type: ignore

    def serve(self) -> None:
        """
        Runs the server synchronously.
        """
        self.socket.listen(self.configuration.get("server.backlog", 10))

        while True:
            try:
                conn, addr = self.socket.accept()
                logger.info("Accepting connection from {0}".format(addr))
                transport = Transport(conn)
                transport.add_server_key(self.key)
                transport.set_subsystem_handler(
                    "sftp", ParamikoSFTPServer, SFTPStubServer
                )
                server = StubServer(self)
                transport.start_server(server=server)
                channel = transport.accept()
                # while transport.is_active():
                #   time.sleep(1)
                # TODO: Why was the above ever here? I removed it and it fixed
                # multiple active connections...but was there a reason that was
                # disallowed in the first place?
            except Exception as ex:
                if isinstance(ex, KeyboardInterrupt):
                    raise ex
                logger.error(
                    "Exception caught when establishing SFTP connection. {0}()\n{1}".format(
                        type(ex).__name__, str(ex)
                    )
                )

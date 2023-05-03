import os
import stat
import paramiko

try:
    import pwd
except ImportError:
    pass

import paramiko.ssh_exception

from typing import Iterable, Optional, Any, Mapping, Union, cast

from pibble.api.exceptions import (
    NotFoundError,
    BadRequestError,
    ConfigurationError,
    AuthenticationError,
    PermissionError as PibbleCakePermissionError,
)
from pibble.api.client.file.base import (
    FileTransferAPIClientBase,
    RemoteObject,
    ContentIterator,
)

from pibble.util.log import logger
from pibble.util.strings import encode, decode
from pibble.util.helpers import ignore_exceptions
from pibble.util.numeric import o2r8d, r8d2o


class SFTPClient(FileTransferAPIClientBase):
    """
    Wraps around Paramiko.
    """

    sftp: paramiko.SFTPClient

    def on_configure(self) -> None:
        host = self.configuration["client.host"]
        port = self.configuration.get("client.port", 22)

        gss = self.configuration.get("client.sftp.gss", False)
        gss_exchange = self.configuration.get("client.sftp.gssexchange", False)

        username = self.configuration.get("client.sftp.username", None)
        password = self.configuration.get("client.sftp.password", None)

        hostkeyfile = self.configuration.get("client.sftp.hostkeyfile", None)

        privatekeyfile = self.configuration.get("client.sftp.privatekeyfile", None)
        privatekey = self.configuration.get("client.sftp.privatekey", None)

        if not username:
            if os.name == "nt":
                raise ConfigurationError(
                    "You must provide a username on Windows sytems."
                )
            username = pwd.getpwuid(os.getuid()).pw_name  # type: ignore
            if not privatekeyfile:
                path = os.path.join(os.path.expanduser("~"), ".ssh", "id_rsa")
                if os.path.exists(path):
                    privatekeyfile = path
                else:
                    path = os.path.join(os.path.expanduser("~"), "ssh", "id_rsa")
                    if os.path.exists(path):
                        privatekeyfile = path

            if not hostkeyfile:
                path = os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")
                if os.path.exists(path):
                    hostkeyfile = path
                else:
                    path = os.path.join(os.path.expanduser("~"), "ssh", "known_hosts")
                    if os.path.exists(path):
                        hostkeyfile = path

        if not privatekey and privatekeyfile:
            privatekey = paramiko.RSAKey.from_private_key_file(privatekeyfile)

        keys: Mapping = {}
        if hostkeyfile:
            keys = paramiko.util.load_host_keys(hostkeyfile)

        if host in keys:
            hostkeytype = keys[host].keys()[0]
            hostkey = keys[host][hostkeytype]
        else:
            hostkey = None

        self.chunksize = self.configuration.get("client.sftp.chunksize", 8192)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.transport = paramiko.Transport((host, port))

        try:
            if password and privatekey:
                self.transport.start_client(event=None, timeout=15)
                self.transport.get_remote_server_key()
                self.transport.auth_publickey(username, privatekey, event=None)
                self.transport.auth_password(username, password, event=None)
            elif privatekey and not password:
                self.transport.connect(username=username, pkey=privatekey)
            elif password and not privatekey:
                self.transport.connect(username=username, password=password)
            else:
                raise ConfigurationError(
                    "Must use either user/pass authentication, key authentication, or both."
                )
        except paramiko.ssh_exception.AuthenticationException:
            raise AuthenticationError("Authentication failed.")
        except paramiko.ssh_exception.SSHException as ex:
            raise BadRequestError(
                "Error connecting to {0}:{1}. {2}".format(self.host, self.port, str(ex))
            )

        self.sftp = cast(
            paramiko.SFTPClient, paramiko.SFTPClient.from_transport(self.transport)
        )

    def close(self) -> None:
        """
        Closes the active SFTP connection.
        """
        ignore_exceptions(self.sftp.close)
        ignore_exceptions(self.transport.close)

    # Helper Functions

    def sendCommand(self, *command: str, **kwargs: Any) -> Union[str, bytes]:
        """
        Sends an arbitrary command over the underlying transport.

        :param command tuple: Any number of string arguments that comprise a command.
        :returns str: The stdout from the command.
        """

        cmd = " ".join([str(c) for c in command])
        logger.debug("Sending command {0}".format(cmd))

        session = self.sftp.sock.get_transport().open_channel(kind="session")

        try:
            session.exec_command(cmd)

            stdout = bytearray()
            stderr = bytearray()
            rc = 0

            while True:
                if session.exit_status_ready():
                    while True:
                        data = session.recv(self.chunksize)
                        if not data:
                            break
                        stdout.extend(data)
                    while True:
                        data = session.recv_stderr(self.chunksize)
                        if not data:
                            break
                        stderr.extend(data)
                    break

            rc = session.recv_exit_status()

            if rc != 0 and not kwargs.get("ignore_exceptions", False):
                raise BadRequestError(
                    "Command {0} failed with exit code {1}.\n{2}".format(
                        " ".join(command), rc, stderr
                    )
                )
            else:
                try:
                    return decode(stdout).strip()
                except UnicodeDecodeError:
                    return stdout

        finally:
            session.close()

    def getPathURI(self, path: str) -> str:
        """
        Gets an SFTP uri, included the username and password, for a resource.
        """
        if self.pathExists(path):
            return "sftp://{0}:{1}@{2}:{3}/{4}".format(
                self.username,
                self.password,
                self.host,
                self.port,
                path[1:] if path[0] == "/" else path,
            )
        raise NotFoundError(path)

    def getUIDFromUser(self, username: str) -> int:
        """
        Uses the `getent` command to get the UID from a username.

        :param username str: The username to get the ID for.
        :returns int: The UID.
        """
        try:
            return int(
                decode(self.sendCommand("getent", "passwd", username)).split(":")[2]
            )
        except paramiko.ssh_exception.SSHException:
            logger.error(
                "Received SSH exception when trying to run `getent`. It's likely the server is SFTP-only. You'll need to use an actual UID."
            )
            raise BadRequestError("UID must be an integer.")

    def getGIDFromGroup(self, group: str) -> int:
        """
        Uses the `getent` command to get the GID from a group name.

        :param group str: The group to get the ID for.
        :returns int: The GID.
        """
        try:
            return int(decode(self.sendCommand("getent", "group", group)).split(":")[2])
        except paramiko.ssh_exception.SSHException:
            logger.error(
                "Received SSH exception when trying to run `getent`. It's likely the server is SFTP-only. You'll need to use an actual GID."
            )
            raise BadRequestError("GID must be an integer.")

    def convertSFTPAttributes(
        self, attr: paramiko.SFTPAttributes, path: str = ""
    ) -> RemoteObject:
        """
        Converts the result of listdir or lstat commands into a RemoteObject.

        :param attr `paramiko.SFTPAttributes`: The attributes object returned.
        :param path str: Optional, the path in which the file was located.
        :returns RemoteObject: The converted object.
        """

        if attr.st_mode and stat.S_ISDIR(attr.st_mode):
            otype = RemoteObject.DIRECTORY
        elif attr.st_mode and stat.S_ISLNK(attr.st_mode):
            otype = RemoteObject.LINK
        else:
            otype = RemoteObject.FILE

        if attr.st_mode:
            permission = o2r8d(stat.S_IMODE(attr.st_mode))
        else:
            permission = None

        if hasattr(attr, "filename") and attr.filename:
            file_path = os.path.join(path, attr.filename)
        else:
            file_path = path

        return RemoteObject(
            otype,
            file_path,
            owner=attr.st_uid,
            group=attr.st_gid,
            modificationTime=attr.st_mtime,
            accessTime=attr.st_atime,
            permission=permission,
            length=attr.st_size,
        )

    def changeDirectory(self, path: str, **kwargs: Any) -> None:
        """
        Changes current working directory.

        :param path str: The path to change current directory to.
        """
        self.cwd = self.absPath(path)
        self.sftp.chdir(self.cwd)

    def makeDirectory(
        self,
        path: str,
        permission: Optional[int] = None,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Make a directory.

        :param path str: A directory path.
        :param permission int: Any radix-8 permission integer. Default None.
        :returns RemoteObject: The new directory.
        """
        path = self.absPath(path)
        try:
            return self.getPath(path)
        except NotFoundError:
            pass

        if permission is None:
            permission = 511

        self.sftp.mkdir(path, r8d2o(permission))

        if owner is not None or group is not None:
            self.setPathOwner(path, owner, group)

        return self.getPath(path)

    def listDirectory(
        self, path: str = "", materialize: Optional[bool] = False, **kwargs: Any
    ) -> Iterable[RemoteObject]:
        """
        Lists the contents of a directory.

        :param path str: A directory path.
        :returns iterable<RemoteObject>: The content of the directory.
        """
        path = self.absPath(path)
        if materialize:
            for attr in self.sftp.listdir_attr(path):
                yield self.convertSFTPAttributes(attr, path)
        else:
            for attr in self.sftp.listdir_iter(path):
                yield self.convertSFTPAttributes(attr, path)

    # File Operations

    def writeFile(
        self,
        path: str,
        contents: Any,
        overwrite: Optional[bool] = False,
        permission: Optional[int] = None,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Writes a file.

        :param path str: The path of the file.
        :param contents object: Either a unicode string, bytes-like object or iterable.
        :param overwrite bool: Whether or not to overwrite. Default False.
        :param permission int: Any radix-8 permission integer. Default None.
        :param owner str: The owner of the file. Default None.
        :param group str: The group of the file. Default None.
        :returns RemoteObject: The newly written remote file.
        """
        path = self.absPath(path)

        try:
            node = self.getPath(path)
            if not overwrite:
                return node
        except NotFoundError:
            pass

        fp = self.sftp.open(path, "wb", self.chunksize)
        for chunk in ContentIterator(contents):
            fp.write(encode(chunk))
        fp.close()

        if permission is not None:
            self.setPathPermission(path, permission)
        if owner is not None or group is not None:
            self.setPathOwner(path, owner, group)

        return self.getPath(path)

    def appendFile(self, path: str, contents: Any, **kwargs: Any) -> RemoteObject:
        """
        Appends contents to a file. Some implementations may not have a method
        specifically for this, so a base method is provided to do so.

        :param path str: The path of the file.
        :param contents object: Either a unicode string, bytes-like object or iterable.
        :returns RemoteObject: The newly modified remote file.
        """
        path = self.absPath(path)

        fp = self.sftp.open(path, "ab", self.chunksize)

        for chunk in ContentIterator(contents):
            fp.write(encode(chunk))
        fp.close()

        return self.getPath(path)

    def readFile(self, path: str, **kwargs: Any) -> Iterable[str]:
        """
        Reads the contents of a file.

        This should return an iterator to gradually the read the file.

        :param path str: The path of the file to read.
        :returns iterable: An iterator over the contents of the file.
        :raises `pibble.api.exceptions.NotFoundError`: When the file does not exist.
        """
        node = self.getPath(path)
        fp = self.sftp.open(path, "r", self.chunksize)

        while True:
            chunk = fp.read(self.chunksize)
            if not chunk:
                break
            try:
                yield decode(chunk)
            except Exception as ex:
                # Possibly cut off characters, try adding up to 7 more bytes
                logger.warning(
                    "Received {0}. Will add up to 7 bytes, in case a character is cut off.".format(
                        type(ex)
                    )
                )
                for i in range(7):
                    logger.debug("Trying with {0} bytes.".format(i + 1))
                    chunk += fp.read(1)
                    try:
                        yield decode(chunk)
                    except:
                        if i == 6:
                            raise
                        pass
        fp.close()

    def movePath(
        self, src: str, dest: str, overwrite: Optional[bool] = False, **kwargs: Any
    ) -> RemoteObject:
        """
        Moves a file from src to dest.

        :param src str: The source path.
        :param dest str: The destination path.
        :returns RemoteObject: The newly moved file.
        :raises `pibble.api.exceptions.NotFoundError`: When src is not found.
        """
        src = self.absPath(src)
        dest = self.absPath(dest)

        self.sftp.rename(src, dest)
        return self.getPath(dest, **kwargs)

    def pathExists(self, path: str, **kwargs: Any) -> bool:
        """
        Determine if a path exists.

        :param path str: The path to get.
        :returns bool: Whether or not it exists.
        """
        try:
            self.getPath(path)
            return True
        except NotFoundError:
            return False

    def pathIsFile(self, path: str, **kwargs: Any) -> bool:
        """
        Determine if a path is a file.

        :param path str: The path to get.
        :returns bool: If the path represents a file.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        return self.getPath(path).otype == RemoteObject.FILE

    def pathIsDirectory(self, path: str, **kwargs: Any) -> bool:
        """
        Determine if a path is a directory.

        :param path str: The path to get.
        :returns bool: If the path represents a directory.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        return self.getPath(path).otype == RemoteObject.DIRECTORY

    def pathIsLink(self, path: str, **kwargs: Any) -> bool:
        """
        Determine if a path is a link.

        :param path str: The path to get.
        :returns bool: If the path represents a link.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        return self.getPath(path).otype == RemoteObject.LINK

    def getPath(self, path: str = "/", **kwargs: Any) -> RemoteObject:
        """
        List the contents of a directory or a file.

        :param path str: The path to list. Defaults to `self.cwd`.
        :returns RemoteObject: The file or directory.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        path = self.absPath(path)
        try:
            return self.convertSFTPAttributes(self.sftp.lstat(path), path)
        except FileNotFoundError:
            raise NotFoundError("No file or directory at path '{0}'.".format(path))

    def deletePath(self, path: str, **kwargs: Any) -> bool:
        """
        Delete a path.

        :param path str: Either a file or directory path.
        :returns bool: True if successful.
        """

        try:
            node = self.getPath(path)
        except NotFoundError:
            return False

        if node.otype == RemoteObject.DIRECTORY:
            for subPath in self.listDirectory(node.path, materialize=True):
                self.deletePath(subPath.path)
            self.sftp.rmdir(node.path)
        else:
            self.sftp.remove(node.path)
        return True

    def setPathPermission(
        self, path: str, permission: int, **kwargs: Any
    ) -> RemoteObject:
        """
        Sets the permissions on a path.

        :param path str: Either a file or directory path.
        :param permission: Any radix-8 permission integer.
        :returns RemoteObject: The updated path.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """

        node = self.getPath(path)

        try:
            self.sftp.chmod(node.path, r8d2o(permission))
        except PermissionError:
            raise PibbleCakePermissionError()

        return self.getPath(path)

    def setPathOwner(
        self,
        path: str,
        owner: Optional[Union[str, int]] = None,
        group: Optional[Union[str, int]] = None,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Sets the owner, group, or both on a path.

        :param path str: Either a file or directory path.
        :param owner str: The owner name.
        :param group str: The group name.
        :returns RemoteObject: The updated path.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        :raises `pibble.api.exceptions.BadRequestError`: When both owner and group are None.
        """
        if owner is None and group is None:
            raise BadRequestError("Must include either owner, group, or both.")

        node = self.getPath(path)
        if owner is not None and isinstance(owner, int):
            owner_id = owner
        elif owner is not None:
            owner_id = self.getUIDFromUser(owner)
        else:
            owner_id = node.owner

        if group is not None and isinstance(group, int):
            group_id = group
        elif group is not None:
            group_id = self.getGIDFromGroup(group)
        else:
            group_id = node.group

        try:
            self.sftp.chown(node.path, owner_id, group_id)
        except PermissionError:
            raise PibbleCakePermissionError()

        return self.getPath(path)

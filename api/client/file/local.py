import os
import stat
import shutil
import types
import traceback

try:
    import pwd
except ImportError:
    pass

from multiprocessing import Process, Pipe
from multiprocessing.connection import Connection

from typing import Callable, Optional, Iterable, Any, cast

from pibble.api.client.file.base import (
    FileTransferAPIClientBase,
    RemoteObject,
    ContentIterator,
)
from pibble.api.exceptions import (
    NotFoundError,
    BadRequestError,
    PermissionError as PibbleLibPermissionError,
)
from pibble.util.strings import encode
from pibble.util.log import logger
from pibble.util.helpers import is_binary_file
from pibble.util.numeric import r8d2o, o2r8d


def UserContext(fn: Callable) -> Callable:
    """
    Executes a function under the context of a user (or no user.)

    Returns a callable suitable for decoration.
    """

    if os.name == "nt":
        # No user context available for windows.
        return lambda *args, **kwargs: fn(*args, **kwargs)

    def callable(*args: Any, **kwargs: Any) -> Any:
        user = kwargs.get("user", None)
        demote = False
        uid = None
        if user is not None:
            uid = pwd.getpwnam(user).pw_uid  # type: ignore
            if uid != os.getuid():  # type: ignore
                demote = True
                logger.debug(
                    "Demoting to user {0} ({1}) for process {2}::{3}".format(
                        user, uid, os.getpid(), fn.__name__
                    )
                )

        def context(pipe: Connection) -> None:
            if uid is not None:
                os.setuid(uid)  # type: ignore
            try:
                result = fn(*args, **kwargs)
                if isinstance(result, types.GeneratorType):
                    result = [r for r in result]
            except Exception as ex:
                if isinstance(ex, PermissionError):
                    ex = PibbleLibPermissionError(str(ex))
                setattr(ex, "tb", traceback.format_exc())
                result = ex

            pipe.send(result)

        if demote:
            pipe_r, pipe_s = Pipe()

            p = Process(target=context, args=(pipe_s,))
            p.start()
            p.join()

            result = pipe_r.recv()
            pipe_r.close()
            pipe_s.close()

            if isinstance(result, Exception):
                raise result
            return result
        else:
            if user is not None:
                logger.debug(
                    "Not demoting user {0} ({1}) for process {2}::{3}".format(
                        user, uid, os.getpid(), fn.__name__
                    )
                )
            return fn(*args, **kwargs)

    return callable


class LocalFileTransferAPIClient(FileTransferAPIClientBase):
    """
    A base class for file transfer clients.
    """

    @UserContext
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
        :param owner str: The owner of the file. Default None.
        :param group str: The group of the file. Default None.
        :returns RemoteObject: The new directory.
        """
        path = self.absPath(path)
        if permission:
            permission = r8d2o(permission)
        else:
            permission = 0o700

        os.makedirs(path, permission)

        if os.name != "nt":
            if owner is not None:
                uid = pwd.getpwnam(owner).pw_uid  # type: ignore
            else:
                uid = -1
            if group is not None:
                gid = pwd.getpwnam(group).pw_uid  # type: ignore
            else:
                gid = -1

            os.chown(path, uid, gid)  # type: ignore
        return cast(RemoteObject, self.getPath(path))

    @UserContext
    def listDirectory(self, path: str, **kwargs: Any) -> Iterable[RemoteObject]:
        """
        Lists the contents of a directory.

        :param path str: A directory path.
        :returns iterable<RemoteObject>: The content of the directory.
        """
        node = self.getPath(path)
        if node.otype != RemoteObject.DIRECTORY:
            raise BadRequestError("Path {0} is not a directory.".format(node.path))
        for subpath in os.listdir(node.path):
            yield self.getPath(os.path.join(node.path, subpath))

    # File Operations

    @UserContext
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
        if os.path.exists(path) and not overwrite:
            return cast(RemoteObject, self.getPath(path))
        else:
            with open(path, "wb") as fp:
                for part in ContentIterator(contents):
                    fp.write(encode(part))
            if permission is not None:
                self.setPathPermission(path, permission)
            if owner is not None or group is not None:
                self.setPathOwner(path, owner, group)
        return cast(RemoteObject, self.getPath(path))

    @UserContext
    def appendFile(self, path: str, contents: Any, **kwargs: Any) -> RemoteObject:
        """
        Appends contents to a file. Some implementations may not have a method
        specifically for this, so a base method is provided to do so.

        :param path str: The path of the file.
        :param contents object: Either a unicode string, bytes-like object or iterable.
        :returns RemoteObject: The newly modified remote file.
        """
        path = self.absPath(path)
        with open(path, "ab") as fp:
            for part in ContentIterator(contents):
                fp.write(encode(part))
        return cast(RemoteObject, self.getPath(path))

    @UserContext
    def readFile(self, path: str, **kwargs: Any) -> Iterable[bytes]:
        """
        Reads the contents of a file.

        This should return an iterator to gradually the read the file.

        :param path str: The path of the file to read.
        :returns iterable: An iterator over the contents of the file.
        :raises `pibble.api.exceptions.NotFoundError`: When the file does not exist.
        """
        fp = None
        if is_binary_file(path):
            fp = open(path, "rb")
        else:
            fp = open(path, "r")  # type: ignore
        while True:
            data = fp.read(8192)  # type: ignore
            if not data:
                break
            yield data
        fp.close()  # type: ignore

    @UserContext
    def getPath(self, path: str, **kwargs: Any) -> RemoteObject:
        """
        List the contents of a directory or a file.

        :param path str: The path to list. Defaults to `self.cwd`.
        :returns RemoteObject: The file or directory.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        path = self.absPath(path)
        if not os.path.exists(path):
            raise NotFoundError("Path {0} does not exist.".format(path))

        lstat = os.lstat(path)
        if stat.S_ISDIR(lstat.st_mode):
            otype = RemoteObject.DIRECTORY
        elif stat.S_ISLNK(lstat.st_mode):
            otype = RemoteObject.LINK
        else:
            otype = RemoteObject.FILE

        if os.name == "nt":
            owner = None
            group = None
        else:
            owner = pwd.getpwuid(lstat.st_uid).pw_name  # type: ignore
            group = pwd.getpwuid(lstat.st_gid).pw_name  # type: ignore

        return RemoteObject(
            otype,
            path,
            reference=None if otype != RemoteObject.LINK else os.path.realpath(path),
            length=lstat.st_size,
            owner=owner,
            group=group,
            permission=o2r8d(stat.S_IMODE(lstat.st_mode)),
            accessTime=lstat.st_atime,
            modificationTime=lstat.st_mtime,
        )

    @UserContext
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
        if os.path.exists(dest) and not overwrite:
            return cast(RemoteObject, self.getPath(dest))
        if not os.path.exists(src):
            raise NotFoundError("Cannot find file {0}".format(src))
        os.rename(src, dest)
        return cast(RemoteObject, self.getPath(dest))

    @UserContext
    def deletePath(self, path: str, **kwargs: Any) -> bool:
        """
        Delete a path.

        :param path str: Either a file or directory path.
        :returns bool: True if successful.
        """
        node = self.getPath(path)
        if node.otype in [RemoteObject.FILE, RemoteObject.LINK]:
            os.remove(node.path)
        else:
            shutil.rmtree(node.path)
        return True

    @UserContext
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
        os.chmod(node.path, r8d2o(permission))
        return cast(RemoteObject, self.getPath(path))

    @UserContext
    def copyPath(
        self, src: str, dest: str, overwrite: Optional[bool] = False, **kwargs: Any
    ) -> RemoteObject:
        """
        Copies a path from src to dest.

        :param src str: The path to the source.
        :param dest str: The path to the destination, either a file or directory.
        :param overwrite bool: Whether or not to overwrite when calling writeFile.
        :returns RemoteObject: The newly copied file.
        :raises `pibble.api.exceptions.NotFoundError`: When src is not found.
        """
        dest = self.absPath(dest)
        if os.path.exists(dest) and not overwrite:
            return cast(RemoteObject, self.getPath(dest))

        node = self.getPath(src)
        if node.otype == RemoteObject.DIRECTORY:
            shutil.copytree(node.path, dest)
        else:
            shutil.copy(node.path, dest)
        return cast(RemoteObject, self.getPath(dest))

    def setPathOwner(
        self,
        path: str,
        owner: Optional[str] = None,
        group: Optional[str] = None,
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
        node = self.getPath(path)

        if os.name != "nt":
            if (owner is not None and node.owner != owner) or (
                group is not None and node.group != group
            ):
                if owner is not None:
                    uid = pwd.getpwnam(owner).pw_uid  # type: ignore
                else:
                    uid = -1
                if group is not None:
                    gid = pwd.getpwnam(group).pw_uid  # type: ignore
                else:
                    gid = -1
                os.chown(path, uid, gid)  # type: ignore
        return cast(RemoteObject, self.getPath(path))

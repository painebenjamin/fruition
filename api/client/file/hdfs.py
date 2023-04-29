# type: ignore
# TODO: Typecheck this module or remove it
import os
import datetime
import math

from typing import Optional, Iterable, Any

from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.client.file.base import (
    FileTransferAPIClientBase,
    RemoteObject,
    ContentIterator,
)
from pibble.api.exceptions import BadRequestError

__all__ = ["HDFSFileTransferAPIClient"]


class HDFSFileTransferAPIClient(FileTransferAPIClientBase):
    """
    This client abstracts the REST interface for WebHDFS.

    See http://hadoop.apache.org/docs/current/hadoop-project-dist/hadoop-hdfs/WebHDFS.html
    """

    TYPEMAP = {
        "DIRECTORY": RemoteObject.DIRECTORY,
        "FILE": RemoteObject.FILE,
        "LINK": RemoteObject.LINK,
    }

    def __init__(self):
        super(HDFSFileTransferAPIClient, self).__init__()
        self.client = WebServiceAPIClientBase()

    def on_configure(self) -> None:
        self.client.configure(
            client={
                "scheme": "http",
                "path": "/webhdfs/v1",
                "host": self.configuration["client.host"],
                "port": self.configuration["client.port"],
            }
        )

    def _make_query(
        self,
        method: str,
        path: str,
        op: str,
        user: str,
        data: Any = None,
        **kwargs: Any
    ) -> Any:
        parameters = kwargs
        parameters["op"] = op
        if user is not None:
            parameters["user.name"] = user
        return self.client.query(method, path, data=data, parameters=parameters)

    def _file_status_to_remote_object(
        self, path: str, file_status: dict
    ) -> RemoteObject:
        return RemoteObject(
            self.TYPEMAP[file_status["type"]],
            os.path.join(path, file_status["pathSuffix"])
            if file_status["pathSuffix"]
            else path,
            accessTime=datetime.datetime.fromtimestamp(
                file_status["accessTime"] // 1000
            ),
            modificationTime=datetime.datetime.fromtimestamp(
                file_status["modificationTime"] // 1000
            ),
            owner=file_status["owner"],
            group=file_status["group"],
            permission=int(file_status["permission"]),
            length=file_status["length"],
        )

    # Directory Operations

    def makeDirectory(
        self,
        path: str,
        user: Optional[str] = None,
        permission: Optional[int] = 644,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Makes a directory or directories.

        :param path str: The path to create. Note that this mimics the "-p" mkdir command, wherein missing path parts are automatically created.
        :param user str: The user name to execute as. Defaults to none.
        :param permission int: The octal permission definition.
        :returns RemoteObject: The new directory.
        """
        path = self.absPath(path)
        self._make_query("put", path, "MKDIRS", user, permission=permission).json()
        return self.getPath(path, user)

    def listDirectory(
        self, path: str = "/", user: Optional[str] = None, **kwargs: Any
    ) -> Iterable[RemoteObject]:
        """
        Lists the contents of a directory.

        :param path str: The path to look at. Defaults to root.
        :param user str: The user name to execute as. Defaults to none.
        :returns iterable: The remote objects in this path.
        """
        path = self.absPath(path)
        response = self._make_query("get", path, "LISTSTATUS", user).json()

        for sub in response["FileStatuses"]["FileStatus"]:
            yield self._file_status_to_remote_object(path, sub)

    # File Operations

    def writeFile(
        self,
        path: str,
        contents: Any,
        user: Optional[str] = None,
        overwrite: Optional[bool] = True,
        permission: Optional[int] = 644,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Writes contents to a file.

        :param path str: The file path to write to. Parent directories must exist.
        :param contents str: The contents of the file, as a string.
        :param user str: The user name to execute as. Defaults to none.
        :param overwrite bool: Whether to overwrite the file. If false, and the file exists, an exception will be raised.
        :param permission int: The octal permission definition.
        :returns boolean: Whether or not the file was written to.
        """
        path = self.absPath(path)
        iterator = ContentIterator(contents)
        if iterator.iterable:
            iterator = iter(iterator)
            start = next(iterator)
            assert (
                200
                <= self._make_query(
                    "put",
                    path,
                    "CREATE",
                    user,
                    permission=permission,
                    overwrite=overwrite,
                    data=start,
                ).status_code
                < 300
            )
            for part in iterator:
                self.appendFile(path, part, user)
        else:
            assert (
                200
                <= self._make_query(
                    "put",
                    path,
                    "CREATE",
                    user,
                    permission=permission,
                    overwrite=overwrite,
                    data=contents,
                ).status_code
                < 300
            )
        return self.getPath(path, user)

    def appendFile(
        self, path: str, contents: Any, user: Optional[str] = None, **kwargs: Any
    ) -> RemoteObject:
        """
        Writes contents to a file, appending after current contents.

        :param path str: The file path to write to.
        :param contents str: The contents of the file, as a string.
        :param user str: The user name to execute as. Defaults to none.
        :returns boolean: Whether or not the file was written to.
        """
        path = self.absPath(path)
        for chunk in ContentIterator(contents):
            assert (
                self._make_query("post", path, "APPEND", user, data=chunk).status_code
                == 200
            )

        return self.getPath(path, user)

    def readFile(
        self,
        path: str,
        user: Optional[str] = None,
        length: Optional[int] = 8192,
        **kwargs: Any
    ) -> Iterable[bytes]:
        """
        Reads the contents of a file iteratively.

        :param path str: The file path to read.
        :param user str: The user name to execute as. Defaults to none.
        :param offset int: The offset, in bytes, to read into the file. Defaults to 0.
        :param length int: The length, in bytes, to read. Defaults to None, None means to read until the end.
        :yields str: The string contents of the file.
        """

        path = self.absPath(path)
        remote_file = self.getPath(path, user=user)
        for i in range(math.ceil(float(remote_file.length) / float(length))):
            yield self._make_query(
                "get", path, "OPEN", user, offset=i * length, length=length
            ).text

    def checksumFile(
        self, path: str, user: Optional[str] = None, **kwargs: Any
    ) -> RemoteObject:
        """
        Gets a checksum on the file.

        :param path str: The source file, must exist.
        :param user str: The user name to execute as. Defaults to none.
        :returns dict: The dictionary object containing "FileChecksum," which includes the algorithm, bytes, and length.
        """
        path = self.absPath(path)
        return self._make_query("get", path, "GETFILECHECKSUM", user).json()

    # File or Directory Operations

    def getPath(
        self, path: str, user: Optional[str] = None, **kwargs: Any
    ) -> RemoteObject:
        """
        Gets a path, either directory, file or link.

        :param path str: The path to look at. Defaults to root.
        :param user str: The user name to execute as. Defaults to none.
        :returns RemoteObject: The remote object at this path.
        """
        path = self.absPath(path)
        return self._file_status_to_remote_object(
            path,
            self._make_query("get", path, "GETFILESTATUS", user).json()["FileStatus"],
        )

    def deletePath(
        self,
        path: str,
        user: Optional[str] = None,
        recursive: Optional[bool] = False,
        **kwargs: Any
    ) -> bool:
        """
        Deletes a file or directory.

        :param path str: The path to delete, either a directory or file.
        :param user str: The user name to execute as. Defaults to none.
        :param recurisve bool: Whether or not to recursively delete. If this is false, and the target is a non-empty directory, an exception will be raised.
        :returns boolean: Whether or not the file or directory was deleted.
        """
        path = self.absPath(path)
        return self._make_query(
            "delete", path, "DELETE", user, recursive=recursive
        ).json()["boolean"]

    def setPathPermission(
        self, path: str, permission: int, user: Optional[str] = None, **kwargs: Any
    ) -> RemoteObject:
        """
        Sets the permissions of a file or directory.

        :param path str: The file to change permissions on.
        :param permission int: The permission, a radix-8 integer.
        :param user str: The user name to execute as. Defaults to none.
        :return RemoteObject: If the request succeeded.
        """
        path = self.absPath(path)
        assert (
            self._make_query(
                "put", path, "SETPERMISSION", user, permission=permission
            ).status_code
            == 200
        )
        return self.getPath(path)

    def setPathOwner(
        self,
        path: str,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        user: Optional[str] = None,
        **kwargs: Any
    ) -> RemoteObject:
        """
        Sets the owner of a file or directory.

        One or both of group and owner should be passed.

        :param path str: The file to change owner on.
        :param owner str: The owner of the file.
        :param group str: The group of the file.
        :param user str: The user name to execute as. Defaults to none.
        :return RemoteObject: The path.
        """
        path = self.absPath(path)
        kwargs = {}
        if owner is not None:
            kwargs["owner"] = owner
        if group is not None:
            kwargs["group"] = group
        if not kwargs:
            raise BadRequestError("Must pass at least one of 'owner' or 'group'.")
        assert (
            self._make_query("put", path, "SETOWNER", user, **kwargs).status_code == 200
        )
        return self.getPath(path, user)

    def movePath(
        self, src: str, dest: str, user: Optional[str] = None, **kwargs: Any
    ) -> RemoteObject:
        """
        Moves a file from one location to another.

        :param src str: The source file, must exist.
        :param dest str: The destination file, must not exist.
        :param user str: The user name to execute as. Defaults to none.
        :returns RemoteObject: The destination.
        """
        src = self.absPath(src)
        dest = self.absPath(dest)
        self._make_query("put", src, "RENAME", user, destination=dest).json()
        return self.getPath(dest, user)

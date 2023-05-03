import os
import hashlib
import types
import io

from typing import Optional, Iterable, Any, Iterator, Union, cast

from pibble.api.client.base import APIClientBase
from pibble.api.exceptions import NotFoundError
from pibble.util.strings import encode
from pibble.util.log import logger


class ContentIterator:
    """
    A simple wrapper to make sure contents are properly iterable.
    """

    def __init__(self, contents: Any) -> None:
        if any(
            [
                isinstance(contents, cls)
                for cls in [io.TextIOBase, io.BufferedIOBase, io.RawIOBase, io.IOBase]
            ]
        ):
            self.iterable = True
            self.is_file = True
        elif isinstance(contents, types.GeneratorType):
            self.iterable = True
            self.is_file = False
        else:
            self.iterable = False
            self.is_file = False
        self.contents = contents

    def __iter__(self) -> Iterator[Union[bytes, str]]:
        if self.iterable:
            if self.is_file:
                while True:
                    data = self.contents.read(8192)
                    if not data:
                        break
                    yield data
            else:
                for chunk in self.contents:
                    yield chunk
        else:
            yield self.contents


class RemoteObject:
    DIRECTORY = 0
    FILE = 1
    LINK = 2

    def __init__(self, otype: int, path: str, **kwargs: Any):
        self.otype = otype
        self.path = path
        self.basename = os.path.basename(self.path)
        self.reference = kwargs.pop("reference", None)
        self.length = kwargs.pop("length", None)
        self.owner = kwargs.pop("owner", None)
        self.group = kwargs.pop("group", None)
        self.permission = kwargs.pop("permission", None)
        self.accessTime = kwargs.pop("accessTime", None)
        self.modificationTime = kwargs.pop("modificationTime", None)
        self.details = kwargs

    def __str__(self) -> str:
        return str(dict(vars(self)))


class FileTransferAPIClientBase(APIClientBase):
    """
    A base class for file transfer clients.
    """

    def __init__(self) -> None:
        logger.debug("Initializing File Transfer API Client Base.")
        super(FileTransferAPIClientBase, self).__init__()
        self.cwd = ""

    # Directory Operations

    def changeDirectory(self, path: str, **kwargs: Any) -> None:
        """
        Changes current working directory.

        :param path str: The path to change current directory to.
        """
        self.cwd = path

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
        raise NotImplementedError()

    def listDirectory(self, path: str = "", **kwargs: Any) -> Iterable[RemoteObject]:
        """
        Lists the contents of a directory.

        :param path str: A directory path.
        :returns iterable<RemoteObject>: The content of the directory.
        """
        raise NotImplementedError()

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
        raise NotImplementedError()

    def appendFile(
        self, path: str, contents: Iterator[bytes], **kwargs: Any
    ) -> RemoteObject:
        """
        Appends contents to a file. Some implementations may not have a method
        specifically for this, so a base method is provided to do so.

        :param path str: The path of the file.
        :param contents object: Either a unicode string, bytes-like object or iterable.
        :returns RemoteObject: The newly modified remote file.
        """
        path = self.absPath(path)

        existing: bytearray

        try:
            read_data = self.readEntireFile(path, **kwargs)
            if type(read_data) is str:
                existing = bytearray(encode(existing))
            else:
                existing = bytearray(cast(bytes, read_data))
        except NotFoundError:
            existing = bytearray()

        for part in ContentIterator(contents):
            existing += bytearray(encode(part))
        return self.writeFile(path, existing, True, **kwargs)

    def readFile(self, path: str, **kwargs: Any) -> Iterable[str]:
        """
        Reads the contents of a file.

        This should return an iterator to gradually the read the file.

        :param path str: The path of the file to read.
        :returns iterable: An iterator over the contents of the file.
        :raises `pibble.api.exceptions.NotFoundError`: When the file does not exist.
        """
        raise NotImplementedError()

    def readEntireFile(self, path: str, **kwargs: Any) -> str:
        """
        Reads the entire contents of a file.

        Some implementations will be able to do this without using the iterator function,
        but some will not. For that reason, a method is provided to just use the iterator.

        :param path str: The path of the file to read.
        :returns bytearray: The byte array of the entire file.
        :raises `pibble.api.exceptions.NotFoundError`: When path is not found.
        """
        path = self.absPath(path)

        iterator = self.readFile(path, **kwargs)
        if isinstance(iterator, list):
            start = iterator.pop(0)
        else:
            start = next(iterator)  # type: ignore

        if type(start) is str:
            fmt = lambda part: part
            buf = ""
        else:
            fmt = lambda part: bytearray(part)
            buf = bytearray()  # type: ignore

        buf += fmt(start)  # type: ignore

        for chunk in iterator:
            buf += fmt(chunk)  # type: ignore
        return buf

    def checksumFile(self, path: str, **kwargs: Any) -> str:
        """
        Checksums a file.

        Some implementations will be able to do this without needing to get the whole
        file first, but some will need to download the entire thing. For that reason
        there is a base method provided for checksumming after reading.

        :param path str: The path to the file.
        :returns str: The hex digest.
        :raises `pibble.api.exceptions.NotFoundError`: When path is not found.
        """
        path = self.absPath(path)

        checksum = hashlib.md5()
        for chunk in self.readFile(path, **kwargs):
            checksum.update(encode(chunk))
        return checksum.hexdigest()

    # File or Directory Operations

    def absPath(self, path: str) -> str:
        """
        Returns the absolute path version of a path. If it's already absolute,
        returns it, otherwise appends to `self.cwd`.

        :param path str: The path, relative or absolute.
        :return str: The absolute path.
        """
        if not os.path.isabs(path):
            return os.path.join(self.cwd, path)
        return path

    def movePath(
        self, src: str, dest: str, overwrite: Optional[bool] = False, **kwargs: Any
    ) -> RemoteObject:
        """
        Moves a file from src to dest. Some implementations cannot do this, so
        a method is provided to copy then remove.

        :param src str: The source path.
        :param dest str: The destination path.
        :returns RemoteObject: The newly moved file.
        :raises `pibble.api.exceptions.NotFoundError`: When src is not found.
        """
        src = self.absPath(src)
        dest = self.absPath(dest)

        self.copyPath(src, dest, overwrite, **kwargs)
        self.deletePath(src, **kwargs)
        return self.getPath(dest, **kwargs)

    def copyPath(
        self, src: str, dest: str, overwrite: Optional[bool] = True, **kwargs: Any
    ) -> RemoteObject:
        """
        Copies a path from src to dest. Some implementations will only have movePath and writeFile,
        so a base method is provided to copy it.

        :param src str: The path to the source.
        :param dest str: The path to the destination, either a file or directory.
        :param overwrite bool: Whether or not to overwrite when calling writeFile.
        :returns RemoteObject: The newly copied file.
        :raises `pibble.api.exceptions.NotFoundError`: When src is not found.
        """
        src = self.absPath(src)
        dest = self.absPath(dest)

        source = self.getPath(src, **kwargs)
        if source.otype == RemoteObject.DIRECTORY:
            for content in self.listDirectory(src, **kwargs):
                if content.otype == RemoteObject.DIRECTORY:
                    self.makeDirectory(
                        content.path,
                        permission=source.permission,
                        owner=source.owner,
                        group=source.group,
                        **kwargs
                    )
                return self.copyPath(
                    content.path,
                    os.path.join(dest, os.path.basename(content.path)),
                    overwrite=overwrite,
                    **kwargs
                )
        elif source.otype == RemoteObject.LINK:
            while source.otype == RemoteObject.LINK:
                source = self.getPath(source.reference, **kwargs)
            return self.copyPath(src, dest, overwrite, **kwargs)
        # File
        destination_path = dest
        try:
            destination = self.getPath(destination_path, **kwargs)
            if destination.otype == RemoteObject.DIRECTORY:
                destination_path = os.path.join(dest, os.path.basename(source.path))
        except NotFoundError:
            pass
        return self.writeFile(
            destination_path,
            self.readEntireFile(source.path),
            overwrite=overwrite,
            permission=source.permission,
            owner=source.owner,
            group=source.group,
            **kwargs
        )

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

    def getPath(self, path: str = "", **kwargs: Any) -> RemoteObject:
        """
        List the contents of a directory or a file.

        :param path str: The path to list. Defaults to `self.cwd`.
        :returns RemoteObject: The file or directory.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        raise NotImplementedError()

    def deletePath(self, path: str, **kwargs: Any) -> bool:
        """
        Delete a path.

        :param path str: Either a file or directory path.
        :returns bool: True if successful.
        """
        raise NotImplementedError()

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
        raise NotImplementedError()

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
        raise NotImplementedError()

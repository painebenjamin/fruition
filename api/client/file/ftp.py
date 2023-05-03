import ftplib
import os
import datetime

from typing import Iterator, Iterable, Optional, Any, Union, Mapping

from pibble.api.exceptions import (
    NotFoundError,
    BadRequestError,
)
from pibble.api.client.file.base import (
    FileTransferAPIClientBase,
    RemoteObject,
    ContentIterator,
)
from pibble.util.strings import encode, decode


class FTPClient(FileTransferAPIClientBase):
    ftp: Union[ftplib.FTP, ftplib.FTP_TLS]
    cwd: str

    def on_configure(self) -> None:
        host = self.configuration["client.host"]
        port = self.configuration.get("client.port", 21)

        user = self.configuration.get("client.ftp.username", "")
        password = self.configuration.get("client.ftp.password", "")
        account = self.configuration.get("client.ftp.account", "")
        secure = self.configuration.get("client.secure", False)

        if secure:
            keyfile = self.configuration.get("client.key", None)
            certfile = self.configuration.get("client.cert", None)

            self.ftp = ftplib.FTP_TLS(keyfile=keyfile, certfile=certfile)
        else:
            self.ftp = ftplib.FTP()

        self.ftp.connect(host, port)
        self.ftp.login(user, password, account)

        self.chunksize = self.configuration.get("client.ftp.chunksize", 8192)

    def close(self) -> None:
        """
        Closes the FTP connection.
        """
        try:
            self.ftp.quit()
        except:
            pass

    # Helpers

    def convertFacts(self, path: str, facts: Mapping) -> RemoteObject:
        """
        Converts an MLSx response to a RemoteObject.

        :param path str: The path of the remote file.
        :param facts dict: A dictionary of facts.
        :returns RemoteObject: The converted object.
        """
        if "unix.mode" in facts:
            _, _, permission = facts["unix.mode"].partition("o")
            permission = int(permission)
        else:
            permission = None

        if "modify" in facts:
            modifyTime = datetime.datetime.strptime(
                facts["modify"], "%Y%m%d%H%M%S"
            ).timestamp()
        else:
            modifyTime = None

        if "size" in facts:
            length = int(facts["size"])
        else:
            length = None

        return RemoteObject(
            RemoteObject.DIRECTORY if facts["type"] == "dir" else RemoteObject.FILE,
            path,
            length=length,
            permission=permission,
            modificationTime=modifyTime,
        )

    # Directory Operations

    def changeDirectory(self, path: str, **kwargs: Any) -> None:
        """
        Changes current working directory.

        :param path str: The path to change current directory to.
        """
        self.cwd = path
        self.ftp.cwd(path)

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
        :returns RemoteObject: The new directory.
        """
        path = self.absPath(path)
        try:
            return self.getPath(path)
        except NotFoundError:
            pass
        self.ftp.mkd(path)
        return self.getPath(path)

    def listDirectory(self, path: str = "/", **kwargs: Any) -> Iterable[RemoteObject]:
        """
        Lists the contents of a directory.

        :param path str: A directory path.
        :returns iterable<RemoteObject>: The content of the directory.
        """
        directory = self.getPath(path)
        for path, facts in self.ftp.mlsd(
            directory.path, facts=["type", "size", "perm", "modify", "unix.mode"]
        ):
            yield self.convertFacts(os.path.join(directory.path, path), facts)

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

        self.ftp.voidcmd("TYPE I")

        with self.ftp.transfercmd("STOR {0}".format(path)) as conn:
            for chunk in ContentIterator(contents):
                conn.sendall(encode(chunk))
            if self.configuration.get("client.secure", False) and callable(
                getattr(conn, "unwrap")
            ):
                conn.unwrap()  # type: ignore

        self.ftp.voidresp()
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

        try:
            existing = self.readEntireFile(path, **kwargs)
        except NotFoundError:
            existing = ""
        for chunk in ContentIterator(contents):
            existing += decode(chunk)
        return self.writeFile(path, existing, True, **kwargs)

    def readFile(self, path: str, **kwargs: Any) -> Iterator[str]:
        """
        Reads the contents of a file.

        :param path str: The path of the file to read.
        :returns iterable: An iterator over the contents of the file.
        :raises `pibble.api.exceptions.NotFoundError`: When the file does not exist.
        """

        binary = None
        self.ftp.voidcmd("TYPE I")

        with self.ftp.transfercmd("RETR {0}".format(self.absPath(path))) as conn:
            while True:
                data = conn.recv(self.chunksize)
                if not data:
                    break

                yield decode(data)
            if self.configuration.get("client.secure", False) and callable(
                getattr(conn, "unwrap")
            ):
                conn.unwrap()  # type: ignore

        self.ftp.voidresp()

    # File or Directory Operations

    def movePath(
        self, src: str, dest: str, overwrite: Optional[bool] = True, **kwargs: Any
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

        try:
            node = self.getPath(dest)
            if not overwrite:
                return node
        except NotFoundError:
            pass

        self.ftp.rename(src, dest)
        return self.getPath(dest)

    def getPath(self, path: str = "/", **kwargs: Any) -> RemoteObject:
        """
        List the contents of a directory or a file.

        :param path str: The path to list. Defaults to `self.cwd`.
        :returns RemoteObject: The file or directory.
        :raises `pibble.api.exceptions.NotFoundError`: When the path is not found.
        """
        path = self.absPath(path)
        facts = ["type", "size", "perm", "modify", "unix.mode"]

        self.ftp.sendcmd("OPTS MLST {0};".format(";".join(facts)))
        response = None

        try:
            response = self.ftp.sendcmd("MLST {0}".format(self.absPath(path)))
            response = response.splitlines()[1].strip()
            response_facts, response_path = response.split()

            response_fact_dict = dict(
                [
                    (part.split("=")[0].lower(), part.split("=")[1])
                    for part in response_facts.strip(" ;").split(";")
                ]
            )

            return self.convertFacts(response_path, response_fact_dict)
        except IndexError as ex:
            raise BadRequestError("Could not parse response: {0}".format(response))
        except Exception as ex:
            if type(ex) is ftplib.error_perm:
                code, _, data = str(ex).partition(" ")
                if int(code) == 550:
                    raise NotFoundError("Path {0} not found".format(self.absPath(path)))
            raise

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
            for subPath in self.listDirectory(node.path):
                self.deletePath(subPath.path)
            self.ftp.rmd(node.path)
        else:
            self.ftp.delete(node.path)
        return True

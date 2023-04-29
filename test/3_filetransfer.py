import stat
import os
import random
import string
import tempfile
import shutil

try:
    import pwd
except ImportError:
    pass

from pibble.api.client.file.ftp import FTPClient
from pibble.api.client.file.sftp import SFTPClient
from pibble.api.server.file.ftp import FTPServer
from pibble.api.server.file.sftp import SFTPServer

from pibble.api.client.file.local import LocalFileTransferAPIClient
# from pibble.api.client.file.hdfs import HDFSFileTransferAPIClient

from pibble.util.log import logger, DebugUnifiedLoggingContext
from pibble.util.helpers import ignore_exceptions, expect_exception, Assertion
from pibble.util.strings import decode
from pibble.api.exceptions import PermissionError


def pstat(f):
    try:
        s = os.lstat(f)
        print(
            "{0:o} {1}/{2} {3}".format(
                stat.S_IMODE(s.st_mode),
                pwd.getpwuid(s.st_uid).pw_name,
                pwd.getpwuid(s.st_gid).pw_name,
                os.path.abspath(f),
            )
        )
    except:
        print("{0} does not exist.".format(os.path.abspath(f)))


class ChunkData:
    def __init__(self, chunk_size, chunks):
        self.chunk_size = chunk_size
        self.chunks = chunks
        self.size = chunk_size * chunks
        self.content = "".join(
            random.choice(string.ascii_lowercase) for j in range(self.size)
        )

    def __iter__(self):
        for i in range(self.chunks):
            yield self.content[(i * self.chunk_size) : ((i + 1) * self.chunk_size)]


def main():
    with DebugUnifiedLoggingContext():

        tempdir = tempfile.mkdtemp()
        clients = [
            (
                FTPClient,
                {
                    "client": {
                        "host": "127.0.0.1",
                        "port": 9091,
                        "ftp": {"username": "goodydata-test", "password": "password"},
                    }
                },
                "/",
                False,
            ),
            (LocalFileTransferAPIClient, {}, tempdir, True),
            (
                SFTPClient,
                {
                    "client": {
                        "host": "127.0.0.1",
                        "port": 9092,
                        "sftp": {"username": "goodydata-test", "password": "password"},
                    }
                },
                "/home/goodydata-test",
                False,
            )
        ]

        ftp_server = FTPServer()
        sftp_server = SFTPServer()

        if os.name == "nt" or os.getuid() != 0:
            clients.pop(0)
            clients.pop(0)
            clients.pop(0)
            logger.critical(
                "Owner is not root, cannot use local file transfer, FTP API or SFTP API."
            )
        else:
            ftp_server.configure(server={"host": "0.0.0.0", "port": 9091})
            ftp_server.start()
            sftp_server.configure(
                authentication={"driver": "unix"},
                server={
                    "host": "0.0.0.0",
                    "port": 9092,
                    "sftp": {"root": {"directory": "/home"}},
                },
            )
            sftp_server.start()
            os.chown(tempdir, pwd.getpwnam("goodydata-user-1").pw_uid, -1)
            os.chmod(tempdir, 0o777)

        try:
            for cls, configuration, root, scoped in clients:
                api = cls()
                api.configure(**configuration)

                # Make /user/goodytest
                try:
                    ROOT_DIR = root
                    TEST_DIR = "goodytest"
                    FILE_1 = "test.txt"
                    FILE_2 = "test2.txt"
                    CONTENTS = "testcontents"
                    APPEND = "_appended"
                    MAIN_USER = "goodydata-user-1"
                    SECOND_USER = "goodydata-user-2"
                    THIRD_USER = "goodydata-user-3"

                    if cls is SFTPClient:
                        MAIN_USER = pwd.getpwnam(MAIN_USER).pw_uid
                        SECOND_USER = pwd.getpwnam(SECOND_USER).pw_uid
                        THIRD_USER = pwd.getpwnam(THIRD_USER).pw_uid

                    FILE_DIR = os.path.join(ROOT_DIR, TEST_DIR)
                    FILE_PATH_1 = os.path.join(FILE_DIR, FILE_1)
                    FILE_PATH_2 = os.path.join(FILE_DIR, FILE_2)

                    def assert_in_directory(filename, directory, user=MAIN_USER):
                        Assertion(Assertion.IN)(
                            filename,
                            [
                                ro.basename
                                for ro in api.listDirectory(directory, user=user)
                            ],
                        )

                    def assert_not_in_directory(filename, directory, user=MAIN_USER):
                        Assertion(Assertion.NIN)(
                            filename,
                            [
                                ro.basename
                                for ro in api.listDirectory(directory, user=user)
                            ],
                        )

                    logger.warning("Making directories.")
                    try:
                        api.makeDirectory(
                            FILE_DIR, user=MAIN_USER, permission=755, owner=MAIN_USER
                        )
                    except PermissionError as ex:
                        logger.error(
                            "Permission error occurred, will attempt to continue test: {0}".format(
                                ex
                            )
                        )
                        pass
                    assert_in_directory(TEST_DIR, ROOT_DIR)

                    # Write /user/goodytest/test.txt
                    logger.warning("Writing first file.")
                    try:
                        api.writeFile(
                            FILE_PATH_1,
                            CONTENTS,
                            user=MAIN_USER,
                            owner=MAIN_USER,
                            permission=755,
                        )
                    except PermissionError as ex:
                        logger.error(
                            "Permission error occurred, will attempt to continue test: {0}".format(
                                ex
                            )
                        )
                        pass
                    assert_in_directory(FILE_1, FILE_DIR)

                    # Read /user/goodytest/test.txt
                    logger.warning("Reading first file.")
                    Assertion(Assertion.EQ)(
                        CONTENTS,
                        decode(api.readEntireFile(FILE_PATH_1, user=MAIN_USER)),
                    )

                    # Move /user/goodytest/test.txt to /user/goodytest/test2.txt
                    logger.warning("Moving file.")
                    api.movePath(FILE_PATH_1, FILE_PATH_2, user=MAIN_USER)
                    assert_in_directory(FILE_2, FILE_DIR)
                    assert_not_in_directory(FILE_1, FILE_DIR)

                    # Read /user/goodytest/test2.txt
                    logger.warning("Reading moved file.")
                    Assertion(Assertion.EQ)(
                        CONTENTS,
                        decode(api.readEntireFile(FILE_PATH_2, user=MAIN_USER)),
                    )

                    # Append to /user/goodytest/test2.txt
                    logger.warning("Appending to file.")
                    api.appendFile(FILE_PATH_2, APPEND, user=MAIN_USER)
                    Assertion(Assertion.EQ)(
                        CONTENTS + APPEND,
                        decode(api.readEntireFile(FILE_PATH_2, user=MAIN_USER)),
                    )

                    if scoped:
                        logger.warning("Chaning permissions.")
                        # Change permissions of /user/goodytest/test2.txt
                        Assertion(Assertion.EQ)(
                            CONTENTS + APPEND,
                            decode(api.readEntireFile(FILE_PATH_2, user=SECOND_USER)),
                        )
                        Assertion(Assertion.EQ)(
                            CONTENTS + APPEND,
                            decode(api.readEntireFile(FILE_PATH_2, user=THIRD_USER)),
                        )

                        api.setPathPermission(FILE_PATH_2, 700, user=MAIN_USER)
                        Assertion(Assertion.EQ)(
                            700, api.getPath(FILE_PATH_2).permission
                        )
                        Assertion(Assertion.EQ)(
                            CONTENTS + APPEND,
                            decode(api.readEntireFile(FILE_PATH_2, user=MAIN_USER)),
                        )
                        expect_exception(PermissionError)(
                            api.readEntireFile, FILE_PATH_2, user=SECOND_USER
                        )
                        expect_exception(PermissionError)(
                            api.readEntireFile, FILE_PATH_2, user=THIRD_USER
                        )

                        logger.warning("Changing ownership.")
                        # Change owner of /user/goodytest/test2.txt
                        Assertion(Assertion.T)(
                            api.setPathOwner(
                                FILE_PATH_2, owner=SECOND_USER, user=MAIN_USER
                            )
                        )
                        Assertion(Assertion.EQ)(
                            CONTENTS + APPEND,
                            decode(api.readEntireFile(FILE_PATH_2, user=SECOND_USER)),
                        )
                        expect_exception(PermissionError)(
                            api.readEntireFile, FILE_PATH_2, user=THIRD_USER
                        )

                    # Delete /user/goodytest/test2.txt
                    logger.warning("Deleting file.")
                    Assertion(Assertion.T)(api.deletePath(FILE_PATH_2, user=MAIN_USER))
                    assert_not_in_directory(FILE_2, FILE_DIR)

                    # Test iterative reading / writing
                    logger.warning("Iteratively writing.")
                    data = ChunkData(8192, 16)
                    api.writeFile(FILE_PATH_1, iter(data), user=MAIN_USER)

                    Assertion(Assertion.EQ)(
                        data.content,
                        decode(api.readEntireFile(FILE_PATH_1, user=MAIN_USER)),
                    )

                    logger.warning("Iteratively reading.")
                    local_data = iter(data)
                    for remote_chunk in api.readFile(FILE_PATH_1, user=MAIN_USER):
                        Assertion(Assertion.EQ)(next(local_data), decode(remote_chunk))

                    expect_exception(StopIteration)(lambda: next(local_data))

                    # Test copying
                    logger.warning("Copying.")
                    api.copyPath(FILE_PATH_1, FILE_PATH_2, user=MAIN_USER)
                    Assertion(Assertion.EQ)(
                        decode(api.readEntireFile(FILE_PATH_1, user=MAIN_USER)),
                        decode(api.readEntireFile(FILE_PATH_2, user=MAIN_USER)),
                    )
                    logger.warning("Copied.")

                finally:
                    logger.warning("Removing test data.")
                    # Delete /user/goodytest
                    Assertion(Assertion.T)(
                        api.deletePath(FILE_DIR, user=MAIN_USER, recursive=True)
                    )
                    assert_not_in_directory(TEST_DIR, ROOT_DIR)

        finally:
            ignore_exceptions(ftp_server.stop)
            ignore_exceptions(sftp_server.stop)
            ignore_exceptions(shutil.rmtree, tempdir)


if __name__ == "__main__":
    main()

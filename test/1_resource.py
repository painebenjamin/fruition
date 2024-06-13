import io
import os
import string
import random
import hashlib
import sqlite3

from webob import Request, Response

from fruition.util.log import logger, DebugUnifiedLoggingContext
from fruition.util.strings import encode, RandomWordGenerator
from fruition.util.helpers import expect_exception, Assertion
from fruition.util.files import TempfileContext, SpreadsheetParser

from fruition.resources.retriever import Retriever, RetrieverIO

from fruition.api.server.webservice.base import WebServiceAPIHandlerRegistry
from fruition.api.server.webservice.base import WebServiceAPIServerBase
from fruition.api.middleware.webservice.authentication.basic import (
    BasicAuthenticationMiddleware,
)
from fruition.api.exceptions import AuthenticationError

from fruition.api.server.file.ftp import FTPServer
from fruition.api.server.file.sftp import SFTPServer

CHUNK_SIZE = 8192
CHUNKS = 10

FAKE_DATA = "".join(
    [random.choice(string.ascii_lowercase) for j in range(CHUNK_SIZE * CHUNKS)]
)


class FakeFileServingAPI(WebServiceAPIServerBase):
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.methods("GET")
    @handlers.path("/file")
    @handlers.download()
    def getFakeFile(self, request: Request, response: Response) -> io.BytesIO:
        return io.BytesIO(FAKE_DATA.encode("utf-8"))

    @handlers.methods("GET")
    @handlers.path("/single")
    def getSingle(self, request: Request, response: Response) -> str:
        return FAKE_DATA


class FakeFileServingBasicAuthenticationAPI(
    FakeFileServingAPI, BasicAuthenticationMiddleware
):
    pass


def main() -> None:
    with DebugUnifiedLoggingContext():
        with TempfileContext() as tempgen:

            # Test URL Retrieval - HTTP

            server = FakeFileServingAPI()
            server.configure(
                server={"host": "localhost", "port": 9090, "driver": "werkzeug"}
            )

            try:
                server.start()
                parts = []
                for part in Retriever.get("http://localhost:9090/file"):
                    parts.append(part)
                    Assertion(Assertion.EQ, "Part Size")(len(part), CHUNK_SIZE)
                Assertion(Assertion.EQ, "Total Part Size")(
                    CHUNK_SIZE * CHUNKS, sum([len(part) for part in parts])
                )
                single = Retriever.get("http://localhost:9090/single").all()
                Assertion(Assertion.EQ, "Total Size")(CHUNK_SIZE * CHUNKS, len(single))

            finally:
                server.stop()

            # Test URL Retrieval - Basic Auth

            username = "user"
            password = "pass"

            passwordfile = next(tempgen)

            conn = sqlite3.connect(passwordfile)
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE users (username TEXT, password TEXT, PRIMARY KEY(username))"
            )
            conn.commit()
            cursor.execute(
                "INSERT INTO users (username, password) VALUES ('{0}','{1}')".format(
                    username, hashlib.md5(encode(password)).hexdigest()
                )
            )
            conn.commit()
            conn.close()

            server = FakeFileServingBasicAuthenticationAPI()
            server.configure(
                **{
                    "server": {"host": "0.0.0.0", "port": 9090, "driver": "werkzeug"},
                    "authentication": {
                        "driver": "database",
                        "encryption": "md5",
                        "database": {
                            "type": "sqlite",
                            "connection": {"database": passwordfile},
                            "table": "users",
                        },
                    },
                }
            )

            try:
                server.start()

                Assertion(Assertion.EQ)(
                    CHUNK_SIZE * CHUNKS,
                    len(
                        Retriever.get(
                            "http://{0}:{1}@localhost:9090/single".format(
                                username, password
                            )
                        ).all()
                    ),
                )
                Assertion(Assertion.EQ)(
                    CHUNK_SIZE * CHUNKS,
                    len(
                        Retriever.get(
                            "http://localhost:9090/single",
                            {
                                "authentication": {
                                    "type": "basic",
                                    "basic": {
                                        "username": username,
                                        "password": password,
                                    },
                                }
                            },
                        ).all()
                    ),
                )
                expect_exception(AuthenticationError)(
                    lambda: Retriever.get("http://localhost:9090/single").all()
                )

            finally:
                server.stop()

            # Test FS retrieval

            testfile = next(tempgen)
            testcontents = "mycontents"
            open(testfile, "w").write(testcontents)
            Assertion(Assertion.EQ)(
                Retriever.get(f"file://{testfile}").all().decode("UTF-8"), testcontents
            )

            # Test (S)FTP Retrieval

            if os.name != "nt" and os.getuid() == 0:
                try:
                    test_user = "fruition-test"
                    test_user_password = "password"
                    test_file = "ftp-test.csv"

                    ftp_server = FTPServer()
                    sftp_server = SFTPServer()

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

                    # FTP
                    local_path = os.path.join("/home", test_user, test_file)
                    words = RandomWordGenerator()
                    row_tuples = [[next(words), next(words)] for i in range(100000)]
                    testcontents = "\n".join(
                        ["first,second"]
                        + ["{0},{1}".format(*row_tuple) for row_tuple in row_tuples]
                    )

                    open(local_path, "w").write(testcontents)

                    Assertion(Assertion.EQ)(
                        Retriever.get(
                            f"ftp://{test_user}:{test_user_password}@localhost:9091/{test_file}"
                        )
                        .all()
                        .decode("UTF-8"),
                        testcontents,
                    )

                    # Test IO
                    Assertion(Assertion.EQ)(
                        RetrieverIO(
                            f"ftp://{test_user}:{test_user_password}@localhost:9091/{test_file}"
                        )
                        .read()
                        .decode("UTF-8"),
                        testcontents,
                    )

                    # Test spreadsheet
                    for i, row in enumerate(
                        SpreadsheetParser(
                            RetrieverIO(
                                f"ftp://{test_user}:{test_user_password}@localhost:9091/{test_file}"
                            )
                        ).listIterator()
                    ):
                        Assertion(Assertion.EQ)(row, row_tuples[i])

                    # SFTP
                    for i, row in enumerate(
                        SpreadsheetParser(
                            RetrieverIO(
                                f"sftp://{test_user}:{test_user_password}@localhost:9092/home/{test_user}/{test_file}"
                            )
                        ).listIterator()
                    ):
                        Assertion(Assertion.EQ)(row, row_tuples[i])

                finally:
                    ftp_server.stop()
                    sftp_server.stop()
            else:
                logger.critical("User is not root, cannot run FTP/SFTP retrieval.")


if __name__ == "__main__":
    main()

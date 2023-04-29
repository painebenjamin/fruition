import tempfile
import shutil
import os

from pibble.util.log import DebugUnifiedLoggingContext

from pibble.api.client.googlerpc import GRPCAPIClient
from pibble.api.server.googlerpc import GRPCAPIServer

from pibble.api.helpers.googlerpc import GRPCCompiler

TEST_IMPORT = """
syntax = "proto3";

message NumberReply {
  int32 result = 1;
}
"""

TEST_SERVICE = """
syntax = "proto3";

import "testdir/import.proto";

service Calculator {
  rpc add(TwoNumberRequest) returns (NumberReply) {}
  rpc pow(TwoNumberRequest) returns (NumberReply) {}
}

message TwoNumberRequest {
  int32 num1 = 1;
  int32 num2 = 2;
}
"""


class TempProto(object):
    def __enter__(self):
        self.directory = tempfile.mkdtemp()
        return self

    def add(self, filename, content):
        filepath = os.path.join(self.directory, "{0}.proto".format(filename))
        dirs = filepath.split("/")[:-1]
        if dirs:
            dirname = "/".join(dirs)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        open(filepath, "w").write(content)
        return filepath

    def __exit__(self, *args):
        shutil.rmtree(self.directory)


class Handler(object):
    def add(self, num1, num2):
        return num1 + num2

    def pow(self, num1, num2):
        return num1**num2


CONFIGURATION = {
    "server": {"host": "0.0.0.0", "port": 50051},
    "client": {"host": "localhost", "port": 50051},
}


def main():
    with DebugUnifiedLoggingContext():
        with TempProto() as proto:
            main = proto.add("test", TEST_SERVICE)
            proto.add("testdir/import", TEST_IMPORT)
            try:
                with GRPCCompiler(proto.directory) as directory:

                    CONFIGURATION["grpc"] = {
                        "directory": directory,
                        "service": "Calculator",
                        "handler": Handler,
                    }

                    server = GRPCAPIServer()
                    client = GRPCAPIClient()

                    server.configure(**CONFIGURATION)
                    client.configure(**CONFIGURATION)

                    server.start()

                    assert client.add(2, 4) == 6
                    assert client.pow(2, 4) == 16

                    server.stop(False)
            except IOError as ex:
                logger.error(ex)
                logger.info("Abandoning remainder of test.")
                return


if __name__ == "__main__":
    main()

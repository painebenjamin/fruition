# type: ignore
import tempfile
import shutil
import os
import grpc

from fruition.util.log import DebugUnifiedLoggingContext
from fruition.api.helpers.googlerpc import GRPCCompiler, GRPCImporter

from concurrent.futures import ThreadPoolExecutor

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


class TempProto:
    """
    A quickly assembled context manager to write the proto, and delete it
    when it's done.
    """

    def add(self, filename: str, content: str) -> str:
        filepath = os.path.join(self.directory, "{0}.proto".format(filename))
        dirs = filepath.split("/")[:-1]
        if dirs:
            dirname = "/".join(dirs)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        open(filepath, "w").write(content)
        return filepath

    def __enter__(self):
        self.directory = tempfile.mkdtemp()
        return self

    def __exit__(self, *args):
        shutil.rmtree(self.directory)


def main() -> None:
    with DebugUnifiedLoggingContext():
        with TempProto() as proto:
            main = proto.add("test", TEST_SERVICE)
            proto.add("testdir/import", TEST_IMPORT)
            with GRPCCompiler(proto.directory) as outdir:
                with GRPCImporter(outdir) as explorer:
                    assert hasattr(explorer, "test_pb2_grpc")
                    assert hasattr(explorer, "test_pb2")
                    assert hasattr(explorer.test_pb2_grpc.module(), "CalculatorStub")

                    class Servicer(explorer.test_pb2_grpc.module().CalculatorServicer):
                        def add(self, request, context):
                            return explorer.testdir.import_pb2.module().NumberReply(
                                result=request.num1 + request.num2
                            )

                        def pow(self, request, context):
                            return explorer.testdir.import_pb2.module().NumberReply(
                                result=request.num1**request.num2
                            )

                    server = grpc.server(ThreadPoolExecutor(max_workers=10))
                    explorer.test_pb2_grpc.module().add_CalculatorServicer_to_server(
                        Servicer(), server
                    )
                    server.add_insecure_port("[::]:50051")
                    server.start()

                    channel = grpc.insecure_channel("localhost:50051")
                    stub = explorer.test_pb2_grpc.module().CalculatorStub(channel)

                    assert (
                        stub.add(
                            explorer.test_pb2.module().TwoNumberRequest(num1=2, num2=4)
                        ).result
                        == 6
                    )
                    assert (
                        stub.pow(
                            explorer.test_pb2.module().TwoNumberRequest(num1=2, num2=4)
                        ).result
                        == 16
                    )

                    server.stop(False)


if __name__ == "__main__":
    main()

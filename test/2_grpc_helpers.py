from __future__ import annotations

import tempfile
import shutil
import os
import grpc

from concurrent.futures import ThreadPoolExecutor
from grpc import ServicerContext

from typing import Any, NamedTuple

from fruition.util.log import DebugUnifiedLoggingContext, logger
from fruition.util.helpers import find_executable
from fruition.api.helpers.googlerpc import (
    GRPCCompiler,
    GRPCImporter,
    GRPCServiceExplorer,
)

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
    def __enter__(self) -> TempProto:
        self.directory = tempfile.mkdtemp()
        return self

    def add(self, filename: str, content: str) -> str:
        filepath = os.path.join(self.directory, "{0}.proto".format(filename))
        dirs = filepath.split("/")[:-1]
        if dirs:
            dirname = "/".join(dirs)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
        open(filepath, "w").write(content)
        return filepath

    def __exit__(self, *args: Any) -> None:
        shutil.rmtree(self.directory)


class TwoNumberRequest(NamedTuple):
    num1: int
    num2: int


class NumberReply(NamedTuple):
    result: int


def main() -> None:
    with DebugUnifiedLoggingContext():
        with TempProto() as proto:
            main = proto.add("test", TEST_SERVICE)
            proto.add("testdir/import", TEST_IMPORT)
            try:
                with GRPCCompiler(proto.directory) as directory:
                    with GRPCImporter(directory) as module:
                        explorer = GRPCServiceExplorer(module)
                        service = explorer.find("Calculator")
            except IOError as ex:
                logger.error(ex)
                logger.info("Abandoning remainder of test.")
                return

        # MyPy is not happy if you just extend the service.service class,
        # if you want to keep MyPy happy, we programmatically define the
        # type after.
        class CalculatorServicer:
            def add(
                self, request: TwoNumberRequest, context: ServicerContext
            ) -> NumberReply:
                return service.messages.NumberReply(result=request.num1 + request.num2)

            def pow(
                self, request: TwoNumberRequest, context: ServicerContext
            ) -> NumberReply:
                return service.messages.NumberReply(result=request.num1**request.num2)

        servicer = type(
            "CalculatorServicer", (CalculatorServicer, service.servicer), {}
        )()
        server = grpc.server(ThreadPoolExecutor(max_workers=10))
        service.assigner(servicer, server)
        server.add_insecure_port("[::]:50051")
        server.start()

        channel = grpc.insecure_channel("localhost:50051")
        client = service.stub(channel)

        assert client.add(service.messages.TwoNumberRequest(num1=2, num2=4)).result == 6
        assert (
            client.pow(service.messages.TwoNumberRequest(num1=2, num2=4)).result == 16
        )

        server.stop(False)


if __name__ == "__main__":
    main()

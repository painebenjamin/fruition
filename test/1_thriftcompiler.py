import tempfile
import os

from pibble.util.helpers import find_executable
from pibble.util.log import DebugUnifiedLoggingContext
from pibble.api.helpers.apachethrift import ApacheThriftCompiler

TEST_SERVICE = """
namespace py GoodyThriftTest

service Calculator {
  i32 add(1:i32 num1, 2:i32 num2)
}
"""


def main() -> None:
    try:
        find_executable("thrift")
    except ImportError:
        return
    with DebugUnifiedLoggingContext():
        _, tmp = tempfile.mkstemp()
        try:
            open(tmp, "w").write(TEST_SERVICE)
            compiler = ApacheThriftCompiler(tmp)
            GoodyThriftTest = compiler.compile()
            assert hasattr(GoodyThriftTest, "Calculator")
            assert hasattr(GoodyThriftTest.Calculator, "Client")

            open(tmp, "w").write("\n".join(TEST_SERVICE.splitlines()[2:]))
            compiler2 = ApacheThriftCompiler(tmp)
            unnamed_module = compiler2.compile()
            assert hasattr(unnamed_module, "Calculator")
            assert hasattr(unnamed_module.Calculator, "Client")
        finally:
            os.remove(tmp)


if __name__ == "__main__":
    main()

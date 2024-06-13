import tempfile
import os

from fruition.util.helpers import find_executable
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.api.helpers.apachethrift import ApacheThriftCompiler

TEST_SERVICE = """
namespace py FruitionThriftTest

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
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        try:
            open(tmp, "w").write(TEST_SERVICE)
            compiler = ApacheThriftCompiler(tmp)
            FruitionThriftTest = compiler.compile()
            assert hasattr(FruitionThriftTest, "Calculator")
            assert hasattr(FruitionThriftTest.Calculator, "Client")

            open(tmp, "w").write("\n".join(TEST_SERVICE.splitlines()[2:]))
            compiler2 = ApacheThriftCompiler(tmp)
            unnamed_module = compiler2.compile()
            assert hasattr(unnamed_module, "Calculator")
            assert hasattr(unnamed_module.Calculator, "Client")
        finally:
            os.remove(tmp)


if __name__ == "__main__":
    main()

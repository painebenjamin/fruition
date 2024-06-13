from fruition.util.helpers import Assertion
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.files import TempfileContext, load_yaml


def main() -> None:
    with DebugUnifiedLoggingContext():
        with TempfileContext() as tempfiles:
            path1 = next(tempfiles)
            path2 = next(tempfiles)
            open(path1, "w").write("{{value: !include {0}}}".format(path2))
            open(path2, "w").write("{nested: 'test'}")

            Assertion(Assertion.EQ)(load_yaml(path1), {"value": {"nested": "test"}})


if __name__ == "__main__":
    main()

"""
A collection of helpers methods and classes that don't otherwise belong.
"""
import os
import sys
import json
import zlib
import math
import shlex
import signal
import difflib
import termcolor
import subprocess

try:
    import pwd
except ImportError:
    pass

from logging import DEBUG
from distutils import spawn

from typing import (
    Type,
    Callable,
    Optional,
    Iterable,
    Iterator,
    Any,
    Tuple,
    Union,
    Dict,
    List,
)
from types import FunctionType

from pandas import DataFrame
from io import StringIO

from numpy import ndarray
from difflib import unified_diff
from time import sleep
from datetime import date, datetime

from pibble.util.log import logger
from pibble.util.strings import truncate, decode, Serializer

__all__ = [
    "url_join",
    "find_executable",
    "qualify",
    "resolve",
    "expect_exception",
    "ignore_exceptions",
    "is_binary",
    "is_binary_file",
    "openpyxl_dataframe",
    "Assertion",
    "CompressedIterator",
    "DecompressedIterator",
    "AttributeDictionary",
    "Pause",
    "OutputCatcher",
    "Printer",
]


def no_op(*parts: Any, **kwargs: Any) -> None:
    """
    Does nothing.
    """


def url_join(*parts: str) -> str:
    """
    Joins parts of a URL together.

    Unlike `urllib.parse.urljoin`, this doesn't overwrite paths if they start with "/".

    >>> from pibble.util.helpers import url_join
    >>> baseurl = "http://localhost:8080"
    >>> url_join(baseurl, "api")
    'http://localhost:8080/api'
    >>> url_join(baseurl, "api", "v2")
    'http://localhost:8080/api/v2'
    >>> url_join(baseurl, "api", None, "", 1, "")
    'http://localhost:8080/api/1'

    :param parts tuple: Any number of parts to join together. Strips slashes, and decodes to unicode. Removes empty and NoneType parts.
    :returns str: The joined URL.
    """
    return "/".join(
        [
            str(part).strip("/")
            for part in parts
            if part is not None and str(part).strip("/")
        ]
    )


def find_executable(binary_name: str, raise_missing: bool = True) -> Optional[str]:
    """
    Finds a binary on PATH. Raises an exception if it does not exist.
    """
    executable = spawn.find_executable(binary_name)
    if not executable:
        if raise_missing:
            raise ImportError("Could not find {0} on PATH.".format(binary_name))
        return None
    return executable


def qualify(obj: Any) -> str:
    """
    Reports the fully qualified name of objects. Avoids using __builtin__.

    Will NOT instantiate types.

    >>> from pibble.util.helpers import qualify
    >>> qualify(qualify)
    'pibble.util.helpers.qualify'
    >>> from webob import Request
    >>> qualify(Request) # Request is passed through from webob.request to webob
    'webob.request.Request'
    >>> qualify(1)
    'int'
    >>> qualify('test')
    'str'

    :param obj object: The object to qualify.
    :returns str: The string name of the object.
    """
    if obj.__class__ in [FunctionType, type]:
        return f"{obj.__module__}.{obj.__name__}"
    module = obj.__module__ if hasattr(obj, "__module__") else obj.__class__.__module__
    if module is None or module == str.__class__.__module__:
        return str(obj.__class__.__name__)
    return f"{module}.{obj.__class__.__name__}"


def resolve(qualified_name: Any, local: dict = {}) -> Any:
    """
    Attempts to resolve a name through imports.

    Safer than calling eval().

    >>> from pibble.util.helpers import resolve, expect_exception
    >>> resolve("requests.models.Request")
    <class 'requests.models.Request'>
    >>> expect_exception(ImportError)(lambda: resolve("MyClass"))

    :param qualified_name str: The fully-qualified name, or globally accessible name.
    :param local dict: A dictionary of local names, if name is unqualified.
    """
    if type(qualified_name) is type or type(qualified_name).__name__ == "module":
        return qualified_name
    try:
        if qualified_name.count(".") > 0:
            qualified_split = qualified_name.split(".")

            module_name = ".".join(qualified_split[:-1])
            member_name = qualified_split[-1]
            try:
                if module_name in sys.modules:
                    return getattr(sys.modules[module_name], member_name)
            except:
                pass

            try:
                module = __import__(qualified_name, locals(), globals())
            except ImportError:
                try:
                    module = __import__(module_name, locals(), globals())
                except ImportError as ex:
                    checked_paths = "; ".join(sys.path)
                    cwd = os.getcwd()
                    raise ImportError(
                        f"Cannot import module {module_name}. Tried {checked_paths} from {cwd}. {ex}"
                    )
            active = module
            for qualified_part in qualified_split[1:]:
                active = getattr(active, qualified_part)
            return active
        else:
            return local.get(
                qualified_name, getattr(sys.modules[__name__], qualified_name)
            )
    except (KeyError, AttributeError) as ex:
        raise ImportError(
            "Cannot resolve name '{0}': {1}({2})".format(
                qualified_name, type(ex).__name__, str(ex)
            )
        )


def expect_exception(exception_class: Type[Exception]) -> Callable[[Any], None]:
    """
    A small callable that lets you call a function
    with an exception expected in a single line.

    Useful for debugging.

    >>> from pibble.util.helpers import expect_exception
    >>> my_dict = {"foo": "bar"}
    >>> expect_exception(KeyError)(lambda: my_dict["baz"])

    :param exception_class type: The type of exception to expect.
    :returns callable: A function to call which the user expects will raise an exception.
    """

    def _call(fn: Callable, *args: Any, **kwargs: Any) -> None:
        """
        Calls the function, and catches the exception.

        No exception being raised is considered an exception.
        """
        try:
            fn(*args, **kwargs)
            raise AssertionError(
                "Expected exception type {0}, got none instead.".format(
                    exception_class.__name__
                )
            )
        except Exception as ex:
            if not isinstance(ex, exception_class):
                if type(ex) is AssertionError:
                    raise ex
                raise AssertionError(
                    "Expected exception type {0}, got {1} instead.".format(
                        exception_class.__name__, type(ex).__name__
                    )
                )

    return _call


def ignore_exceptions(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """
    A simple helper that ignores any exceptions that occur from a callable.

    >>> from pibble.util.helpers import ignore_exceptions
    >>> my_dict = {"a": 1}
    >>> ignore_exceptions(lambda: my_dict["a"])
    1
    >>> ignore_exceptions(lambda: my_dict["b"]) # Expect Nothing
    """
    try:
        return func(*args, **kwargs)
    except:
        return


def is_binary(value: Any) -> bool:
    """
    Guesses whether a value represents a binary string or a decodable string.

    This can give both false positives and false negatives.

    >>> from pibble.util.helpers import is_binary
    >>> is_binary(bytearray([0x20, 0x10]))
    True
    >>> is_binary("string".encode("UTF-8"))
    False

    :param value bytearray: The bytearray to check.
    """
    return bool(
        value.translate(
            None,
            bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}),
        )
    )


def is_binary_file(path: str, chunk_size: Optional[int] = 1024) -> bool:
    """
    Similar to `is_binary`, but instead reads a file.

    >>> from pibble.util.helpers import is_binary_file
    >>> import tempfile
    >>> import os
    >>> fd, tmp = tempfile.mkstemp()
    >>> os.close(fd)
    >>> s = open(tmp, "w").write("abc")
    >>> is_binary_file(tmp)
    False
    >>> s = open(tmp, "wb").write(bytearray([0x20, 0x10]))
    >>> is_binary_file(tmp)
    True

    :param path str: The path to check.
    :param chunk_size int: The chunk of data to read. Defaults to 1 KiB.
    """
    with open(path, "rb") as fp:
        return is_binary(fp.read(chunk_size))


def openpyxl_dataframe(
    path: str, header: int = 0, chunksize: int = 1, **kwargs: Any
) -> Iterable[DataFrame]:
    """
    Creates a pandas dataframe of an excel file, using
    openpyxl. This is moderately more efficient than
    pandas' native pd.read_excel using openpyxl.

    read_only is omitted, since worksheet dimensions
    aren't always accurate.
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError("Couldn't import openpyxl. Run `pip install pibble[excel]` to get it.")
    wb = load_workbook(path)
    ws = wb.active
    data = ws.values
    for i in range(header + 1):
        kwargs["columns"] = next(data)
    df = DataFrame(data, **kwargs)
    if chunksize <= 1:
        yield df

    def iterator() -> Iterable[DataFrame]:
        """
        Iterates over the DataFrame.
        """
        for i in range(math.ceil(df.shape[0] / chunksize)):
            yield df[i * chunksize : (i + 1) * chunksize]

    return iterator()


class Assertion:
    """
    A class that holds assertion types, and allows for AssertionErrors to indicate actual and expected values.

    >>> from pibble.util.helpers import Assertion, expect_exception
    >>> Assertion(Assertion.EQ)(1, 1)
    >>> Assertion(Assertion.IN)(1, [1])
    >>> expect_exception(AssertionError)(lambda: Assertion(Assertion.IN)(1, [1]))
    >>> Assertion(Assertion.EQ)([1], [1])
    >>> Assertion(Assertion.NEQ)([1], [2])
    """

    EQ = 1
    NEQ = 2
    GT = 3
    GTE = 4
    LT = 5
    LTE = 6
    IS = 7
    ISN = 8
    IN = 9
    NIN = 10
    T = 11
    F = 12

    LIST_LIKES = [list, tuple, ndarray]

    def __init__(
        self,
        assertion_type: int,
        name: Optional[str] = None,
        diff_split_on: Optional[str] = None,
    ) -> None:
        """
        :param type int: The assertion type. Use global variables for ease of use.
        :param name str: Optional string. Passed through in the exception, for debugging.
        :param diff_split_on str: Optional. When using diffs, will split the diff's on this character.
        """
        self.name = name
        self.assertion_type = assertion_type
        self.diff_split_on = diff_split_on

    def _is_equal(self, left: Any, right: Any) -> bool:
        """
        Checks if two variables are the same.

        This is more robust than a simple assertion, and allows for list-likes and dict-likes.
        """
        if isinstance(left, dict) and isinstance(right, dict):
            if set(left.keys()) != set(right.keys()):
                return False
            for key in left:
                if not self._is_equal(left[key], right[key]):
                    return False
            return True
        elif type(left) in Assertion.LIST_LIKES and type(left) in Assertion.LIST_LIKES:
            if len(left) != len(right):
                return False
            for i in range(len(left)):
                if not self._is_equal(left[i], right[i]):
                    return False
            return True
        return type(left) is type(right) and left == right

    def call(self, left: Any, right: Any = None) -> bool:
        """
        Calls the assertion, but doesn't raise - instead returns True or False.
        """
        try:
            self(left, right)
            return True
        except:
            return False

    def __call__(self, left: Any, right: Any = None) -> None:
        """
        Calls the assertion.

        :raises AssertionError: When the assertion fails.
        """
        try:
            error_msg = None
            if self.assertion_type == Assertion.T:
                opcode = "== True"
                assert left
            elif self.assertion_type == Assertion.F:
                opcode = "== False"
                assert not left
            elif self.assertion_type == Assertion.EQ:
                opcode = "=="
                assert self._is_equal(left, right) == True
            elif self.assertion_type == Assertion.NEQ:
                opcode = "!="
                assert not self._is_equal(left, right)
            elif self.assertion_type == Assertion.GT:
                opcode = ">"
                assert left > right
            elif self.assertion_type == Assertion.GTE:
                opcode = ">="
                assert left >= right
            elif self.assertion_type == Assertion.LT:
                opcode = "<"
                assert left < right
            elif self.assertion_type == Assertion.LTE:
                opcode = "<="
                assert left <= right
            elif self.assertion_type == Assertion.IS:
                opcode = "is"
                assert left is right
            elif self.assertion_type == Assertion.ISN:
                opcode = "is not"
                assert left is not right
            elif self.assertion_type == Assertion.IN and right is not None:
                opcode = "in"
                assert left in right
            elif self.assertion_type == Assertion.NIN and right is not None:
                opcode = "not in"
                assert left not in right
            else:
                raise KeyError(
                    "Unknown assertion operation code '{0}'.".format(
                        self.assertion_type
                    )
                )
        except AssertionError:
            if self.assertion_type in [Assertion.T, Assertion.F]:
                raise AssertionError(
                    "{0}The following assertion failed: {1} ({2}) {3}".format(
                        "{0}: ".format(self.name) if self.name else "",
                        truncate(left),
                        type(left).__name__,
                        opcode,
                    )
                )
            if self.assertion_type == Assertion.EQ and logger.isEnabledFor(DEBUG):
                if self.diff_split_on is None:
                    left_compare = str(left).splitlines()
                    right_compare = str(right).splitlines()
                else:
                    left_compare = str(left).split(self.diff_split_on)
                    right_compare = str(right).split(self.diff_split_on)

                diff = difflib.unified_diff(left_compare, right_compare)
                for differ in diff:
                    logger.debug(differ)
            raise AssertionError(
                "{0}The following assertion failed: {1} ({2}) {3} {4} ({5})".format(
                    "{0}: ".format(self.name) if self.name else "",
                    truncate(left),
                    type(left).__name__,
                    opcode,
                    truncate(right) if right is not None else None,
                    type(right).__name__,
                )
            )


class CompressedIterator:
    """
    A helper that iterates over anything and compresses it using zlib. The size of each
    yielded chunk is variable, and you cannot know ahead of time how many chunks will be
    yielded.
    """

    def __init__(self, iterable: Iterator[bytes]) -> None:
        """
        :param iterable Iterable: The content to compress.
        """
        self.iterable = iterable
        self.compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)

    def __iter__(self) -> Iterator[bytes]:
        """
        Allows for iterating over the iterator itself.
        """
        while True:
            try:
                yield next(self)
            except StopIteration:
                return

    def __next__(self) -> bytes:
        """
        Allows for calling next() on the iterator.
        """
        try:
            chunk = next(self.iterable)
            compressed = self.compressor.compress(chunk)
            if compressed:
                return compressed
            else:
                return self.__next__()
        except StopIteration:
            try:
                return self.compressor.flush()
            except:
                raise StopIteration()


class DecompressedIterator:
    """
    The opposite of CompressedIterator, this is a helper for decompressing
    using zlib.
    """

    def __init__(self, iterable: Iterator[bytes]) -> None:
        """
        :param iterable Iterable: The content to compress.
        """
        self.iterable = iterable
        self.decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)

    def __iter__(self) -> Iterator[bytes]:
        """
        Allows for iterating over the iterator itself.
        """
        while True:
            try:
                yield next(self)
            except StopIteration:
                return

    def __next__(self) -> bytes:
        """
        Allows for calling next() on the iterator.
        """
        try:
            chunk = next(self.iterable)
            decompressed = self.decompressor.decompress(chunk)
            if decompressed:
                return decompressed
            else:
                return self.__next__()
        except StopIteration:
            try:
                flushed = self.decompressor.flush()
                if flushed:
                    return flushed
                else:
                    raise StopIteration()
            except:
                raise StopIteration()


class AttributeDictionary:
    """
    A small class to hold dictionary key/values as attribute.

    >>> from pibble.util.helpers import AttributeDictionary
    >>> attrDict = AttributeDictionary(foo = "bar")
    >>> attrDict.foo
    'bar'
    >>> attrDict['foo']
    'bar'
    """

    def __init__(self, **kwargs: Any) -> None:
        """
        :param kwargs Any: The dictionary attributes.
        """
        for key in kwargs:
            setattr(self, key, kwargs[key])
        self._keys = kwargs.keys()

    def __getitem__(self, key: str) -> Any:
        """
        Allows for using square-bracket syntax if desired.
        """
        return getattr(self, key)

    def keys(self) -> Iterable[str]:
        """
        Iterates over the keys of the dictionary.
        """
        for key in self._keys:
            yield key

    def values(self) -> Iterable[Any]:
        """
        An iterator over the values instead of the keys.
        """
        for key in self.keys():
            yield getattr(self, key)

    def __iter__(self) -> Iterable[str]:
        """
        Similar to the default behavior for dicts, an iterator goes over keys.
        """
        for key in self.keys():
            yield key


class Pause:
    """
    A small class to allow sleeping until a certain time.

    >>> from pibble.util.helpers import Pause
    >>> from datetime import datetime, timedelta
    >>> test_maximum_delta = 5e-2
    >>> start = datetime.now()
    >>> Pause.seconds(1)
    >>> assert abs((datetime.now() - start).total_seconds()-1.00) < test_maximum_delta
    >>> start = datetime.now(); Pause.milliseconds(500)
    >>> assert abs((datetime.now() - start).total_seconds()-0.50) < test_maximum_delta
    >>> start = datetime.now(); target = start + timedelta(milliseconds = 500); Pause.until(target)
    >>> assert abs((datetime.now() - start).total_seconds()-0.50) < test_maximum_delta
    """

    @staticmethod
    def seconds(n: Union[int, float]) -> None:
        """
        Sleeps for <n> seconds.

        :param n int | float: The number of seconds to wait for.
        """
        sleep(n)

    @staticmethod
    def milliseconds(n: Union[int, float]) -> None:
        """
        Sleeps for <n> milliseconds.

        :param n int | float: The number of milliseconds to wait for.
        """
        sleep(n / 1000)

    @staticmethod
    def until(dt: Union[date, datetime]) -> None:
        """
        Allows for sleeping until a certain datetime.

        :param dt date | datetime: The date or time to wait until/
        """
        while True:
            diff = (dt - datetime.now()).total_seconds()
            if diff < 0:
                return
            sleep(diff / 2)
            if diff <= 0.1:
                return


class OutputCatcher:
    """
    A context manager that allows easy capturing of stdout.

    >>> from pibble.util.helpers import OutputCatcher
    >>> catcher = OutputCatcher()
    >>> catcher.__enter__()
    >>> print("stdout")
    >>> catcher.__exit__()
    >>> catcher.output()[0].strip()
    'stdout'
    """

    def __init__(self) -> None:
        """
        Initialize IOs for stdout and stderr.
        """
        self.stdout = StringIO()
        self.stderr = StringIO()

    def __enter__(self) -> None:
        """
        When entering context, steal system streams.
        """
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = self.stdout
        sys.stderr = self.stderr

    def __exit__(self, *args: Any) -> None:
        """
        When exiting context, return system streams.
        """
        if hasattr(self, "_stdout"):
            sys.stdout = self._stdout
        if hasattr(self, "_stderr"):
            sys.stderr = self._stderr

    def clean(self) -> None:
        """
        Cleans memory by replacing StringIO.
        This is faster than trunc/seek
        """
        self.stdout = StringIO()
        self.stderr = StringIO()

    def output(self) -> Tuple[str, str]:
        """
        Returns the contents of stdout and stderr.
        """
        return (self.stdout.getvalue(), self.stderr.getvalue())


class ProcessRunner:
    """
    Wrapper around subprocess.Popen for ease-of-use.
    """

    process: Optional[subprocess.Popen]

    def __init__(self, executable: str):
        if not executable.startswith("/"):
            executable = str(find_executable(executable))
        self.executable = executable
        self.process = None

    def call(
        self,
        *args: str,
        shell: bool = False,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ) -> subprocess.Popen:
        """
        The underlying 'call' method just gets the Subprocess.

        >>> import subprocess
        >>> from pibble.util.helpers import ProcessRunner
        >>> p = ProcessRunner("echo").call("hello")
        >>> type(p)
        <class 'subprocess.Popen'>
        >>> p.communicate()
        (b'hello\\n', b'')
        >>> p.returncode
        0
        """
        subprocess_kwargs: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if user is not None and os.name != "nt":
            # Set the env for the subprocess
            user_pw = pwd.getpwnam(user)  # type: ignore
            env = os.environ.copy()
            env.update(
                {
                    "HOME": user_pw.pw_dir,
                    "LOGNAME": user,
                    "USER": user,
                }
            )
            if cwd:
                env.update({"PWD": cwd})
            else:
                env.update({"PWD": os.getcwd()})

            subprocess_kwargs["env"] = env

            # Generate a demote function as pre-executable
            def demote(user_id: int, group_id: int) -> Callable[[], None]:
                def wrapper() -> None:
                    os.setsid()
                    os.setgid(group_id)
                    os.setuid(user_id)

                return wrapper

            subprocess_kwargs["preexec_fn"] = demote(user_pw.pw_uid, user_pw.pw_gid)
        if cwd:
            subprocess_kwargs["cwd"] = cwd

        subprocess_command: Union[List[str], str] = [self.executable] + list(args)
        if shell:
            subprocess_command = shlex.join(subprocess_command)
            subprocess_kwargs["shell"] = True
        logger.debug(
            "Executing subprocess command {0}, kwargs {1}".format(
                subprocess_command, subprocess_kwargs
            )
        )
        return subprocess.Popen(subprocess_command, **subprocess_kwargs)

    def run(
        self,
        *args: str,
        shell: bool = False,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Runs the executable synchronously and returns (out, err).

        :param args str: Arguments to pass to the command.
        :param shell bool: Whether or not to run through the users' shell.

        >>> from pibble.util.helpers import ProcessRunner, Assertion
        >>> from datetime import datetime
        >>> start = datetime.now()
        >>> ProcessRunner("sleep").run("3")
        ('', '')
        >>> Assertion(Assertion.LTE)((datetime.now() - start).total_seconds(), 4) # Give 1 second buffer
        >>> ProcessRunner("echo").run("my text")
        ('my text', '')
        """
        process = self.call(*args, shell=shell, cwd=cwd, user=user)
        out, err = process.communicate()
        if process.returncode != 0:
            logger.error(err)
            raise ChildProcessError(
                f"Child process '{self.executable}' returned error code {process.returncode}"
            )
        if out is not None:
            out = decode(out).strip()
        if err is not None:
            err = decode(err).strip()
        return out, err

    def start(
        self,
        *args: str,
        shell: bool = False,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        """
        Starts the executable asynchronously.

        :param args str: Arguments to pass to the command.
        :param shell bool: Whether or not to run through the users' shell.

        >>> from pibble.util.helpers import ProcessRunner, Assertion
        >>> from datetime import datetime
        >>> start = datetime.now()
        >>> p = ProcessRunner("sleep")
        >>> p.start("3")
        >>> Assertion(Assertion.LT)((datetime.now() - start).total_seconds(), 0.1) # Should be nearly immediate
        >>> p.communicate(5) # Wait longer than necessary
        ('', '')
        >>> Assertion(Assertion.LT)((datetime.now() - start).total_seconds(), 4) # 1 second buffer
        """
        self.process = self.call(*args, shell=shell, cwd=cwd, user=user)

    def running(self) -> bool:
        """
        Check if a process is running.
        """
        return self.process is not None and self.process.returncode is None

    def terminate(self) -> None:
        """
        Terminates a running process. (SIGTERM)
        """
        if self.process is not None:
            if os.name != "nt":
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)  # type: ignore
            else:
                os.kill(self.process.pid, signal.SIGTERM)

    def kill(self) -> None:
        """
        Kills a running process. (SIGKILL)
        """
        if self.process is not None:
            if os.name != "nt":
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)  # type: ignore
            else:
                os.kill(self.process.pid, signal.SIGTERM)

    def communicate(self, timeout: int = 1) -> tuple[Optional[str], Optional[str]]:
        """
        Communicate with a running process.
        """
        if self.process is None:
            raise IOError("Process not started.")
        try:
            out, err = self.process.communicate(timeout=timeout)
            if self.process.returncode is not None and self.process.returncode != 0:
                logger.error(err)
                raise ChildProcessError(
                    f"Child process '{self.executable}' returned error code {self.process.returncode}"
                )
            if out is not None:
                out = decode(out).strip()
            if err is not None:
                err = decode(err).strip()
            return out, err
        except subprocess.TimeoutExpired:
            return "", ""


class PythonRunner(ProcessRunner):
    """
    Extends the ProcessRunner to allow calling python modules
    or scripts from within python itself.
    """

    def __init__(self) -> None:
        super(PythonRunner, self).__init__(sys.executable)

    def module(
        self,
        module: str,
        *args: str,
        sync: bool = True,
        shell: bool = False,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ) -> Optional[tuple[Optional[str], Optional[str]]]:
        """
        Executes a python module.

        >>> from pibble.util.helpers import PythonRunner
        >>> p = PythonRunner()
        >>> out, err = p.module("pip", "help")
        >>> out.splitlines()[0].strip()
        'Usage:'
        """
        if sync:
            return self.run("-m", module, *args, shell=shell, cwd=cwd, user=user)
        self.start("-m", module, *args, shell=shell, cwd=cwd, user=user)
        return None

    def script(
        self,
        script: str,
        sync: bool = True,
        shell: bool = False,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ) -> Optional[tuple[Optional[str], Optional[str]]]:
        """
        Executes a python script in a separate process.

        >>> from pibble.util.helpers import PythonRunner
        >>> p = PythonRunner()
        >>> p.script("import datetime; print(datetime.date(2020, 1, 1))")
        ('2020-01-01', '')
        """
        if sync:
            return self.run("-c", script, shell=shell, cwd=cwd, user=user)
        self.start("-c", script, shell=shell, cwd=cwd, user=user)
        return None


class Printer:
    """
    A printer that uses the termcolor module to output colored text to stdout.
    """

    @staticmethod
    def green(msg: str) -> None:
        """
        Prints in green.
        """
        print(termcolor.colored(msg, "green"))

    @staticmethod
    def red(msg: str) -> None:
        """
        Prints in red.
        """
        print(termcolor.colored(msg, "red"))

    @staticmethod
    def yellow(msg: str) -> None:
        """
        Prints in yellow.
        """
        print(termcolor.colored(msg, "yellow"))

    @staticmethod
    def cyan(msg: str) -> None:
        """
        Prints in cyan.
        """
        print(termcolor.colored(msg, "cyan"))

    @staticmethod
    def magenta(msg: str) -> None:
        """
        Prints in magenta.
        """
        print(termcolor.colored(msg, "magenta"))

    @staticmethod
    def grey(msg: str) -> None:
        """
        Prints in grey.
        """
        print(termcolor.colored(msg, "grey"))

    @staticmethod
    def gray(msg: str) -> None:
        """
        Prints in grey, but misspelled.
        """
        print(termcolor.colored(msg, "grey"))

    @staticmethod
    def white(msg: str) -> None:
        """
        Prints in white.
        """
        print(msg)


class CaseInsensitiveDict(dict):
    """
    A dictionary drop-in that always lowercases keys.
    """

    def get(self, key: str, *args: Any, **kwargs: Any) -> Any:
        return super(CaseInsensitiveDict, self).get(key.lower(), *args, **kwargs)

    def __delitem__(self, key: str) -> None:
        return super(CaseInsensitiveDict, self).__delitem__(key.lower())

    def __getitem__(self, key: str) -> Any:
        return super(CaseInsensitiveDict, self).__getitem__(key.lower())

    def __setitem__(self, key: str, value: Any) -> None:
        return super(CaseInsensitiveDict, self).__setitem__(key.lower(), value)

    def __contains__(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        return super(CaseInsensitiveDict, self).__contains__(key.lower())


class FlexibleJSONDecoder(json.JSONDecoder):
    """
    Extends the base JSONDecoder to allow for more string formats (incl. dates/times.)
    """

    def decode(
        self, string: str, *args: Any
    ) -> Union[dict, list, str, int, float, bool, None]:
        """
        The function called by the decoder - will be passed the raw string of the JSON text.

        :param string str: The contents of the JSON to be decoded.
        :returns Any: The decoded value - see the flexible stringer for more details.
        :see: class:`pibble.helpers.strings.Serializer`
        """
        return Serializer.deserialize(string)  # type: ignore


class FlexibleJSONEncoder(json.JSONEncoder):
    """
    Extends the base JSONEncoder to allow for more string formats (incl. dates/times.)
    """

    def encode(self, to_encode: Any) -> str:
        """
        The function called by the encoder - will be passed anything, and respond with a string.

        :param to_encode Any: The object to encode to a string.
        :returns str: The stringified object.
        :see: class:`funllib.helpers.strings.Serializer`
        """
        return Serializer.serialize(to_encode)

"""
A collection of helpers for dealing with files of various formats.
"""

from __future__ import annotations

import os
import yaml
import json
import pandas as pd
import hashlib

from io import IOBase, TextIOWrapper
from shutil import rmtree
from pathlib import Path
from tempfile import mkdtemp

from typing import Any, Iterable, Iterator, Optional, Literal, Union

from pibble.util.log import logger
from pibble.util.strings import get_uuid, safe_name
from pibble.util.helpers import (
    openpyxl_dataframe,
    FlexibleJSONDecoder,
    FlexibleJSONEncoder,
)

default_missing = pd._libs.parsers.STR_NA_VALUES
try:
    default_missing.remove("")
except KeyError:
    pass

__all__ = [
    "TempfileContext",
    "FileIterator",
    "ConfigParser",
    "SpreadsheetParser",
    "IncludeLoader",
    "load_yaml",
    "load_json",
]


class IncludeLoader(yaml.SafeLoader):
    """
    This loader allows !include directives in yaml files.

    The included files are relative to the directory of the main yaml file.

    For example::
      # vars.yml
      ---
      username: pibbleuser
      first_name: Pibble

      # base.yml
      ---
      context:
        vars: !include vars.yml

      # result
      ---
      context:
        vars:
          username: pibbleuser
          first_name: Pibble
    """

    def __init__(self, stream: TextIOWrapper) -> None:
        """
        :param stream TextIOWrapper: The file stream to read from.
        """
        self._root = os.path.split(stream.name)[0]
        super(IncludeLoader, self).__init__(stream)

    def include(self, node: yaml.nodes.ScalarNode) -> Optional[yaml.nodes.Node]:
        """
        Does the heavy lifting of the inclusion.

        Called by yaml itself.

        :param node yaml.nodes.ScalarNode: A scalar node as returned by the parser. Will
            be either a string, float, or None.
        :returns yaml.nodes.Node: The node of the included file (however it is parsed.)
        """
        filename = self.construct_scalar(node)
        if not isinstance(filename, str):
            return None
        if not filename.startswith("/"):
            filename = os.path.join(self._root, filename)
        with open(filename, "r") as fp:
            return yaml.load(fp, Loader=IncludeLoader)  # type: ignore


IncludeLoader.add_constructor("!include", IncludeLoader.include)


def load_yaml(path: str) -> Any:
    """
    Loads a yaml file, using the IncludeLoader.

    :param path str: The path to load.
    :returns Any: The result, as parsed by pyyaml.

    >>> from pibble.util.files import TempfileContext, load_yaml
    >>> context = TempfileContext()
    >>> context.start()
    >>> main_file, include_file = next(context), next(context)
    >>> _ = open(include_file, "w").write("{role: admin}")
    >>> _ = open(main_file, "w").write("{{username: pibble, meta: !include {0}}}".format(include_file))
    >>> load_yaml(main_file)
    {'username': 'pibble', 'meta': {'role': 'admin'}}
    >>> context.stop()
    """
    with open(path, "r") as fp:
        return yaml.load(fp, Loader=IncludeLoader)


def dump_yaml(path: str, to_dump: Union[dict, list]) -> None:
    """
    Dumps (writes) YAML to a file.

    :param path str: The path to write to.
    :param to_dump dict|list: The YAML to write.
    """
    with open(path, "w") as fp:
        fp.write(yaml.dump(to_dump, default_flow_style=False))


def load_json(path: str) -> Union[dict, list, str, int, float, bool, None]:
    """
    Loads a JSON file, using the Serializer.

    >>> from pibble.util.files import TempfileContext, load_json
    >>> import datetime
    >>> context = TempfileContext()
    >>> context.start()
    >>> path = next(context)
    >>> _ = open(path, "w").write('{"str_key": "abc", "int_key": 4, "float_key": 5.5, "date_key": "2020-01-01", "datetime_key": "2020-01-01T01:00:00"}')
    >>> load_json(path)
    {'str_key': 'abc', 'int_key': 4, 'float_key': 5.5, 'date_key': datetime.date(2020, 1, 1), 'datetime_key': datetime.datetime(2020, 1, 1, 1, 0)}
    >>> context.stop()

    :param path str: The path to the file to read:

    """
    with open(path, "r") as fp:
        return json.loads(fp.read(), cls=FlexibleJSONDecoder)  # type: ignore


def dump_json(path: str, to_dump: Union[dict, list]) -> None:
    """
    Dumps JSON to a file.

    >>> from pibble.util.files import TempfileContext, dump_json
    >>> import datetime
    >>> context = TempfileContext()
    >>> context.start()
    >>> path = next(context)
    >>> dump_json(path, {"str_key": "abc", "int_key": 4, "float_key": 5.5, "date_key": datetime.date(2020, 1, 1), "datetime_key": datetime.datetime(2020, 1, 1, 1, 0)})
    >>> open(path, "r").read()
    '{"str_key": "abc", "int_key": 4, "float_key": 5.5, "date_key": "2020-01-01", "datetime_key": "2020-01-01T01:00:00"}'
    >>> context.stop()
    """
    with open(path, "w") as fp:
        fp.write(json.dumps(to_dump, cls=FlexibleJSONEncoder))


class TempfileContext:
    """
    A simple helper that keeps track of tempfiles, then
    destroys them on exit.

    >>> from pibble.util.files import TempfileContext
    >>> tempfiles = TempfileContext()
    >>> tempfiles.start()
    >>> file_path = next(tempfiles)
    >>> write_contents = "123"
    >>> fp = open(file_path, "w")
    >>> _ = fp.write(write_contents)
    >>> fp.close()
    >>> read_fp = open(file_path, "r")
    >>> read_contents  = read_fp.read()
    >>> read_fp.close()
    >>> assert write_contents == read_contents
    >>> tempfiles.stop()
    >>> import os
    >>> assert not os.path.exists(file_path)
    """

    def __init__(self, mode: Optional[int] = None):
        self.mode = mode

    def touch(self, filename: str) -> str:
        """
        Touches a file - i.e., makes sure it exists, but does not set content.

        :param filename str: The path to the file.
        :return str: The path to the file.
        """
        if not hasattr(self, "directory"):
            raise IOError("Context not started; cannot create files yet.")
        filename = os.path.join(self.directory, filename)
        Path(filename).touch()
        if self.mode is not None:
            os.chmod(filename, self.mode)
        return filename

    def start(self) -> None:
        """
        Starts the context, if it's not started yet.
        """
        if not hasattr(self, "directory"):
            self.directory = mkdtemp()
            if self.mode is not None:
                os.chmod(self.directory, self.mode)

    def stop(self) -> None:
        """
        Stops the context, if it's started.
        """
        if hasattr(self, "directory") and os.path.isdir(self.directory):
            try:
                rmtree(self.directory)
            except Exception as ex:
                logger.error(
                    "Couldn't clean tempfile context: {0}({1})".format(
                        type(ex).__name__, ex
                    )
                )
            del self.directory

    def __iter__(self) -> Iterator[str]:
        """
        Allows for iterating over the context to generate new files.
        """
        while True:
            yield self.touch(get_uuid())

    def __next__(self) -> str:
        """
        Allows calling next(context) to generate a new file.
        """
        return self.touch(get_uuid())

    def __enter__(self) -> Iterator[str]:
        """
        Handles initializing state when using `with`.
        """
        self.start()
        return self.__iter__()

    def __exit__(self, *args: Any) -> None:
        """
        Handles cleaning up state when using `with`.
        """
        self.stop()


class FileIterator:
    """
    A helper that reads a file iteratively. Useful for streaming responses.

    >>> from pibble.util.files import TempfileContext, FileIterator
    >>> from pibble.util.helpers import expect_exception
    >>> tempfiles = TempfileContext()
    >>> tempfiles.start()
    >>> tmp = next(tempfiles)
    >>> _ = open(tmp, "w").write(("A" * 4) + ("B" * 4))
    >>> iterator = FileIterator(tmp, chunk_size=4)
    >>> next(iterator)
    b'AAAA'
    >>> next(iterator)
    b'BBBB'
    >>> expect_exception(StopIteration)(lambda: next(iterator))
    >>> tempfiles.stop()
    """

    def __init__(self, path: str, chunk_size: int = 4096) -> None:
        """
        :param path str: The file to read.
        :param chunk_size int: The number of bytes to read at a time. Defaults to 4 KB.
        """
        self.path = path
        self.chunk_size = chunk_size
        self.handle = open(self.path, "rb")

    def __iter__(self) -> Iterator[bytes]:
        """
        Allows for iterating over the object, i.e.::
            for chunk in FileIterator(path):
                // do something with chunk
        """
        while True:
            try:
                yield next(self)
            except StopIteration:
                if not self.handle.closed:
                    self.handle.close()
                return

    def __next__(self) -> bytes:
        """
        Allows for calling next() on the iterator, i.e.::

            iterator = FileIterator(path)
            while True:
                try:
                    chunk = next(iterator)
                    // do something with chunk
                except StopIteration:
                    pass
        """
        chunk = None
        if not self.handle.closed:
            chunk = self.handle.read(self.chunk_size)
        if not chunk:
            if not self.handle.closed:
                self.handle.close()
            raise StopIteration
        return chunk


class SpreadsheetParser:
    """
    A series of helper functions and sub-classes for reading
    spreadsheets.

    >>> from pibble.util.files import SpreadsheetParser, TempfileContext
    >>> from pibble.util.helpers import expect_exception
    >>> tempfiles = TempfileContext()
    >>> tempfiles.start()
    >>> csv_file = tempfiles.touch("test.csv")
    >>> import csv
    >>> fh = open(csv_file, "w")
    >>> writer = csv.writer(fh)
    >>> resp = writer.writerow(["column_1","column_2"])
    >>> resp = writer.writerow(["string_value", "1"])
    >>> resp = writer.writerow(["other_string_value", "2"])
    >>> fh.close()
    >>> ss = SpreadsheetParser(csv_file)
    >>> iterator = ss.dictIterator()
    >>> next(iterator)
    {'column_1': 'string_value', 'column_2': 1}
    >>> next(iterator)
    {'column_1': 'other_string_value', 'column_2': 2}
    >>> expect_exception(StopIteration)(lambda: next(iterator))
    >>> tempfiles.stop()
    """

    def __init__(
        self,
        file_path: Union[Iterable[dict], IOBase, str],
        parse: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        """
        :param file_path str: The path to the spreadsheet file. Also allows for other IO types.
        :param parse bool: Whether or not to parse the values using Serializer.
        """
        self.path = file_path
        self.parse = parse
        self.kwargs = kwargs

        logger.info(
            "Instantiating spreadsheet iterator on file path {0}".format(str(file_path))
        )

        if "header" not in self.kwargs:
            self.kwargs["header"] = 0

        basename, ext = os.path.splitext(str(file_path))

        if ext.lower() == ".csv":
            if "na_values" not in self.kwargs:
                self.kwargs["na_values"] = default_missing
            if parse is None:
                self.parse = True
            self.read = pd.read_csv
        elif ext.lower() == ".tsv":
            if parse is None:
                self.parse = True
            self.read = lambda *a, **k: pd.read_csv(*a, sep="\t", **k)
        elif ext.lower().startswith(".xls"):
            if parse is None:
                self.parse = False
            if ext.lower() == ".xls":
                if "na_values" not in self.kwargs:
                    self.kwargs["na_values"] = default_missing
                self.read = pd.read_excel
                self.kwargs["engine"] = "xlrd"
            else:
                self.read = openpyxl_dataframe
        else:
            raise TypeError("Can't read spreadsheet type '{0}'.".format(ext))

    @staticmethod
    def fromIO(
        iterable: Iterable[dict],
        format: str = "csv",
        parse: Optional[bool] = None,
        **kwargs: Any,
    ) -> SpreadsheetParser:
        """
        Creates a parser with an IOBase object.

        Used so we can pass a format argument to the parser.
        """
        faux = SpreadsheetParser("temp.{0}".format(format), parse, **kwargs)
        faux.path = iterable
        return faux

    def listIterator(self, include_columns: Optional[bool] = False) -> Iterator[list]:
        """
        Iterates over the spreadsheet in a list.

        :param include_columns bool: Whether or not to include columns (i.e. yield them first.). Default false.
        :returns Iterator[List[Any]]: The iterator over the contents.
        """
        data = self.read(self.path, **self.kwargs)
        if include_columns:
            yield data.columns
        for row in data.values:
            yield row

    def dictIterator(self, safe_names: Optional[bool] = False) -> Iterator[dict]:
        """
        Iterates over the spreadsheet in a dict.

        :param safe_names bool: Whether ot not to rename column keys to their 'safe' versions. Default false.
        :returns Iterator[Dict[Any]]: The iterator over the contents.
        """
        data = self.read(self.path, **self.kwargs)
        columns = data.columns
        if safe_names:
            columns = [safe_name(col) for col in columns]
        self.columns = columns
        for row in data.values:
            yield dict(zip(columns, row))

    def chunkedListIterator(self, chunk_size: int = 100) -> Iterator[list]:
        """
        Same as ``listIterator``, but chunks the reading.

        Doesn't work for all file types - specifically XML-based types (XLSX)
        can't be read iteratively.

        :param chunk_size int: The number of rows to get at once. Default 100.
        :returns Iterator[List[Any]]: The iterator over the contents.
        """
        for chunk in self.read(self.path, chunksize=chunk_size, **self.kwargs):
            for row in chunk.values:
                yield row

    def chunkedDictIterator(
        self, chunk_size: int = 100, safe_names: Optional[bool] = False
    ) -> Iterator[dict]:
        """
        Same as ``dictIterator``, but chunks the reading.

        Doesn't work for all file types - specifically XML-based types (XLSX)
        can't be read iteratively.

        :param chunk_size int: The number of rows to get at once. Default 100.
        :returns Iterator[Dict[Any]]: The iterator over the contents.
        """
        if self.read is pd.read_excel:
            # Can't do it
            for row in self.dictIterator(safe_names):
                yield row
        else:
            for chunk in self.read(self.path, chunksize=chunk_size, **self.kwargs):
                columns = chunk.columns
                if safe_names:
                    columns = [safe_name(col) for col in columns]
                for row in chunk.values:
                    yield dict(zip(columns, row))


def checksum(path: str, method: Literal["md5", "sha1"] = "md5") -> str:
    """
    Performs a checksum on a path. Uses the FileIterator so as not to
    overload memory.

    >>> from pibble.util.files import TempfileContext, checksum
    >>> tempfiles = TempfileContext()
    >>> tempfiles.start()
    >>> sum_file = tempfiles.touch("test.txt")
    >>> fh = open(sum_file, "w")
    >>> _ = fh.write("The quick brown fox jumped over the lazy dog")
    >>> fh.close()
    >>> checksum(sum_file)
    '08a008a01d498c404b0c30852b39d3b8'
    >>> checksum(sum_file, 'sha1')
    'f6513640f3045e9768b239785625caa6a2588842'
    >>> tempfiles.stop()

    :param path str: The path to the file.
    :returns string: The checksum of the file.
    """
    digester = hashlib.md5() if method == "md5" else hashlib.sha1()
    for chunk in FileIterator(path):
        digester.update(chunk)
    return digester.hexdigest()

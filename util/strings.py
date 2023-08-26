import io
import sys
import base64
import string
import hashlib

import email.parser

from re import compile, sub, split
from typing import Any, TypedDict, Optional, Union, Tuple, Dict, List, cast
from random import choice, shuffle
from uuid import uuid4, UUID
from json import dumps, loads, JSONDecodeError
from numpy import nan, isnan
from datetime import datetime, date, time
from chardet import detect
from urllib.parse import unquote
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from pibble.util.log import logger

EMPTY_CASE = compile(r"^$")
LOWER_CASE = compile(r"^[a-z0-9]+$")
UPPER_CASE = compile(r"^[A-Z0-9]+$")
SNAKE_CASE = compile(r"^[A-Za-z0-9]+(_[A-Za-z0-9]+)+$")
KEBAB_CASE = compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$")
CAMEL_CASE = compile(r"^[a-z]+([A-Z][a-z0-9]+)+$")
PASCAL_CASE = compile(r"^([A-Z][a-z0-9]+)+$")
SENTENCE_CASE = compile(r"^(\w+)((\W\w+)+)$")

# CLASSES


def try_json_dict_parse(to_parse: str) -> Union[dict, str]:
    """
    Tries to parse JSON to a dict, but returns the string
    if it fails.
    """
    try:
        loaded = loads(to_parse)
        return dict([(key, Serializer.deserialize(loaded[key])) for key in loaded])
    except JSONDecodeError:
        return to_parse


def try_json_list_parse(to_parse: str) -> Union[list, str]:
    """
    Tries to parse JSON to a list, but returns the string
    if it fails.
    """
    try:
        loaded = loads(to_parse)
        return [Serializer.deserialize(i) for i in loaded]
    except JSONDecodeError:
        return to_parse


def serialize_image(image: Image.Image, **kwargs: Any) -> str:
    """
    Serializes an image to a base64 Data URI.
    """
    image_byte_io = io.BytesIO()
    image_png_info = PngInfo()
    image_text_metadata = getattr(image, "text", {})
    for key in image_text_metadata:
        image_png_info.add_text(key, image_text_metadata[key])
    image.save(image_byte_io, format="PNG", pnginfo=image_png_info)
    image_bytestring = base64.b64encode(image_byte_io.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{image_bytestring}"


def deserialize_image(image_string: str, **kwargs: Any) -> Image.Image:
    """
    Deserializes an image from a base64 Data URI.
    """
    image_bytestring = image_string.split(",")[1]
    image_bytes = base64.b64decode(image_bytestring)
    return Image.open(io.BytesIO(image_bytes))


class Serializer:
    """
    A class that takes a string and attempts to parse it into an object by matching
    it with a regular expression, and vice-versa.

    >>> from pibble.util.strings import Serializer
    >>> from datetime import datetime
    >>> Serializer.deserialize("4")
    4
    >>> Serializer.deserialize("4.0")
    4.0
    >>> Serializer.deserialize("true")
    True
    >>> Serializer.deserialize("2018-01-01T00:00:00")
    datetime.datetime(2018, 1, 1, 0, 0)
    >>> Serializer.serialize(4)
    '4'
    >>> Serializer.serialize(False)
    'false'
    >>> Serializer.serialize(datetime(2018, 1, 1))
    '2018-01-01T00:00:00'

    :param parameter str: The string to attempt to parse.
    :returns object: Either the parameter itself, or the parsed version of it.
    """

    PARSE_FORMATS = {
        compile(r"^data:image/.+;base64,.+$"): lambda p: deserialize_image(p),
        compile(r"^[0-9][0-9\,]*$"): lambda p: int(p.replace(",", "")),
        compile(r"^[0-9][0-9\,]*\.[0-9]*$"): lambda p: float(p.replace(",", "")),
        compile(r"^(null|Null|NULL|none|None|NONE)$"): lambda p: None,
        compile(
            r"^(y|Y|yes|Yes|YES|t|T|true|True|TRUE|n|N|no|No|NO|f|F|false|False|FALSE)$"
        ): lambda p: p.lower()
        in ["t", "true", "y", "yes"],
        compile(r"^\d{4}-\d{1,2}-\d{1,2}$"): lambda p: datetime.strptime(
            p, "%Y-%m-%d"
        ).date(),
        compile(r"^\d{4}\/\d{1,2}\/\d{1,2}$"): lambda p: datetime.strptime(
            p, "%Y/%m/%d"
        ).date(),
        compile(r"^\d{1,2}-\d{1,2}-\d{4}$"): lambda p: datetime.strptime(
            p, "%m-%d-%Y"
        ).date(),
        compile(r"^\d{1,2}-\d{1,2}-\d{2}$"): lambda p: datetime.strptime(
            p, "%m-%d-%y"
        ).date(),
        compile(r"^\d{1,2}\/\d{1,2}\/\d{4}$"): lambda p: datetime.strptime(
            p, "%m/%d/%Y"
        ).date(),
        compile(r"^\d{1,2}\/\d{1,2}\/\d{2}$"): lambda p: datetime.strptime(
            p, "%m/%d/%y"
        ).date(),
        compile(r"^\d{1,2}:\d{1,2}$"): lambda p: datetime.strptime(p, "%H:%M").time(),
        compile(r"^\d{1,2}:\d{1,2}\.\d+$"): lambda p: datetime.strptime(
            p, "%H:%M:%f"
        ).time(),
        compile(
            r"^\d{1,2}:\d{1,2}\ \d{1,2}(-|\/)\d{1,2}(-|\/)\d{4}$"
        ): lambda p: datetime.strptime(p, "%H:%M %m/%d/%Y"),
        compile(
            r"^\d{1,2}:\d{1,2}:\d{1,2}\ \d{1,2}(-|\/)\d{1,2}(-|\/)\d{4}$"
        ): lambda p: datetime.strptime(p, "%H:%M:%S %m/%d/%Y"),
        compile(
            r"^\d{1,2}:\d{1,2}:\d{1,2}\ \d{1,2}(-|\/)\d{1,2}(-|\/)\d{2}$"
        ): lambda p: datetime.strptime(p, "%H:%M:%S %m/%d/%y"),
        compile(
            r"^\d{1,2}(-|\/)\d{1,2}(-|\/)\d{4}\ \d{1,2}:\d{1,2}:\d{1,2}$"
        ): lambda p: datetime.strptime(p, "%m/%d/%Y %H:%M:%S"),
        compile(
            r"^\d{1,2}(-|\/)\d{1,2}(-|\/)\d{2}\ \d{1,2}:\d{1,2}:\d{1,2}$"
        ): lambda p: datetime.strptime(p, "%m/%d/%y %H:%M:%S"),
        compile(
            r"^\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{1,2}:\d{1,2}$"
        ): lambda p: datetime.strptime(p, "%Y-%m-%dT%H:%M:%S"),
        compile(
            r"^\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{1,2}:\d{1,2}\.\d+$"
        ): lambda p: datetime.strptime(p, "%Y-%m-%dT%H:%M:%S.%f"),
        compile(
            r"^\d{4}-\d{1,2}-\d{1,2}\ \d{1,2}:\d{1,2}:\d{1,2}$"
        ): lambda p: datetime.strptime(p, "%Y-%m-%d %H:%M:%S"),
        compile(
            r"^\d{4}-\d{1,2}-\d{1,2}\ \d{1,2}:\d{1,2}:\d{1,2}\.\d+$"
        ): lambda p: datetime.strptime(p, "%Y-%m-%d %H:%M:%S.%f"),
        compile(r"^\{.*\}$"): lambda p: try_json_dict_parse(p),
        compile(r"^\[.*\]$"): lambda p: try_json_list_parse(p),
    }

    SERIALIZE_FORMATS = {
        Image.Image: lambda p, **k: serialize_image(p, **k),
        nan: lambda p, **k: "null",
        type(None): lambda p, **k: "null",
        str: lambda p, **k: p,
        bytes: lambda p, **k: decode(p),
        datetime: lambda p, **k: p.isoformat(),
        date: lambda p, **k: p.isoformat(),
        time: lambda p, **k: p.isoformat(),
        int: lambda p, **k: str(p),
        float: lambda p, **k: str(p),
        dict: lambda p, **k: dump_json(p, **k),
        list: lambda p, **k: dump_json(p, **k),
        bool: lambda p, **k: "true" if p else "false",
    }

    @classmethod
    def deserialize(cls, parameter: Any, permissive: bool = False) -> Any:
        try:
            if isinstance(parameter, list):
                return [cls.deserialize(p) for p in parameter]
            elif isinstance(parameter, dict):
                return dict([(p, cls.deserialize(parameter[p])) for p in parameter])
            elif isinstance(parameter, str):
                test_parameter = parameter.strip().replace("\n", "")
                for pattern in cls.PARSE_FORMATS:
                    if bool(pattern.match(test_parameter)):
                        return cls.PARSE_FORMATS[pattern](test_parameter)  # type: ignore
        except Exception as ex:
            if permissive:
                logger.warning(
                    "Couldn't parse parameter {0}, ignoring.".format(parameter)
                )
                pass
            else:
                raise ValueError(
                    "Can't parse {0}: {1}({2})".format(parameter, type(ex).__name__, ex)
                )
        return parameter

    @classmethod
    def serialize(cls, parameter: Any, **kwargs: Any) -> str:
        # Strict pass
        for typename in cls.SERIALIZE_FORMATS:
            if type(parameter) is typename:
                return cls.SERIALIZE_FORMATS[typename](parameter, **kwargs)  # type: ignore
        # Lenient pass
        for typename in cls.SERIALIZE_FORMATS:
            try:
                if isinstance(parameter, typename):
                    return cls.SERIALIZE_FORMATS[typename](parameter, **kwargs)  # type: ignore
            except TypeError:
                pass
        return str(parameter)


class RandomWordGenerator(object):
    """
    A simple class to generate a random word. Reads from /usr/share/dict/words.

    :param source str: The source dictionary, merely a text file word a word on each line.
    """

    DISALLOWED_WORDS = ["null", "nan", "na"]

    def __init__(self, source: str = "/usr/share/dict/words") -> None:
        self.words = [word.strip() for word in open(source, "r").read().splitlines()]

    def __next__(self) -> str:
        word = choice(self.words)
        if word.lower() in RandomWordGenerator.DISALLOWED_WORDS:
            return self.__next__()
        return word


class UniqueRandomWordGenerator(RandomWordGenerator):
    """
    An extension of the RandomWordGenerator that ensures it
    doesn't repeat. This assumes the source is unique.

    :param source str: The source dictionary, merely a text file word a word on each line.
    """

    def __init__(self, source: str = "/usr/share/dict/words") -> None:
        super(UniqueRandomWordGenerator, self).__init__()
        shuffle(self.words)
        self.index = 0
        self.word_count = len(self.words)

    def __next__(self) -> str:
        if self.index >= self.word_count:
            raise StopIteration()
        word = self.words[self.index]
        self.index += 1
        if word.lower() in RandomWordGenerator.DISALLOWED_WORDS:
            return self.__next__()
        return word


# METHODS

word_generator = None
unique_word_generator = None


def get_random_word() -> str:
    """
    Gets a random word. Instantiates a global generator, if it doesn't exist.
    """
    global word_generator
    if not word_generator:
        word_generator = RandomWordGenerator()
    return next(word_generator)


def get_random_name(length: int = 32) -> str:
    """
    Gets a random name, optionally targeting a certain length.
    """
    name = ""
    while len(name) < length:
        name += pascal_case(get_random_word())
    return name


def get_unique_random_word() -> str:
    """
    Gets a unique random word. Instantiates a global generator, if it doesn't exist.
    """
    global unique_word_generator
    if not unique_word_generator:
        unique_word_generator = UniqueRandomWordGenerator()
    return next(unique_word_generator)


def get_uuid() -> str:
    """
    Generates a UUID.
    """
    return uuid4().hex


def get_seeded_uuid(seed: str) -> str:
    """
    Generates a UUID with a seed, so it's always the same.
    """
    md5_hash = hashlib.md5()
    md5_hash.update(f"pibble.{seed}".encode("utf-8"))
    return UUID(md5_hash.hexdigest()).hex


def dump_json(obj: Union[list, dict], **kwargs: Any) -> str:
    """
    Dumps JSON to a string.
    """

    def _fix_nan(_obj: Any) -> Any:
        if isinstance(_obj, float) and isnan(_obj):
            return None
        elif type(_obj) is list:
            return [_fix_nan(_o) for _o in _obj]
        elif type(_obj) is dict:
            return dict([(_key, _fix_nan(_obj[_key])) for _key in _obj])
        return _obj

    return dumps(_fix_nan(obj), allow_nan=False, default=Serializer.serialize, **kwargs)


def random_string(
    length: int = 32,
    use_uppercase: bool = True,
    use_lowercase: bool = True,
    use_digits: bool = True,
    use_punctuation: bool = False,
) -> str:
    """
    Makes a random string.

    >>> from pibble.util.strings import random_string
    >>> from re import match
    >>> assert match(r"^[a-z]{32}$", random_string(use_uppercase = False, use_digits = False))
    >>> assert match(r"^[a-zA-Z]{32}$", random_string(use_digits = False))
    >>> assert match(r"^[a-zA-Z0-9]{64}$", random_string(64))

    :param length int: The length of the string.
    :param use_uppercase bool: Whether or not to include uppercase characters.
    :param use_lowercase bool: Whether or not to include lowercase characters.
    :param use_digits bool: Whether or not to include digital characters.
    :param use_punctuation bool: Whether or not to include punctuation characters.
    :returns str: A random string of the length specified
    """
    choices = ""
    if use_uppercase:
        choices += string.ascii_uppercase
    if use_lowercase:
        choices += string.ascii_lowercase
    if use_digits:
        choices += string.digits
    if use_punctuation:
        choices += string.punctuation
    if not choices:
        raise ValueError("No characters to choose from.")
    return "".join(choice(choices) for i in range(length))


def truncate(text: Union[str, bytes, bytearray], length: int = 20) -> str:
    """
    Truncates a string to a set length, with additional details.
    Should be used for logging.

    >>> import string
    >>> from pibble.util.strings import truncate
    >>> truncate("12345")
    '12345'
    >>> truncate("12345xxxxx54321", 10)
    '12345...54321 (5 characters truncated)'

    :param text str: The text to truncate.
    :returns object: Either a truncated string if {var} is a string, or the same var.
    """
    if type(text) not in [str, bytes, bytearray]:
        return truncate(str(text), length)

    decoded_text = decode(text)
    if len(decoded_text) > length:
        return "{0}...{1} ({2} characters truncated)".format(
            decoded_text[: length // 2],
            decoded_text[len(decoded_text) - (length // 2) :],
            len(decoded_text) - length,
        )
    return decoded_text


def guess_case(string: str) -> str:
    """
    Guesses the case of a string.

    >>> from pibble.util.strings import guess_case
    >>> guess_case('mystring')
    'LOWER'
    >>> guess_case('MYSTRING')
    'UPPER'
    >>> guess_case('MyString')
    'PASCAL'
    >>> guess_case('myString')
    'CAMEL'
    >>> guess_case('My String')
    'SENTENCE'
    >>> guess_case('my-string')
    'KEBAB'
    >>> guess_case('my_string')
    'SNAKE'
    """
    for test, name in [
        (EMPTY_CASE, "EMPTY"),
        (LOWER_CASE, "LOWER"),
        (UPPER_CASE, "UPPER"),
        (SNAKE_CASE, "SNAKE"),
        (KEBAB_CASE, "KEBAB"),
        (CAMEL_CASE, "CAMEL"),
        (PASCAL_CASE, "PASCAL"),
        (SENTENCE_CASE, "SENTENCE"),
    ]:
        if bool(test.match(string)):
            return name
    return "UNKNOWN"


def guess_string_parts(string: str) -> List[str]:
    """
    Using guess_case, splits a string into it's constituent parts.

    >>> from pibble.util.strings import guess_string_parts
    >>> guess_string_parts('MyString')
    ['my', 'string']
    >>> guess_string_parts('myString')
    ['my', 'string']
    >>> guess_string_parts('my-string')
    ['my', 'string']
    >>> guess_string_parts('my_string')
    ['my', 'string']
    >>> guess_string_parts('my string')
    ['my', 'string']
    """

    string = sub(r"[^A-Za-z0-9_\-\ ]", "", string.strip())
    case = guess_case(string)

    def _regex_split_capture(_regex: str, _string: str) -> List[str]:
        _split = split(_regex, _string)
        parts = []
        for i in range(len(_split)):
            if i == 0 or i % 2 == 1:
                parts.append(_split[i])
            else:
                parts[-1] += _split[i]
        return parts

    if case == "SENTENCE":
        return [s.lower() for s in string.split(" ")]
    elif case == "SNAKE":
        return [s.lower() for s in string.split("_")]
    elif case == "KEBAB":
        return [s.lower() for s in string.split("-")]
    elif case == "CAMEL":
        return [s.lower() for s in _regex_split_capture(r"([A-Z])", string)]
    elif case == "PASCAL":
        return [s.lower() for s in _regex_split_capture(r"([A-Z])", string)[1:]]
    else:
        return [s.lower() for s in sub(r"[_\-]", "", string).split(" ") if s]


def kebab_case(string: str, separator: str = "-") -> str:
    """
    Turns any string into kebab case.

    >>> from pibble.util.strings import kebab_case
    >>> kebab_case('my_string')
    'my-string'
    >>> kebab_case('my-string')
    'my-string'
    >>> kebab_case('My String')
    'my-string'
    >>> kebab_case('MyString')
    'my-string'
    >>> kebab_case('myString')
    'my-string'
    """
    return separator.join(guess_string_parts(string))


def snake_case(string: str, separator: str = "_") -> str:
    """
    Turns any string into snake case.

    >>> from pibble.util.strings import snake_case
    >>> snake_case('my_string')
    'my_string'
    >>> snake_case('my-string')
    'my_string'
    >>> snake_case('My String')
    'my_string'
    >>> snake_case('MyString')
    'my_string'
    >>> snake_case('myString')
    'my_string'
    """
    return separator.join(guess_string_parts(string))


def camel_case(string: str, separator: str = "") -> str:
    """
    Turns any string into camel case.

    >>> from pibble.util.strings import camel_case
    >>> camel_case('my_string')
    'myString'
    >>> camel_case('my-string')
    'myString'
    >>> camel_case('My String')
    'myString'
    >>> camel_case('MyString')
    'myString'
    >>> camel_case('myString')
    'myString'
    """
    parts = guess_string_parts(string)
    return separator.join(
        [
            parts[i] if i == 0 else parts[i][0].upper() + parts[i][1:]
            for i in range(len(parts))
        ]
    )


def pascal_case(string: str, separator: str = "") -> str:
    """
    Turns any string into pscal case.

    >>> from pibble.util.strings import pascal_case
    >>> pascal_case('my_string')
    'MyString'
    >>> pascal_case('my-string')
    'MyString'
    >>> pascal_case('My String')
    'MyString'
    >>> pascal_case('MyString')
    'MyString'
    >>> pascal_case('myString')
    'MyString'
    """
    parts = guess_string_parts(string)
    return separator.join(
        [parts[i][0].upper() + parts[i][1:] for i in range(len(parts))]
    )


def safe_name(string: Any, permissive: Optional[bool] = True) -> str:
    """
    Makes a 'Safe' name from a string.
    """
    if not isinstance(string, str):
        if permissive:
            return string  # type: ignore
        raise ValueError("save_name called on {0}".format(type(string)))
    return sub(r"\W+", "_", string).strip("_")


class Encoding(TypedDict):
    confidence: float
    encoding: str


def detect_encoding(obj: Union[bytes, list, dict]) -> List[Encoding]:
    """
    Detects the encoding of a bytestring based upon the characters present in it. Uses chardet to achieve this.

    :param obj object: The object to detect the encoding of. Generally a string, but can be a list or dict as well.
    :returns list: A list of encodings, of the form {"confidence": x, "encoding": y}. Higher confidence means it is more likely.
    :raises TypeError: When obj is not a string, bytestring, list or dict.
    """
    if isinstance(obj, bytes):
        detected = detect(obj)
        return [
            {
                "confidence": detected["confidence"],
                "encoding": str(detected["encoding"]),
            }
        ]
    elif isinstance(obj, list):
        encodings = []
        for item in obj:
            for encoding in detect_encoding(item):
                if encoding is not None and encoding["encoding"] is not None:
                    encodings.append(encoding)
        return [
            {
                "confidence": sum(
                    [
                        enc["confidence"]
                        for enc in [
                            candidate
                            for candidate in encodings
                            if candidate["encoding"] == encoding
                        ]
                    ]
                )
                / len(encodings),
                "encoding": encoding,
            }
            for encoding in set([enc["encoding"] for enc in encodings])
        ]
    elif isinstance(obj, dict):
        return detect_encoding(list(obj.keys()) + list(obj.values()))
    raise TypeError("Cannot detect encoding of type '{0}'.".format(type(obj).__name__))


def decode(
    obj: Union[str, bytes, list, dict],
    encoding: str = sys.getdefaultencoding(),
) -> str:
    """
    Decodes a bytestring into a unicode string.

    >>> from pibble.util.strings import decode
    >>> decode("my_string")
    'my_string'
    >>> decode(b"my_binary_string")
    'my_binary_string'
    >>> decode("my_utf_string".encode("utf-8"))
    'my_utf_string'

    :param obj object: The object to decode. Usually a string, but can be list or dict.
    :returns object: The object passed, with all bytestring entries/keys/values decoded.
    :raises ValueError: When all attempted encodings fail.
    :raises TypeError: When obj is not a string, bytestring, list or dict.
    """

    def _decode(obj: Any, encoding: str) -> Any:
        if isinstance(obj, str):
            return obj
        elif isinstance(obj, bytes):
            return obj.decode(encoding)
        elif isinstance(obj, list):
            return [_decode(entry, encoding) for entry in obj]
        elif isinstance(obj, dict):
            return dict(
                [(_decode(key, encoding), _decode(obj[key], encoding)) for key in obj]
            )
        raise TypeError(
            "Cannot decode object of type '{0}'.".format(type(obj).__name__)
        )

    if isinstance(obj, str):
        return obj
    try:
        return _decode(obj, encoding)  # type: ignore
    except UnicodeDecodeError:
        detected_encodings = detect_encoding(obj)
        for detected_encoding in sorted(
            detected_encodings,
            key=lambda detected_encoding: detected_encoding["confidence"],
        ):
            try:
                return _decode(obj, detected_encoding["encoding"])  # type: ignore
            except UnicodeDecodeError:
                continue
        try:
            logger.error("Failed in decoding the following value: {!r}".format(obj))
        except:
            pass
        raise ValueError(
            "Cannot decode value. Tried ({0})".format(
                pretty_print(
                    *[
                        detected_encoding["encoding"]
                        for detected_encoding in detected_encodings
                    ]
                )
            )
        )


def encode(
    obj: Union[str, bytes, list, dict],
    encoding: str = sys.getdefaultencoding(),
) -> bytes:
    """
    Encodes a unicode string into a bytestring.

    >>> from pibble.util.strings import encode
    >>> encode("my_string")
    b'my_string'
    >>> encode(b"my_binary_string")
    b'my_binary_string'
    >>> encode(b"my_utf_string".decode("utf-8"))
    b'my_utf_string'

    :param obj object: The object to encode. Usually a string, but can be list or dict.
    :returns object: The object passed, with all bytestring entries/keys/values encoded.
    :raises ValueError: When all attempted encodings fail.
    :raises TypeError: When obj is not a string, bytestring, list or dict.
    """

    def _encode(obj: Any, encoding: str) -> Any:
        if isinstance(obj, str):
            return obj.encode(encoding)
        elif isinstance(obj, bytes):
            return obj
        elif isinstance(obj, list):
            return [_encode(entry, encoding) for entry in obj]
        elif isinstance(obj, dict):
            return dict(
                [(_encode(key, encoding), _encode(obj[key], encoding)) for key in obj]
            )
        raise TypeError(
            "Cannot encode object of type '{0}'.".format(type(obj).__name__)
        )

    try:
        return _encode(obj, encoding)  # type: ignore
    except UnicodeEncodeError:
        if isinstance(obj, str):
            raise ValueError("Cannot encode as {0}".format(encoding))
        detected_encodings = detect_encoding(obj)

        for detected_encoding in sorted(
            detected_encodings,
            key=lambda detected_encoding: detected_encoding["confidence"],
        ):
            try:
                return _encode(obj, detected_encoding["encoding"])  # type: ignore
            except UnicodeEncodeError:
                continue
        try:
            logger.error("Failed in encoding the following value: {!r}".format(obj))
        except:
            pass
        raise ValueError(
            "Cannot encode value. Tried ({0})".format(
                pretty_print(
                    *[
                        detected_encoding["encoding"]
                        for detected_encoding in detected_encodings
                    ]
                )
            )
        )


def pretty_print(*args: Any, **kwargs: Any) -> str:
    """
    Pretty prints a list. Takes any number of arguments or keyword arguments.

    >>> from pibble.util.strings import pretty_print
    >>> print(pretty_print("foo", "bar"))
    foo, bar
    >>> print(pretty_print("foo", bar = "baz"))
    foo, bar=baz
    """
    return ", ".join(
        [str(arg) for arg in args]
        + ["{0}={1}".format(key, kwargs[key]) for key in kwargs]
    )


def pretty_print_sentence(*args: Any, **kwargs: Any) -> str:
    """
    Pretty prints a list with an "and". Takes any number of arguments or keyword arguments.

    No oxford comma.

    >>> from pibble.util.strings import pretty_print_sentence
    >>> print(pretty_print_sentence("foo", "bar"))
    foo and bar
    >>> print(pretty_print_sentence("foo", "bar", "baz"))
    foo, bar and baz
    >>> print(pretty_print_sentence("foo", bar = "baz"))
    foo and bar=baz
    """

    lst = [str(arg) for arg in args] + [
        "{0}={1}".format(key, kwargs[key]) for key in kwargs
    ]

    if len(lst) == 0:
        return ""
    elif len(lst) == 1:
        return lst[0]
    else:
        return "{0} and {1}".format(", ".join(lst[:-1]), lst[-1])


def parse_url_encoded(encoded: str) -> Union[str, Dict[str, Any]]:
    """
    Parses a urlencoded string and returns either the string, or a dictionary of parameters.

    >>> parse_url_encoded("Hello%20Neighbor")
    'Hello Neighbor'
    >>> parse_url_encoded("username=foo&password=bar")
    {'username': 'foo', 'password': 'bar'}
    """
    decoded = unquote(encoded)
    if "=" in decoded:
        return dict(
            [
                cast(Tuple[str, str], tuple(part.split("=")[:2]))
                for part in decoded.split("&")
            ]
        )
    return decoded


class MultipartFile:
    """
    Small wrapper to help reading a multipart file.
    """

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content
        self.limit = len(content)

    @property
    def file(self) -> io.BytesIO:
        return io.BytesIO(self.content)


def parse_multipart(encoded: Union[str, bytes]) -> Dict[str, Union[str, MultipartFile]]:
    """
    Parses a multipart payload.
    """

    parser = email.parser.BytesParser()
    if isinstance(encoded, str):
        message = parser.parsebytes(encoded.strip().encode("utf-8"))
    else:
        message = parser.parsebytes(encoded.strip())
    if not message.is_multipart():
        return {}
    parsed: Dict[str, Union[str, MultipartFile]] = {}
    for part in message.get_payload():
        name = str(part.get_param("name", header="content-disposition"))
        value = part.get_payload(decode=True)
        filename = part.get_filename()
        if filename:
            parsed[name] = MultipartFile(filename, value)
        else:
            parsed[name] = decode(value)
    return parsed

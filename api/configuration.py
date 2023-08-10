import os
from typing import Any

class NoDefaultProvided:
    """
    A "no default provided" class, used to signify that no default value was provided to a get() call.

    The reason we use this instead of "None" is that "None" is a valid thing to ask to be returned to you, whereas
    this class should not be instantiated by classes.
    """

    pass


class APIConfiguration:
    """
    A class to hold configuration values.

    Allows for dot-separated values, like "mydict.myotherdict.mykey".

    >>> from pibble.api.configuration import APIConfiguration
    >>> configuration = APIConfiguration()
    >>> configuration.update(foo = "bar")
    >>> configuration.get("foo")
    'bar'
    >>> configuration["foo"]
    'bar'
    >>> configuration.update(foo = {"bar": "baz"})
    >>> configuration.get("foo.bar")
    'baz'
    >>> configuration.put("foo.bar", "quux")
    >>> configuration.get("foo.bar")
    'quux'
    >>> configuration["foo.bar"] = "xyzzy"
    >>> "foo.bar" in configuration
    True
    >>> configuration["foo.bar"]
    'xyzzy'
    >>> from pibble.util.helpers import expect_exception
    >>> expect_exception(KeyError)(lambda: configuration.get("baz"))
    >>> import os
    >>> os.environ["FOO_BAR_BAZ"] = "25"
    >>> configuration["foo.bar.baz"]
    25
    >>> configuration["foo.bar.baz"] = 26
    >>> configuration["foo.bar.baz"] # Should not have changed
    25
    >>> configuration.environment_prefix = "test" # Should be uppercased
    >>> configuration["foo.bar.baz"]
    26
    >>> os.environ["TEST_FOO_BAR_BAZ"] = "27"
    >>> configuration["foo.bar.baz"]
    27
    """

    def __init__(self, **kwargs: Any) -> None:
        self.environment_prefix = kwargs.pop("environment_prefix", None)
        if kwargs:
            self.configuration = dict(kwargs)
        else:
            self.configuration = {}

    def get_from_environment(self, key: str) -> Any:
        """
        Gets a single value from the environment.

        :param key str: The key to look for.
        :raises KeyError: When the key does not exist in the environment.
        """
        if self.environment_prefix:
            key = "_".join([self.environment_prefix.strip("._"), key])
        key = key.upper().replace(".", "_")
        value = os.getenv(key, NoDefaultProvided())
        if type(value) is NoDefaultProvided:
            raise KeyError(f"Key {key} not found in environment.")
        from pibble.util.strings import Serializer
        return Serializer.deserialize(value)

    def get(self, key: str, default: Any = NoDefaultProvided()) -> Any:
        """
        Gets a single value from the configuration.

        :param key str: The key to look for. Can be dot-separated.
        :param default Any: The default value to return, if you don't want a KeyError raised.
        :raises KeyError: When the key does not exist, and no default was provided.
        :raises TypeError: When attempting to dot-access an object that is not a dictionary.
        """
        try:
            return self.get_from_environment(key)
        except KeyError:
            pass
        keys = key.split(".")
        active = self.configuration
        for keypart in keys:
            try:
                active = active[keypart]
            except TypeError:
                raise KeyError(
                    f"Trying to access property {keypart} of non-object {active} (key {key})"
                )
            except KeyError:
                if type(default) is NoDefaultProvided:
                    raise KeyError(f"Key {key} not configured.")
                else:
                    return default
        return active

    def put(self, key: str, value: Any) -> None:
        """
        Puts a value into the configuration.

        :param key str: The key to put. Can be dot-separated, will create empty dictionaries if a key doesn't exist.
        :param value object: The value to put.
        """
        if key == "environment_prefix":
            self.environment_prefix = f"{value}"
            return
        if isinstance(value, dict):
            for k in value:
                self.put("{0}.{1}".format(key, k), value[k])
            return
        keys = key.split(".")
        active = self.configuration
        for keypart in keys[:-1]:
            if keypart not in active or not isinstance(active[keypart], dict):
                active[keypart] = {}
            active = active[keypart]
        active[keys[-1]] = value

    def has(self, *keys: str) -> bool:
        """
        Determine whether or not a keys exist.

        :param *keys str: Keys to check for.
        :returns bool: True if all exist, else False.
        """
        for key in keys:
            try:
                self.get(key)
            except KeyError:
                return False
        return True

    def update(self, **values: Any) -> None:
        """
        Puts a dictionary of values into the configuration at once.

        :param values dict: The values to put into the configuration. Will overwrite existing values.
        """
        for key in values:
            self.put(key, values[key])

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        return self.put(key, value)

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __repr__(self) -> str:
        return repr(self.configuration)

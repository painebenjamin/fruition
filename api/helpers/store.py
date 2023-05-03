from __future__ import annotations

import sqlalchemy

from pibble.database.engine import EngineFactory
from pibble.database.util import row_to_dict
from pibble.api.exceptions import ConfigurationError
from pibble.api.configuration import APIConfiguration
from pibble.util.strings import Serializer
from pibble.util.helpers import resolve
from pibble.util.log import logger

from typing import Any, Callable, Optional, Dict


class NoDefaultProvided:
    pass


class APISessionStore:
    """
    A helper to store data about API sessions.

    This can be useful for persistent session data, such as
    refresh tokens for authentication.

    In general, this should NOT be used to store or retrieve data relevant to the actual service being provided, and should simply store metadata.

    Required configuration:
      1. ``session.store.driver``: The driver type.

    Optional configuration:
      2. ``session.store.scope``: A scope value. Defaults to None.
      3. ``session.store.serializer``: How values are serialized. Defaults to ``Serializer.serialize``.
      4. ``session.store.deserializer``: How values are deserialized. Defaults to ``Serializer.deserialize``.

    :param configuration pibble.api.configuration.APIConfiguration: The configuration for the server or client.
    """

    CONFIGURATION_PREFIX = "session.store"

    def __init__(self, configuration: APIConfiguration):
        self.serializer = configuration.get(
            "{0}.serializer".format(self.CONFIGURATION_PREFIX),
            Serializer.serialize,
        )
        self.deserializer = configuration.get(
            "{0}.deserializer".format(self.CONFIGURATION_PREFIX), Serializer.deserialize
        )
        self.scope = configuration.get(
            "{0}.scope".format(self.CONFIGURATION_PREFIX), None
        )

        if self.scope is None:
            self.scope = "null"

        if type(self.serializer) in [str, bytes] and not callable(self.serializer):
            try:
                self.serializer = resolve(self.serializer)
            except ImportError:
                raise ConfigurationError(
                    "Cannot resolve serializer name {0}.".format(self.serializer)
                )
        if type(self.deserializer) in [str, bytes] and not callable(self.deserializer):
            try:
                self.deserializer = resolve(self.deserializer)
            except ImportError:
                raise ConfigurationError(
                    "Cannot resolve deserializer name {0}.".format(self.deserializer)
                )

        self.driver = APISessionStoreDriver.get_implementation(
            self.CONFIGURATION_PREFIX, configuration
        )

    def getScope(self, scope: str) -> ScopedAPISessionStore:
        """
        Returns an instance of this store with a different scope.

        :param scope str: The new scope.
        :returns: ``pibble.api.helpers.store.ScopedAPISessionStore``
        """
        return ScopedAPISessionStore(
            scope, self.serializer, self.deserializer, self.driver
        )

    def get(self, key: str, default: Any = NoDefaultProvided()) -> Any:
        """
        Retrieves the value from the store.

        :param key str: The key to retrieve.
        :raises KeyError: When the value does not exist.
        """
        try:
            return self[key]
        except KeyError:
            if type(default) is not NoDefaultProvided:
                return default
            raise

    def has(self, key: str) -> bool:
        """
        Datermines if a key exists.

        :param key str: The key to retrieve.
        """
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def set(self, key: str, value: Any) -> None:
        """
        Sets the value in the store.

        :param key str: The key to retrieve.
        :param value object: The value to place. ***MUST*** be serializable.
        """
        self[key] = value

    def delete(self, key: str) -> None:
        """
        Removes the key from the store.

        :param key str: The key to delete.
        :raises KeyError: When the key does not exist.
        """
        del self[key]

    def __getitem__(self, key: str) -> Any:
        """
        Retrieves the value from the store.

        :param key str: The key to retrieve.
        :raises KeyError: When the value does not exist.
        """
        value = self.driver.get(self.scope, key)
        return self.deserializer(value)

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Sets the value in the store.

        :param key str: The key to retrieve.
        :param value object: The value to place. ***MUST*** be serializable.
        """
        return self.driver.set(self.scope, key, self.serializer(value))

    def __delitem__(self, key: str) -> None:
        """
        Removes the key from the store.

        :param key str: The key to delete.
        :raises KeyError: When the key does not exist.
        """
        return self.driver.delete(self.scope, key)

    def __contains__(self, key: str) -> bool:
        """
        Determines if a key is present in the store.

        :param key str: The key to check for.
        """
        return self.has(key)

    def destroy(self) -> None:
        """
        Deletes the entire store.
        """
        self.driver.destroy()
        del self.driver


class ScopedAPISessionStore(APISessionStore):
    """
    A small extension of the session store to be built when changing scopes.
    """

    def __init__(
        self,
        scope: str,
        serializer: Callable[[Any], str],
        deserializer: Callable[[str], Any],
        driver: APISessionStoreDriver,
    ):
        self.scope = scope
        self.serializer = serializer
        self.deserializer = deserializer
        self.driver = driver


class UnconfiguredAPISessionStore(APISessionStore):
    """
    A session store for non-configured APIs.
    """

    def __init__(self) -> None:
        self.driver = MemoryAPISessionStore(None, None)


class APISessionStoreDriver:
    """
    An extendable class for session stores.

    Implemented classes ***must*** override the ``get(key)`` and ``set(key, value)`` functions.
    Implementing classes ***must*** set the DRIVERNAME class variable.
    """

    DRIVERNAME = ""

    def __init__(
        self,
        configuration_prefix: Optional[str],
        configuration: Optional[APIConfiguration],
    ) -> None:
        self.configuration_prefix = configuration_prefix
        self.configuration = configuration

    def get_configuration(self, key: str, default: Any = NoDefaultProvided()) -> Any:
        if self.configuration is None:
            raise KeyError("Unconfigured session store.")
        result = self.configuration.get(f"{self.configuration_prefix}.{key}", default)
        if isinstance(result, NoDefaultProvided):
            raise KeyError(key)
        return result

    @staticmethod
    def get_implementation(
        configuration_prefix: str, configuration: APIConfiguration
    ) -> APISessionStoreDriver:
        """
        Retrieve and instantiate the configured type.

        :param configuration_prefix str: The configuration prefix. Defaults to ``session.store``.
        :param configuration pibble.api.configuration.APIConfiguration: The configuration object,
        :returns pibble.api.helpers.APISessionStoreDriver: The session store.
        :raises pibble.api.exceptions.ConfigurationError: When the implementation does not exist, or configuration values are not present.
        """
        try:
            drivername = configuration["{0}.driver".format(configuration_prefix)]
            for cls in APISessionStoreDriver.__subclasses__():
                if getattr(cls, "DRIVERNAME", None) == drivername:
                    return cls(configuration_prefix, configuration)
            raise NotImplementedError(
                "Unimplemented driver type {0}.".format(drivername)
            )
        except KeyError as ex:
            raise ConfigurationError(str(ex))

    def get(self, scope: str, key: str) -> Any:
        """
        Retrieves the key from the store.

        :param key str: The key to retrieve.
        :raises KeyError: When the value does not exist.
        """
        raise NotImplementedError()

    def set(self, scope: str, key: str, value: Any) -> None:
        """
        Sets the value in the store.

        :param key str: The key to retrieve.
        :param value object: The value to place. **MUST** be picklebale.
        """
        raise NotImplementedError()

    def delete(self, scope: str, key: str) -> None:
        """
        Delete the value from the store.

        :param key str: The value to delete.
        :raises KeyError: When the key does not exist.
        """
        raise NotImplementedError()

    def destroy(self) -> None:
        """
        Does nothing.
        """


class DatabaseAPISessionStore(APISessionStoreDriver):
    DRIVERNAME = "database"

    def __init__(
        self,
        configuration_prefix: Optional[str],
        configuration: Optional[APIConfiguration],
    ) -> None:
        """
        A driver for database-backed session stores.

        Required configuration:
          1. ``session.store.database.type`` The database type - sqlite, postgresql, mssql, etc.
          2. ``session.store.database.connection`` The connection parameters. See :class:``pibble.database.engine.EngineFactory``.
          3. ``session.store.database.table`` The tablename to select from.

        Optional configuration:
          1. ``session.store.database.key`` The key column. Defaults to "key".
          2. ``session.store.database.value`` The value column. Defaults to "value".
          3. ``session.store.database.scope`` The scope column. Defaults to "scope".
        """
        super(DatabaseAPISessionStore, self).__init__(
            configuration_prefix, configuration
        )

        self.database_type = self.get_configuration("database.type")
        self.database_configuration = self.get_configuration("database.connection")
        self.tablename = self.get_configuration("database.table")
        self.key = self.get_configuration("database.key", "key")
        self.value = self.get_configuration("database.value", "value")
        self.scope = self.get_configuration("database.scope", "scope")

        self.factory = EngineFactory(
            **{self.database_type: self.database_configuration}
        )
        self.engine = next(iter(self.factory[self.database_type]))
        self.metadata = sqlalchemy.MetaData(self.engine)

        try:
            self.table = sqlalchemy.Table(
                self.tablename, self.metadata, autoload=True, autoload_with=self.engine
            )
        except sqlalchemy.exc.NoSuchTableError:
            self.table = sqlalchemy.Table(
                self.tablename,
                self.metadata,
                sqlalchemy.Column(self.scope, sqlalchemy.String(32), primary_key=True),
                sqlalchemy.Column(self.key, sqlalchemy.String(32), primary_key=True),
                sqlalchemy.Column(self.value, sqlalchemy.String(512)),
            )
            self.metadata.create_all()

    def _where(self, scope: str, key: str) -> Any:
        return sqlalchemy.and_(
            self.table.c[self.key] == key, self.table.c[self.scope] == scope
        )

    def get(self, scope: str, key: str) -> Any:
        row = self.engine.execute(
            self.table.select().where(self._where(scope, key))
        ).first()
        if not row:
            raise KeyError(f"{scope}.{key}")
        return row_to_dict(row)[self.value]

    def set(self, scope: str, key: str, value: Any) -> None:
        try:
            self.engine.execute(
                self.table.insert().values(
                    **{self.key: key, self.value: value, self.scope: scope}
                )
            )
        except sqlalchemy.exc.IntegrityError:
            self.engine.execute(
                self.table.update()
                .values(**{self.value: value})
                .where(self._where(scope, key))
            )

    def delete(self, scope: str, key: str) -> None:
        result = self.engine.execute(self.table.delete().where(self._where(scope, key)))
        if result.rowcount == 0:
            raise KeyError(f"{scope}.{key}")

    def destroy(self) -> None:
        logger.debug("Disposing of database engines.")
        self.factory.dispose(self.engine)


class MemoryAPISessionStore(APISessionStoreDriver):
    """
    An implementation for storing data in memory. Uses a simple dictionary.
    """

    DRIVERNAME = "memory"
    memory: Dict[str, Dict[str, Any]]

    def __init__(
        self,
        configuration_prefix: Optional[str],
        configuration: Optional[APIConfiguration],
    ) -> None:
        super(MemoryAPISessionStore, self).__init__(configuration_prefix, configuration)
        self.memory = {}

    def get(self, scope: str, key: str) -> Any:
        return self.memory[scope][key]

    def set(self, scope: str, key: str, value: Any) -> None:
        if scope not in self.memory:
            self.memory[scope] = {}
        self.memory[scope][key] = value

    def delete(self, scope: str, key: str) -> None:
        del self.memory[scope][key]

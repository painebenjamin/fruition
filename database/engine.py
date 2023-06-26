from __future__ import annotations

import sqlalchemy
import os

try:
    import pyodbc
except ImportError:
    pyodbc = None

from typing import Any, List, Dict, cast
from typing_extensions import Self

from sqlalchemy.engine.url import URL
from sqlalchemy.engine.base import Engine as EngineBase
from pibble.util.log import logger

from sqlalchemy.schema import DropTable
from sqlalchemy.ext.compiler import compiles

os.environ["TDSVER"] = "8.0"


@compiles(DropTable, "postgresql")  # type: ignore
def _compile_drop_table(element: Any, compiler: Any, **kwargs: Any) -> Any:
    return compiler.visit_drop_table(element) + " CASCADE"


class Engine:
    """
    An 'engine' class, made to wrap around SQLAlchemy's engine creation.

    The usefulness of this is found in accessing multiple databases within one database connection. Instantiating an engine, then calling engine.default, engine.my_db_name, etc., will create a new engine connected to that database in the same connection.

    The arguments for each driver type vary, but a list of general ones is documented.

    :param drivername str: The driver name for the connection. Usually the type of database (mysql, mssql, etc.), but if a specific driver should be used, you should use "type"+"driver". e.g., postgresql+psycopg2.
    :param host str: The host to connect to. Defaults to loopback.
    :param port int: The port to connect to. Defaults are supplied for known connection types.
    :param username str: A username to use for authentication. This authentication is handled by the driver, so the method varies.
    :param password str: A password to use for authentication.
    :param database str: An initial database to connect to. If ommitted, the engine will connect to "default" initially.
    """

    KNOWN_KEYS = ["drivername", "username", "password", "host", "port", "database"]

    engines: Dict[str, EngineBase]

    def __init__(self, name: str, **connection_params: Any):
        self.name = name
        self.connection_params = {}
        for key in connection_params:
            if key in Engine.KNOWN_KEYS:
                self.connection_params[key] = connection_params[key]
            else:
                if "query" not in self.connection_params:
                    self.connection_params["query"] = {}
                self.connection_params["query"][key] = connection_params[key]
        self.engines = {}
        if "database" in self.connection_params:
            self._default_database = str(self.connection_params.pop("database"))
            if self.connection_params["drivername"].startswith(
                "sqlite"
            ) and self._default_database.startswith("~"):
                self._default_database = os.path.expanduser(self._default_database)
                database_dir = os.path.dirname(self._default_database)
                if not os.path.exists(database_dir):
                    try:
                        os.makedirs(database_dir)
                    except:
                        logger.error(
                            f"Database directory {database_dir} does not exist, and it could not be created."
                        )
                        raise
        else:
            self._default_database = "default"
        self._create_engine(self._default_database)

    def __iter__(self) -> Self:
        self._iterkeys = list(self.engines.keys())
        self._iterindex = 0
        return self

    def __next__(self) -> EngineBase:
        if self._iterindex > len(self._iterkeys):
            raise StopIteration
        _engine = self.engines[self._iterkeys[self._iterindex]]
        self._iterindex += 1
        return _engine

    def __getattr__(self, database_name: str) -> EngineBase:
        if database_name not in self.engines:
            self._create_engine(database_name)
        return self.engines[database_name]

    def __delattr__(self, database_name: str) -> None:
        if database_name in self.engines:
            self.engines[database_name].dispose()

    def __getitem__(self, database_name: str) -> EngineBase:
        return getattr(self, database_name)

    def __delitem__(self, database_name: str) -> None:
        return delattr(self, database_name)

    def _create_engine(self, database_name: str) -> None:
        """
        Builds the actual SQLAlchemy engine.
        """
        conn_string = URL(**{**self.connection_params, **{"database": database_name}})
        logger.info(
            "Creating SQLAlchemy engine using connection string {0}".format(conn_string)
        )
        self.engines[database_name] = sqlalchemy.create_engine(
            conn_string,
            pool_reset_on_return=None,
        )
        if "pyodbc" in self.connection_params["drivername"]:
            if pyodbc is None:
                raise OSError(
                    "Failed to import PyODBC. This server/container likely needs ODBC configuration."
                )

            def decode_sketchy_utf16(raw_bytes: bytes) -> str:
                s = raw_bytes.decode("utf-16le", "ignore")
                try:
                    n = s.index("\u0000")
                    s = s[:n]  # respect null terminator
                except ValueError:
                    pass
                return s

            self.engines[database_name].connect().connection.add_output_converter(
                pyodbc.SQL_WVARCHAR, decode_sketchy_utf16
            )

    def default(self) -> EngineBase:
        return self[self._default_database]

    def dispose(self) -> None:
        """
        Closes all engines.
        """
        for database_name in self.engines:
            conn_string = URL(
                **{**self.connection_params, **{"database": database_name}}
            )
            logger.info(
                "Shedding SQLAlchemy engine for connection string {0}".format(
                    conn_string
                )
            )
            try:
                self.engines[database_name].dispose()
            except Exception:
                pass
        self.engines = {}


class NoEngine:
    def __init__(self, name: str):
        self.name = name

    def __getattr__(self, key: str) -> Any:
        raise NotImplementedError(
            "The engine for database type {0} is not configured.".format(self.name)
        )


class EngineFactory:
    """
    The EngineFactory is used to create Engines. See :class:pibble.database.engine.Engine

    :param kwargs dict: A dictionary containing "key" => "configuration" pairs, where "configuration" is a dictionary containing necessary configuration keys.
    """

    DEFAULTS: Dict[str, Dict[str, Any]] = {
        "postgres": {
            "drivername": "postgresql+psycopg2",
            "database": "default",
        },
        "impala": {
            "drivername": "impala",
            "auth_mechanism": "NOSASL",
            "database": "default",
        },
        "hive": {
            "drivername": "hive",
            "auth": "NONE",
            "database": "default",
        },
        "mssql": {
            "drivername": "mssql+pyodbc_mssql",
            "database": "default",
            "driver": "ODBC Driver 17 for SQL Server",
        },
        "sqlite": {"drivername": "sqlite", "database": ":memory:"},
        "mysql": {
            "drivername": "mysql",
            "database": "default",
        },
    }

    configuration: Dict[str, Dict[str, Any]]
    stores: List[EngineStore]

    def __init__(self, **kwargs: Dict[str, Any]):
        self.configuration = {}
        for key in EngineFactory.DEFAULTS:
            self.configuration[key] = {**EngineFactory.DEFAULTS[key]}
        for key in kwargs:
            self.configuration[key].update(kwargs[key])
        self.stores = []

    def configure(self, **kwargs: Any) -> None:
        """
        Updates configuration with new values.

        :param kwargs dict: The configuration to update, see constructor for details.
        """
        for key in kwargs:
            self.configuration[key].update(kwargs[key])

    def get(self, engine_type: str, **configuration: Any) -> Engine:
        """
        Gets an engine based on engine type.

        An optional second argument will override any configured default values. This will first iterate through existing engines to ensure we aren't duplicating effort.

        :param engine_type str: The engine type. See EngineFactory.DEFAULTS, the keys present there are known engine types - though using SQLAlchemy means this can be extended.
        :param configuration dict: Any configuration to override default values with.
        :return pibble.database.engine.Engine: The engine requested.
        """
        configuration = {**self.configuration.get(engine_type, {}), **configuration}
        for store in self.stores:
            if (
                store.engine_type == engine_type
                and store.configuration == configuration
            ):
                return store.engine
        store = EngineFactory.EngineStore(engine_type, **configuration)
        self.stores.append(store)
        return store.engine

    @staticmethod
    def singleton(engine_type: str, **engine_kwargs: Any) -> EngineBase:
        """
        Gets a single SQLAlchemy engine.
        """
        return next(iter(EngineFactory().get(engine_type, **engine_kwargs)))

    def dispose(self, engine: Engine) -> None:
        """
        Dispose of an individual engine. Generally not used, as long as the context manager is used.

        :param engine pibble.database.engine.Engine: The engine to dispose of.
        """
        self.stores = [store for store in self.stores if store.engine is not engine]
        engine.dispose()

    def __getitem__(self, key: str) -> Engine:
        return cast(Engine, getattr(self, key))

    def __delitem__(self, key: str) -> None:
        return delattr(self, key)

    def __getattr__(self, key: str) -> Engine:
        return self.get(key)

    def __enter__(self) -> EngineFactory:
        return self

    def __exit__(self, *args: Any) -> None:
        _stores = self.stores
        self.stores = []
        for store in _stores:
            store.dispose()

    class EngineStore:
        """
        A small wrapper object to hold an engine and the associated configuration with it.

        :param engine_type str: The engine type.
        :param kwargs dict: Any configuration value used when creating this engine.
        """

        def __init__(self, engine_type: str, **kwargs: Any):
            self.engine_type = engine_type
            self.configuration = kwargs
            self.initialize()

        def dispose(self) -> None:
            """
            Closes the engine.
            """
            _engine = self.engine
            del self.engine
            _engine.dispose()

        def initialize(self) -> None:
            """
            Initializes the engine.
            """
            self.engine = Engine(self.engine_type, **self.configuration)

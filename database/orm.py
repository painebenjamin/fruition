from __future__ import (
    annotations,
)  # allows accessing declared classes in this file in type hints

import sqlalchemy

from traceback import format_exc

from pibble.api.exceptions import PermissionError, BadRequestError
from pibble.api.configuration import APIConfiguration

from pibble.util.log import logger
from pibble.util.helpers import resolve
from pibble.util.strings import Serializer, decode
from pibble.util.encryption import AESCipher

from pibble.database.engine import EngineFactory

from typing import Optional, Type, Iterator, Any, Callable, Union, List, Dict, cast

from sqlalchemy import Column, Integer, String, Sequence, ForeignKey

from sqlalchemy.exc import InvalidRequestError

from sqlalchemy.orm import sessionmaker, scoped_session, relationship, Query
from sqlalchemy.orm.session import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute, ScalarAttributeImpl

from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.ext.declarative import declarative_base

FILE_CHUNK_SIZE = 1000


class ORMQuery(Query):  # type: ignore
    """
    A wrapper around a query which permits retrying.
    """

    def __init__(self, orm_session: ORMSession, arg: Any) -> None:
        self.orm_session = orm_session
        super(ORMQuery, self).__init__(arg, session=orm_session.session)

    def reset_retry(self) -> None:
        """
        Resets the retry counter.
        """
        if hasattr(self, "_retried"):
            del self._retried

    def can_retry(self) -> bool:
        """
        Gets if this query has been retried.
        """
        if not hasattr(self, "_retried"):
            self._retried = True
            return True
        return not getattr(self, "_retried", False)

    def _iter(self) -> Any:
        """
        Overrides the base _iter(), which all results-producing methods call.
        """
        try:
            result = super(ORMQuery, self)._iter()
            return result
        except Exception as ex:
            if not self.can_retry():
                raise
            logger.info(
                "Received exception {0}, retrying query.".format(type(ex).__name__)
            )
            logger.debug(str(ex))
            self.orm_session.reset()
            self.session = self.orm_session.session
            return self._iter()


class ORMSession:
    """
    A context manager for sessions.

    Most of the time, function calls will be passed to the underlying session object.

    Should not be instantiated manually. Call ORM.session() to instantiate.

    :param session Session: The SQLALchemy session to wrap around.
    :param kwargs
    """

    def __init__(
        self,
        orm: ORM,
        session: Session,
        autocommit: Optional[bool] = False,
        **kwargs: Any,
    ):
        self.orm = orm
        self.session = session
        self.autocommit = autocommit

    def commit(self) -> None:
        """
        Commits the session. Permissive over InvalidRequestError, which occurs when there
        is nothing to commit.
        """
        try:
            self.session.commit()
        except InvalidRequestError:
            pass

    def close(self) -> None:
        """
        Closes the session, logs and ignores errors.
        """
        try:
            self.session.close()
        except Exception as ex:
            logger.warning(
                "Received {0} during close, ignoring.".format(type(ex).__name__)
            )
            logger.debug(str(ex))

    def rollback(self) -> None:
        """
        Rolls back the session, logs and ignores errors.
        """
        try:
            self.session.rollback()
        except Exception as ex:
            logger.warning(
                "Received {0} during rollback, ignoring.".format(type(ex).__name__)
            )
            logger.debug(str(ex))

    def get(self) -> Session:
        """
        Retrieves the underlying session.
        """
        return self.session

    def add(self, *objects: Any) -> Any:
        """
        Adds all objects to the session.
        """
        self.session.add_all(list(objects))
        if len(objects) == 1:
            return objects[0]
        return objects

    def query(self, arg: Any) -> ORMQuery:
        """
        Returns a wrapper around a query which permits retrying.
        """
        return ORMQuery(self, arg)

    def reset(self) -> None:
        """
        Resets the session.
        """
        self.session = self.orm.session()

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.session, attr)

    def __enter__(self) -> ORMSession:
        return self

    def __exit__(self, *args: Any) -> None:
        try:
            if self.autocommit:
                self.commit()
        finally:
            self.close()


class ORMSolidifiedObject:
    """
    A small way to "solidify" an object.

    This is only necessary because of the way sqlalchemy stores state.
    """

    def __init__(self, **kwargs: Any):
        for key in kwargs:
            setattr(self, key, kwargs[key])


class ORMObjectBase:
    """
    A simple class which should be extended for declaring ORM objects.

    This should be treated identically to a sqlalchemy declarative base object.

    :see: https://docs.sqlalchemy.org/en/13/orm/index.html
    """

    __tablename__: str
    __hidden_columns__: List[str]
    __hidden_relationships__: List[str]
    __default_hidden_columns__: List[str]

    @classmethod
    def Relationship(cls, **kwargs: Any) -> InstrumentedAttribute:
        """
        Declare a relationship within a class structure.

        Usage is like so::

          class User(ORMObjectBase):
            id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence("page_id_sequence"), primary_key = True)

          class Address(ORMObjectBase):
            id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence("address_id_sequence"), primary_key = True)
            user_id = sqlalchemy.Column(User.ForeignKey("id"))
            user = User.Relationship()

        This allows you to call `Address.user` to get the associated `User` object.
        This does NOT define new columns or foreign keys.
        """

        return relationship("{0}Declarative".format(cls.__name__), **kwargs)

    @classmethod
    def Relate(
        cls, othercls: Type[ORMObjectBase], name: Optional[str] = None, **kwargs: Any
    ) -> InstrumentedAttribute:
        """
        Declare a relationship outside of a class structure.

        Usage is like so::

          class User(ORMObjectBase):
            id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence("page_id_sequence"), primary_key = True)

          class Address(ORMObjectBase):
            id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.Sequence("address_id_sequence"), primary_key = True)
            user_id = sqlalchemy.Column(User.ForeignKey("id"))
            user = User.Relationship()

          User.Relate(Address)

        This allows you to call `User.Address` to get the list of associated addresses.
        You can also change the name of the field - by default it is the class name. So calling `User.Relate(Address)` creates the `User.Address` field, but calling `User.Relate(Address, "addresses")` creates `User.addresses`.
        """
        setattr(cls, name or othercls.__name__, othercls.Relationship(**kwargs))

    @classmethod
    def ForeignKey(cls, column: str, **kwargs: Any) -> ForeignKey:
        """
        A small helper so you don't have to know the tablename of an object
        to build a foreign key to that class.
        """
        return ForeignKey("{0}.{1}".format(cls.__tablename__, column), **kwargs)

    @classmethod
    def Hide(
        cls,
        columns: Optional[Union[List[str], str]] = [],
        relationships: Optional[Union[List[str], str]] = [],
    ) -> None:
        """
        Configures columns and relationships that will
        not be passed through in a format() call.
        """
        existing_columns: List[str] = []
        existing_columns.extend(getattr(cls, "__hidden_columns__", []))
        if not isinstance(columns, list):
            columns = cast(List[str], [columns])
        existing_columns.extend(columns)
        setattr(cls, "__hidden_columns__", existing_columns)

        existing_relationships: List[str] = []
        existing_relationships.extend(getattr(cls, "__hidden_relationships__", []))
        if not isinstance(relationships, list):
            relationships = cast(List[str], [relationships])
        existing_relationships.extend(relationships)
        setattr(cls, "__hidden_relationships__", existing_relationships)

    @classmethod
    def DefaultHide(cls, *columns: str) -> None:
        """
        Configures columns that will, by default, not be passed through
        in a format() call, but can be requested.
        """
        existing_columns: List[str] = []
        existing_columns.extend(getattr(cls, "__default_hidden_columns__", []))
        existing_columns.extend(columns)
        setattr(cls, "__default_hidden_columns__", existing_columns)

    @staticmethod
    def _is_simple_data(value: Any) -> bool:
        """
        A way to differentiate between columnar data and other data.
        Actually reads inheritence to ensure the object inherits from a 'primitive' type.
        """
        return type(value).mro()[-2] in [
            str,
            int,
            float,
            complex,
            bool,
            bytes,
            bytearray,
            memoryview,
            type(None),
        ]

    def get_attributes(self) -> Dict[str, Any]:
        """
        Returns the dictionary of columns (attributes) for formatting.
        """
        attribute_dict: Dict[str, Any] = {}
        for k in dir(self):
            v = getattr(self, k, None)
            v_static = getattr(type(self), k, None)
            v_impl_type = type(getattr(v_static, "impl", None))
            if v_impl_type is ScalarAttributeImpl:
                attribute_dict[k] = v

        return attribute_dict

    def see(self, *args: ORMObjectBase) -> None:
        """
        Includes an object in formatting, as a 'see-also' mechanic.
        """
        included = getattr(self, "__see_also__", [])
        setattr(self, "__see_also__", included + list(args))

    def format(self, **kwargs: Any) -> dict:
        """
        This returns a dictionary of what should be meaningful information about this object.

        It should include the type of the object (the class name), any metadata
        relating to how this object was chosen (search likeness), and then the
        attributes about the object itself.

        This will *not* include instrumented lists, i.e., relationships to other objects. If
        you want those, you can pass the `include` parameter, which is list of relationships
        to include. This also supports nested relationships using a dot-separation syntax,
        e.g., ``include = ["products","products.related"]`` would include "products", then pass
        "related" to the product object to get that instrumented list and format it as well.

        """
        attributes = self.get_attributes()
        for hidden in getattr(self, "__hidden_columns__", []):
            if hidden in attributes:
                del attributes[hidden]
        for default_hidden in getattr(self, "__default_hidden_columns__", []):
            if default_hidden in attributes and default_hidden not in kwargs.get(
                "show", []
            ):
                del attributes[default_hidden]

        response = {
            "type": type(self).__name__.replace("Declarative", ""),
            "attributes": attributes,
        }

        if "include" in kwargs and kwargs["include"]:
            include: Dict[str, Optional[List[Optional[ORMObjectBase]]]] = {}
            include_paths = kwargs["include"]
            hidden_relationships = getattr(self, "__hidden_relationships__", [])

            if not isinstance(include_paths, list):
                include_paths = [include_paths]

            for include_path in include_paths:
                if include_path.find(".") != -1:
                    continue
                if include_path in hidden_relationships:
                    raise PermissionError(
                        "Relationship {0} is not allowed to be queried.".format(
                            include_path
                        )
                    )

                try:
                    included_item = getattr(self, include_path)
                    if callable(included_item):
                        included_item = included_item(self)
                    if included_item is not None and not isinstance(
                        included_item, list
                    ):
                        included_item = [included_item]
                except Exception as ex:
                    logger.error("{0}: {1}".format(type(ex).__name__, ex))
                    logger.debug(format_exc())
                    raise BadRequestError(
                        "Unknown or bad relationship {0}({1})".format(
                            response["type"], include_path
                        )
                    )

                deep_zoom = [
                    ".".join(path.split(".")[1:])
                    for path in include_paths
                    if path.startswith(f"{include_path}.")
                ]

                if deep_zoom:
                    formatter = lambda i: i.format(include=deep_zoom)
                else:
                    formatter = lambda i: i.format()

                if included_item is None:
                    include[include_path] = None
                else:
                    include[include_path] = [
                        None if item is None else formatter(item)  # type: ignore
                        for item in included_item
                    ]
            response["include"] = include

        see = getattr(self, "__see_also__", [])
        if see:
            response["see"] = [
                item.format()
                if hasattr(item, "format") and callable(getattr(item, "format", None))
                else item
                for item in see
            ]
        return response

    def solidify(self) -> ORMSolidifiedObject:
        """
        Returns the "solidified" object (removing sqlalchemy state.)
        """
        return ORMSolidifiedObject(**self.get_attributes())

    @classmethod
    def _declared_functions(cls) -> Dict[str, Callable]:
        """
        Gets the functions that will pass through into the results of the session queries.
        """
        return {
            "format": cls.format,
            "solidify": cls.solidify,
            "see": cls.see,
            "get_attributes": cls.get_attributes,
        }

    @classmethod
    def _declared_dict(cls, orm: ORM) -> Dict[str, Any]:
        """
        Gets class variables necessary to declare an object inherited a declarative base.
        """
        _declared = cls._declared_functions()
        _declared["__orm__"] = orm  # type: ignore
        _vars = vars(cls)
        for mapped in _vars:
            if isinstance(_vars[mapped], sqlalchemy.Column):
                setattr(_vars[mapped], "__orm__", orm)
                setattr(_vars[mapped].type, "__orm__", orm)
            _declared[mapped] = _vars[mapped]
        return _declared

    @classmethod
    def _declared_classes(cls) -> Iterator[Type[ORMObjectBase]]:
        """
        Returns all classes that have extended the base.
        """
        for subcls in cls.__subclasses__():
            if hasattr(subcls, "__tablename__"):
                yield subcls
            else:
                logger.info(
                    "Ignoring subclass {0} due to lack of __tablename__ attribute. If this is not intentional, declare a __tablename__ to migrate this subclass.".format(
                        subcls.__name__
                    )
                )


class ORMEncryptedStringType(sqlalchemy.types.TypeDecorator):  # type: ignore
    """
    Using `pibble.util.AESCipher`, encrypt values on their way into the database,
    and decrypt values on their way out of the database. Use the same way you'd use sqlalchemy.String.

    See the class in pibble.util for additional info, but the gist is that you
    should either pass a static password (string) and salt (string, 8 bytes base64-encoded),
    or a key (string, 32 bytes base64-encoded) as the seed for the cipher. If you don't
    pass the key or the password+salt pair, you *must* store the key generated by
    the cipher (cipher.b64key()) in order to be able to decrypt. Otherwise, you'll lose
    the key and the ability to decode.
    """

    impl = sqlalchemy.String

    def process_bind_param(self, value: str, dialect: Dialect) -> str:
        return decode(self.__orm__.cipher.encrypt(value))

    def process_result_value(self, value: str, dialect: Dialect) -> str:
        return decode(self.__orm__.cipher.decrypt(value))


class ORMEncryptedTextType(sqlalchemy.types.TypeDecorator):  # type: ignore
    """
    Using `pibble.util.AESCipher`, encrypt values on their way into the database,
    and decrypt values on their way out of the database. Use the same way you'd use sqlalchemy.String.

    See the class in pibble.util for additional info, but the gist is that you
    should either pass a static password (string) and salt (string, 8 bytes base64-encoded),
    or a key (string, 32 bytes base64-encoded) as the seed for the cipher. If you don't
    pass the key or the password+salt pair, you *must* store the key generated by
    the cipher (cipher.b64key()) in order to be able to decrypt. Otherwise, you'll lose
    the key and the ability to decode.
    """

    impl = sqlalchemy.Text

    def process_bind_param(self, value: str, dialect: Dialect) -> str:
        return decode(self.__orm__.cipher.encrypt(value))

    def process_result_value(self, value: str, dialect: Dialect) -> str:
        return decode(self.__orm__.cipher.decrypt(value))


class ORMVariadicType(sqlalchemy.types.TypeDecorator):  # type: ignore
    """
    Using `pibble.util.Serializer` and `pibble.util.Serializer`, serialize values
    on their way into the databased, and deserialize them on their way out.
    """

    impl = sqlalchemy.String

    def process_bind_param(self, value: Any, dialect: Dialect) -> str:
        return Serializer.serialize(value)

    def process_result_value(self, value: str, dialect: Dialect) -> Any:
        return Serializer.deserialize(value)


class ORMEncryptedVariadicType(sqlalchemy.types.TypeDecorator):  # type: ignore
    """
    Combines the encrypted and variadic types.
    """

    impl = sqlalchemy.String

    def process_bind_param(self, value: Any, dialect: Dialect) -> str:
        return decode(self.__orm__.cipher.encrypt(Serializer.serialize(value)))

    def process_result_value(self, value: str, dialect: Dialect) -> Any:
        return Serializer.deserialize(decode(self.__orm__.cipher.decrypt(value)))


class ORMObject:
    """
    A small class to make isinstance() easier on classes extending the declarative_base()
    """

    pass


class ORM:
    """
    The meat of the ORM, this is a very mild extension of the sqlalchemy declarative base, making for slightly easier scoping across modules.

    Some example usage::
      import sqlalchemy
      from pibble.database.orm import ORM
      from pibble.database.orm import ORMBObjectBase

      class User(ORMObjectBase):
        __tablename__ = "user"
        id = sqlalchemy.Column(sqlalchemy.Integer, primary_key = True)
        username = sqlalchemy.Column(sqlalchemy.String, unique = True)

      orm = ORM(migrate = True) # Creates the user table.

    >>> import sqlalchemy
    >>> from pibble.database.orm import ORMBuilder
    >>> builder = ORMBuilder("sqlite")
    >>> declared = builder.extend("user", {"id": sqlalchemy.Column(sqlalchemy.Integer, primary_key = True)})
    >>> builder.migrate()
    >>> session = builder.session()
    >>> session.get().add(builder.user(id = 1))
    >>> session.commit()
    >>> session.get().query(builder.user).first().id
    1

    :param engine sqlalchemy.Engine: The engine to use with this ORM.
    :param base type: The type to check for subclasses of. Note that subclass checking is not recursive.
    """

    bases: List[Type[ORMObjectBase]]
    models: Dict[str, Type]

    def __init__(
        self,
        engine: Engine,
        migrate: bool = False,
        force: bool = False,
        base: Union[Type[ORMObjectBase], List[Type[ORMObjectBase]]] = ORMObjectBase,
        cipher: Optional[AESCipher] = AESCipher(),
    ):
        self.engine = engine
        self.bases = []
        self.models = {}

        if type(base) is not list:
            base = cast(List[Type[ORMObjectBase]], [base])

        for object_base in base:
            if type(object_base) is not type:
                object_base = resolve(object_base)
            self.bases.append(object_base)

        self.declarative_base = declarative_base(self.engine)
        self.sessionmaker = sessionmaker(self.engine)
        self.cipher = cipher

        if migrate:
            self.migrate(force)

    def session(
        self, test: bool = True, retry: bool = True, **kwargs: Any
    ) -> ORMSession:
        """
        Gets a SQLAlchemy session, and wraps it in an ORMSession.
        """
        session = scoped_session(self.sessionmaker, **kwargs)
        if test:
            try:
                assert session.execute("SELECT 1").fetchone()[0] == 1
            except:
                if retry:
                    self.sessionmaker = sessionmaker(self.engine)
                    return self.session(test=True, retry=False, **kwargs)
                else:
                    raise
        return ORMSession(self, session, **kwargs)

    def _remove_if_exists(self, tablename: str) -> None:
        """
        Removes an existing table if it exists - only called when `force`ing.
        """
        metadata = sqlalchemy.MetaData(self.engine)
        try:
            table = sqlalchemy.Table(tablename, metadata, autoload=True)
            logger.info("Removing existing table {0}.".format(tablename))
            table.drop()
        except sqlalchemy.exc.NoSuchTableError:
            pass

    def __getattr__(self, name: str) -> Type:
        if name in self.models:
            return self.models[name]  # type: ignore
        raise AttributeError(f"Model {name} not defined.")

    def extend(
        self,
        name: str,
        clsdict: Dict[str, Any],
        cls: Type = ORMObject,
        force: bool = False,
        create: bool = True,
    ) -> Type:
        """
        Extends the underlying ORM layer with the object itself. Likely won't be
        called directly by implementing applications. If the ORM was instantiated
        with an ORMObjectBase base class which had declared subclasses at the time
        of instantiation, those subclasses will be automatically bound to the underlying
        layer. This is only necessary to be used *after* initial instantiation. This
        is most useful for mix-ins that need an ORM model.
        """
        if "__tablename__" not in clsdict:
            clsdict["__tablename__"] = name
        clsdict["__schema__"] = {**clsdict}
        clsdict["__orm__"] = self
        if "__table_args__" not in clsdict:
            clsdict["__table_args__"] = tuple()
        clsdict["__table_args__"] += ({"extend_existing": True},)

        if name not in self.models:
            if force:
                self._remove_if_exists(clsdict["__tablename__"])
            logger.debug(f"Adding {name} to models")
            try:
                declared = type(
                    "{0}Declarative".format(name), (self.declarative_base, cls), clsdict
                )
            except Exception as ex:
                existing_table = sqlalchemy.Table(
                    clsdict["__tablename__"],
                    self.declarative_base.metadata,
                    autoload=True,
                )
                existing_clsdict = dict(
                    [
                        (key, clsdict[key])
                        for key in clsdict
                        if key not in ["__tablename__", "__table_args__"]
                        and not isinstance(clsdict[key], sqlalchemy.Column)
                    ]
                )
                existing_clsdict["__table__"] = existing_table
                try:
                    declared = type(
                        "{0}Declarative".format(name),
                        (self.declarative_base, cls),
                        existing_clsdict,
                    )
                except Exception as ex2:
                    logger.error(
                        "Couldn't get existing metadata table for class {0}".format(cls)
                    )
                    logger.error(ex2)
                    raise ex
            self.models[name] = declared
        else:
            declared = self.models[name]
        if create:
            self.declarative_base.metadata.create_all()
        return declared

    def extend_base(
        self,
        cls: Type[ORMObjectBase],
        force: bool = False,
        create: bool = True,
    ) -> None:
        """
        Takes an ORMObjectBase and iterates through any subclasses that are ORM models.
        """
        for subcls in cls._declared_classes():
            self.extend(
                subcls.__name__, subcls._declared_dict(self), force=force, create=False
            )
        self.bases.append(cls)
        if create:
            self.declarative_base.metadata.create_all()

    def migrate(self, force: bool = False) -> None:
        """
        After extending the ORM with all necessary classes and bases, calling migrate()
        will pass the ORMObjects to the sqlalchemy metadata layer and create the tables.
        """
        logger.debug(
            "Migrate called, executing on {0} base classes".format(len(self.bases))
        )
        for object_base in self.bases:
            logger.debug(f"Migrating from object base {object_base}")
            for cls in object_base._declared_classes():
                logger.debug(f"Migrating class {cls}")
                self.extend(
                    cls.__name__, cls._declared_dict(self), force=force, create=False
                )
        self.declarative_base.metadata.create_all()

    def dispose(self) -> None:
        """
        Disposes (closes) all connections.
        """
        self.engine.dispose()


class ORMBuilder(ORM):
    """
    A simple helper for building an ORM programmatically.
    """

    def __init__(
        self, engine_type: str, engine_kwargs: Dict[str, Any] = {}, **kwargs: Any
    ):
        self.engine_type = engine_type
        self.engine_kwargs = engine_kwargs
        self.init_kwargs = kwargs
        super(ORMBuilder, self).__init__(
            EngineFactory.singleton(self.engine_type, **self.engine_kwargs),
            **self.init_kwargs,
        )

    def duplicate(self) -> ORMBuilder:
        """
        Creates another instance of the ORM. Importantly, this creates a new engine connection,
        so this should be called after a fork() to get a new connection in the other thread.
        """
        logger.debug(
            f"Duplicating ORM of type {self.engine_type}, engine parameters {self.engine_kwargs}, initialization parameters {self.init_kwargs}"
        )
        return ORMBuilder(self.engine_type, self.engine_kwargs, **self.init_kwargs)

    @staticmethod
    def from_configuration(
        configuration: APIConfiguration, prefix: Optional[str] = "orm"
    ) -> ORMBuilder:
        """
        Uses an APIConfiguration object to get the initialization parameters for an ORM.
        """
        db_type = configuration["{0}.type".format(prefix)]
        db_kwargs = configuration["{0}.connection".format(prefix)]

        cipher_kwargs = configuration.get("{0}.cipher".format(prefix), {})
        cipher = AESCipher(**cipher_kwargs)

        return ORMBuilder(
            db_type,
            db_kwargs,
            migrate=configuration.get("{0}.migrate".format(prefix), False),
            force=configuration.get("{0}.force".format(prefix), False),
            base=configuration.get("{0}.base".format(prefix), ORMObjectBase),
            cipher=cipher,
        )

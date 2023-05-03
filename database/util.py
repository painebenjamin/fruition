import sqlalchemy.types

from sqlalchemy.sql.type_api import TypeEngine as SQLAlchemyType

from typing import Type, Any, Iterator
from pandas import Timestamp
from numpy import int64, float64
from datetime import datetime, date, time, timedelta
from decimal import Decimal


def sqlalchemy_type_from_python_type(python_type: Type) -> SQLAlchemyType:
    try:
        return {
            int: sqlalchemy.types.Integer,
            int64: sqlalchemy.types.Integer,
            bool: sqlalchemy.types.Boolean,
            float: sqlalchemy.types.Float,
            float64: sqlalchemy.types.Float,
            Decimal: sqlalchemy.types.Float,
            str: sqlalchemy.types.String,
            list: sqlalchemy.types.ARRAY,
            dict: sqlalchemy.types.JSON,
            datetime: sqlalchemy.types.DateTime,
            date: sqlalchemy.types.Date,
            time: sqlalchemy.types.Time,
            timedelta: sqlalchemy.types.Interval,
        }[python_type]
    except KeyError:
        raise ValueError("Can't convert type {0}.".format(python_type.__name__))


def sqlalchemy_type_from_python_value(python_value: Any) -> SQLAlchemyType:
    python_type = type(python_value)
    if python_type in [int, int64]:
        return (
            sqlalchemy.types.BigInteger
            if python_value >= 2**32
            else sqlalchemy.types.Integer
        )
    elif python_type is Timestamp:
        return sqlalchemy.types.DateTime
    return sqlalchemy_type_from_python_type(python_type)


class RowProxy(dict):
    """
    A small "proxy" for a row, which mimics the behavior.

    Notably, rows have the .keys() function that behaves exactly like a dictionary, but when iterating on a row, it gives you the **values**, not the keys as a dict would.

    >>> from pibble.database.util import RowProxy
    >>> rp = RowProxy(foo = "bar", bar = "baz")
    >>> [r for r in rp]
    ['bar', 'baz']

    :param kwargs dict: Any number of keywords arguments.
    """

    def __iter__(self) -> Iterator[Any]:
        return iter(self.values())


def row_to_dict(row: Any) -> dict:
    """
    Turns a row into a dictionary. See :class:pibble.database.util.RowProxy for why this is necessary.

    >>> from pibble.database.util import RowProxy, row_to_dict
    >>> row_to_dict(RowProxy(foo = "bar", bar = "baz"))
    {'foo': 'bar', 'bar': 'baz'}

    :param row row: The row object.
    :returns dict: The row, now in dictionary form.
    """
    if hasattr(row, "__table__"):
        return dict(
            [
                (column.name, str(getattr(row, column.name)))
                for column in row.__table__.columns
            ]
        )
    return dict(zip(row.keys(), row))

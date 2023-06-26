from __future__ import annotations

import re
import logging

from sqlalchemy import and_, or_, not_
from sqlalchemy.orm.query import Query
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

from pibble.api.exceptions import (
    BadRequestError,
    ConfigurationError,
    NotFoundError,
    PermissionError,
)
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.api.server.webservice.orm import ORMWebServiceAPIServer
from pibble.database.orm import ORMSession, ORMObjectBase
from pibble.util.log import logger
from pibble.util.strings import Serializer, pretty_print, pretty_print_sentence

from webob import Request, Response

from typing import Any, Callable, List

DEFAULT_LIMIT = 100


class RESTExtensionServerBase(ORMWebServiceAPIServer):
    """
    Using the JSON web service and ORM extensions, provide a configurable
    interface to create HTTP handlers that follow JSON-REST standards.

    This requires the use of an ORM, so the configuration for the ORMBuilder
    is also required. See `pibble.database.orm.ORMBuilder`.

    Optional configuration:
      - `rest.root` - The root of handlers. Defaults to /rest.
    Required configuration:
      - `rest.scopes` - The scopes to build handlers for. This is
        an array of:
          class:  required. Either a string (matching the ORM object name, case sensitive)
                  or extension of ORMObjectBase.
          root:   optional. Defaults to cls.__name__. This is the start of the handler after
                  `rest.root`, e.g., /rest/{root}.
          parent: optional. When referring to many-to-one relationship hierarchies, this
                  would correspond to the primary key(s) identifying a parent object.
          scope:  optional, sort of. This should be passed in to make a complete REST configuration,
                  and should correspond to the primary key of the object. This is necessary
                  for the REST server to conform to standards, as this creates unique endpoints
                  for all objects (and enables the use of DELETE and PUT endpoints, as well as
                  GET on a single object.)
    """

    handlers = WebServiceAPIHandlerRegistry()

    def paginate_object(
        self,
        request: Request,
        response: Response,
        session: ORMSession,
        obj: ORMObjectBase,
        **handler_filters: Any,
    ) -> tuple[Query, Query]:
        """
        Corresponds to the GET handler - builds a select and count query for
        the requested resource.

        The count query, in this instance, is really just the main query without
        pagination. This should be used to call .count() upon to get the length of
        the result, for proper interface pagination. This should be reasonably performant,
        but will have some serious issues scaling into the millions of rows.

        :param request webob.Request: The request object from the base server.
        :param response webob.Response: The response object from the base server.
        :param session pibble.database.orm.ORMSession: An ORMSession as returned by self.orm.session(). This could technically also be a sqlalchemy.Session, though in such a case, search is disabled.
        :param obj pibble.database.orm.ORMObjectBase: The object to search for.
        :param handler_filters dict: A dictionary of <column, value> that the handler wants to always filter results down by.
        :returns tuple<Query, Query>: The prepared queries for (results, count).
        """

        limit = request.GET.get("limit", DEFAULT_LIMIT)
        offset = request.GET.get("offset", 0)
        sort = request.GET.getall("sort")
        filters = request.GET.getall("filter")
        ilikes = request.GET.getall("ilike")

        query = session.query(obj)

        if sort:
            for sort_column in sort:
                if ":" in sort_column:
                    column, direction = sort_column.split(":")
                else:
                    column = sort_column
                    direction = "asc"
                query = query.order_by(getattr(getattr(obj, column), direction)())

        def apply_filters(
            query: Query,
            obj: ORMObjectBase,
            column: str,
            value: str,
            filter_func: Callable[[QueryableAttribute, str], Any],
        ) -> Query:
            or_split = column.split("|")
            and_split = column.split("+")
            value_or_split = value.split("|")

            def apply_column(column: str) -> ColumnElement:
                negate = False
                if column[0] == "!":
                    column = column[1:]
                    negate = True
                if len(value_or_split) > 1:
                    condition = or_(
                        *[
                            filter_func(
                                getattr(obj, column), Serializer.deserialize(value_part)
                            )
                            for value_part in value_or_split
                        ]
                    )
                else:
                    condition = filter_func(
                        getattr(obj, column), Serializer.deserialize(value)
                    )
                if negate:
                    return not_(condition)
                return condition

            if len(or_split) > 1:
                query = query.filter(
                    or_(*[apply_column(column_part) for column_part in or_split])
                )
            elif len(and_split) > 1:
                query = query.filter(
                    and_(*[apply_column(column_part) for column_part in and_split])
                )
            else:
                query = query.filter(apply_column(column))

            return query

        if ilikes:
            conditions = []
            for ilike_string in ilikes:
                column, _, value = ilike_string.partition(":")
                conditions.append(
                    getattr(obj, column).ilike("%{:s}%".format(value.lower()))
                )
            query = query.filter(or_(*conditions))

        if filters:
            for filter_string in filters:
                column, _, value = filter_string.partition(":")
                query = apply_filters(
                    query, obj, column, value, lambda column, value: column == value
                )

        for column in handler_filters:
            query = apply_filters(
                query,
                obj,
                column,
                handler_filters[column],
                lambda column, value: column == value,
            )

        count = query

        if limit is not None and int(limit) > 0:
            query = query.limit(limit)

        if offset:
            query = query.offset(offset)

        return query, count

    @classmethod
    def get_scoped_handler(
        cls,
        handler_classname: str,
        handler_root: str,
        handler_parent: List[str],
        handler_scope: str,
        **scope: Any,
    ) -> Callable[[RESTExtensionServerBase, Request, Response], List[ORMObjectBase]]:
        """
        Returns a rest handler that has been properly handler_scoped to be callable when registering
        with a handler registry.

        See the handler_root class for descriptions, as they correspond to the configuration values.
        """

        def rest_handler(
            self: RESTExtensionServerBase,
            request: Request,
            response: Response,
            **kwargs: Any,
        ) -> List[ORMObjectBase]:
            method = request.method.upper()

            if hasattr(self, "database"):
                session = self.database
                autoclose = False
            elif not hasattr(self, "orm"):
                raise ConfigurationError(
                    "No ORM present, cannot operate REST server endpoint."
                )
            else:
                session = self.orm.session()
                autoclose = True

            result = []

            orm_object = getattr(self.orm, handler_classname)

            hidden_columns = getattr(orm_object, "__hidden_columns__", [])
            if hidden_columns is None:
                hidden_columns = []

            hidden_relationships = getattr(orm_object, "__hidden_relationships__", [])
            if hidden_relationships is None:
                hidden_relationships = []

            filter_kwargs = {}
            for key in kwargs:
                if kwargs[key] is not None and kwargs[key] != "":
                    filter_kwargs[key] = str(kwargs[key])

            input_dict = {}
            if method in ["POST", "PUT", "PATCH"]:
                input_dict = request.parsed

            for key in input_dict:
                if key in hidden_columns:
                    raise PermissionError(
                        f"Field '{key}' cannot be set through this API."
                    )
                elif not hasattr(orm_object, key):
                    raise BadRequestError(f"Unknown field '{key}'.")

            if method == "GET":
                query, count = self.paginate_object(
                    request, response, session, orm_object, **filter_kwargs
                )
                result = query.all()
                length = count.count()
                if hasattr(response, "meta"):
                    response.meta.update({"count": length})
                else:
                    setattr(response, "meta", {"count": length})
                if handler_scope in kwargs and kwargs[handler_scope] and length == 0:
                    raise NotFoundError(
                        "No {0} found with {1}".format(
                            handler_classname, pretty_print(**kwargs)
                        )
                    )
            elif method == "POST":
                result = orm_object(**{**request.parsed, **filter_kwargs})
                session.add(result)
                session.commit()
            elif method in ["PUT", "PATCH"]:
                if any([not kwargs[k] for k in kwargs]):
                    raise BadRequestError("Cannot PUT without scope.")
                result = (
                    session.query(orm_object).filter_by(**filter_kwargs).one_or_none()
                )
                if not result:
                    if method == "PATCH":
                        raise NotFoundError(
                            "No {0} found with {1}".format(
                                handler_classname, pretty_print(**kwargs)
                            )
                        )
                    logger.debug("REST PUT handler creating new object.")
                    result = orm_object(**{**request.parsed, **filter_kwargs})
                    session.add(result)
                else:
                    logger.debug(
                        "REST PUT/PATCH handler modifying existing object, will set variable(s) {0}".format(
                            pretty_print_sentence(*[k for k in request.parsed.keys()])
                        )
                    )
                    for key in request.parsed:
                        setattr(result, key, request.parsed[key])
                session.commit()
            elif method == "DELETE":
                if any([not kwargs[k] for k in kwargs]):
                    raise BadRequestError("Cannot DELETE without handler_scope.")
                result = (
                    session.query(orm_object).filter_by(**filter_kwargs).one_or_none()
                )
                if not result:
                    raise NotFoundError(
                        f"No {handler_classname:s} found with parent scope {handler_parent:s} and scope {handler_scope:s}."
                    )
                else:
                    session.delete(result)
                    session.commit()
                    result = []
            if autoclose:
                logger.debug("No middleware session, closing handler session.")
                session.close()
            logger.debug(
                "Responding to {0} at {1} with {2}".format(
                    method, request.path, type(result)
                )
            )
            return result

        return rest_handler

    def bind_rest_handler(
        self,
        handler_classname: str,
        handler_methods: List[str],
        handler_root: str,
        handler_parent: List[str],
        handler_scope: str,
        handler_regex: str,
        **scope: Any,
    ) -> None:
        """
        Builds the scoped handler, then binds it to the handler registry.

        :param handler_classname str: The classname of the object to manipulate with handlers.
        :param handler_root str: The root of the handler.
        :param handler_parent str: Optional - the parent of the handler.
        :param handler_scope str: The scope (primary key) of the object to be manipulated.
        :param handler_regex str: The regular expression to use for the URL.
        :param scope dict: Any other parameters, likely to be used by extending classes.
        """

        logger.debug(
            f"Building scoped handler with class {handler_classname}, root {handler_root}, parent {handler_parent}, scope {handler_scope}"
        )
        scoped_handler = self.get_scoped_handler(
            handler_classname, handler_root, handler_parent, handler_scope, **scope
        )
        scoped_handler.__name__ = f"{handler_classname}RESTHandler"
        RESTExtensionServerBase.handlers.methods(*handler_methods)(scoped_handler)
        RESTExtensionServerBase.handlers.path(re.compile(handler_regex))(scoped_handler)
        RESTExtensionServerBase.handlers.format()(scoped_handler)

    def on_configure(self) -> None:
        """
        When configuration fires, bind the handlers.
        """

        if "rest" not in self.configuration:
            logger.error(
                "REST server configuration missing. No handlers will be registered."
            )
        else:
            root = self.configuration.get("rest.root", "/rest")
            scopes = self.configuration.get("rest.scopes", [])
            if not scopes:
                logger.error(
                    "REST server scope configuration missing. No handlers will be registered."
                )
            logger.debug("REST server adding {0} scoped handlers".format(len(scopes)))
            for scope in scopes:
                handler_classname = scope["class"]
                handler_scope = scope["scope"]
                if isinstance(handler_classname, type):
                    handler_classname = handler_classname.__name__
                handler_root = scope.get("root", handler_classname)
                handler_parent = scope.get("parent", [])
                handler_methods = scope.get(
                    "methods", ["GET", "PUT", "PATCH", "POST", "DELETE"]
                )

                if not isinstance(handler_parent, list):
                    handler_parent = [handler_parent]

                handler_regex = f"^{root:s}/{handler_root:s}"

                for handler_parent_part in handler_parent:
                    handler_regex += f"/(?P<{handler_parent_part:s}>[^\/]+)"
                handler_regex += f"(/(?P<{handler_scope:s}>[^\/]+))?$"

                if logger.isEnabledFor(logging.DEBUG):
                    handler_parent_string = ",".join(handler_parent)
                    logger.debug(
                        f"REST server registering scoped handler for class {handler_classname}, handler root '{handler_root}', parent(s) '{handler_parent_string}', scope(s) '{handler_scope}', regex {handler_regex}"
                    )

                self.bind_rest_handler(
                    handler_classname,
                    handler_methods,
                    handler_root,
                    handler_parent,
                    handler_scope,
                    handler_regex,
                    **scope,
                )

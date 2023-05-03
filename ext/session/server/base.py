import datetime

from typing import Any, Optional, cast

from webob import Request, Response

from pibble.util.strings import get_uuid
from pibble.database.orm import ORMSession, ORM
from pibble.api.server.webservice.orm import ORMWebServiceAPIServer
from pibble.api.exceptions import ConfigurationError
from pibble.ext.session.database import SessionExtensionObjectBase
from pibble.ext.session.database.session import SessionDatum


class NoDefaultProvided:
    pass


class SessionHelper:
    """
    A single wrapper around the ORM to make accessing data easier.
    """

    def __init__(self, database: ORMSession, orm: ORM, cookie: str):
        self.database = database
        self.orm = orm
        self.cookie = cookie

    def get(self, key: str, default: Any = NoDefaultProvided) -> Any:
        try:
            return self[key]
        except KeyError:
            if default is NoDefaultProvided:
                raise
            return default

    def _get_session_datum(self, key: str) -> Optional[SessionDatum]:
        """
        Gets the underlying session datum
        """
        result = (
            self.database.query(self.orm.SessionDatum)
            .filter(
                self.orm.SessionDatum.session_token == self.cookie,
                self.orm.SessionDatum.key == key,
            )
            .one_or_none()
        )
        if result is None:
            return None
        return cast(SessionDatum, result)

    def __getitem__(self, key: str) -> Any:
        result = self._get_session_datum(key)
        if not result:
            raise KeyError(key)
        return result.value

    def __setitem__(self, key: str, value: Any) -> None:
        result = self._get_session_datum(key)
        if not result:
            result = self.orm.SessionDatum(
                session_token=self.cookie, key=key, value=value
            )
            self.database.add(result)
            self.database.commit()
        else:
            result.value = value
            self.database.commit()


class SessionExtensionServerBase(ORMWebServiceAPIServer):
    """
    An extension that makes for easy persistent sessions with a server.

    Usage is simple - we assign 'session' to the 'request' object so that we can access it during
    handlers. The session is distinguished by the user token, which is set via cookie.

    Example usage::
        class MySessionServer(SessionExtensionServerBase):
            handlers = WebServiceAPIHandlerRegistry()

            @handlers.methods("GET")
            @handlers.path("^/?$")
            def get_name(self, request: Request, response: Response) -> None:
                try:
                    response.text = request.session["name"]
                except KeyError:
                    raise NotFoundError("You haven't told me your name yet!")

            @handlers.methods("GET")
            @handlers.path("^/(?P<name>[\w]+)$")
            def set_name(self, request: Request, response: Response, name: str) -> None:
                request.session["name"] = name
                response.status_code = 301
                response.location = "/"

    """

    def parse(
        self, request: Optional[Request] = None, response: Optional[Response] = None
    ) -> None:
        if request is not None and not hasattr(request, "session"):
            cookie = request.cookies.get(self.session_cookie_name, None)

            if cookie:
                result = (
                    self.database.query(self.orm.Session)
                    .filter(self.orm.Session.token == cookie)
                    .one_or_none()
                )
                if not result:
                    cookie = None

            if not cookie:
                cookie = get_uuid()
                self.database.add(self.orm.Session(token=cookie))
                self.database.commit()
                if response is not None:
                    response.set_cookie(
                        self.session_cookie_name,
                        cookie,
                        secure=self.configuration.get("server.secure", False),
                        domain=self.configuration.get("server.domain", None),
                        samesite="strict"
                        if self.configuration.get("server.secure", False)
                        else None,
                        expires=datetime.timedelta(
                            days=self.configuration.get("session.days", 30)
                        ),
                    )
            setattr(request, "session", SessionHelper(self.database, self.orm, cookie))

    def on_configure(self) -> None:
        if not hasattr(self, "orm"):
            raise ConfigurationError("No ORM configured, cannot use session extension.")
        self.orm.extend_base(
            SessionExtensionObjectBase,
            force=self.configuration.get("orm.force", False),
            create=self.configuration.get("orm.create", True),
        )
        self.session_cookie_name = self.configuration.get(
            "session.cookie", "pibble_session"
        )

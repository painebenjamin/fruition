from __future__ import annotations

import datetime

from sqlalchemy import func

from webob import Request, Response

from typing import Optional, Callable, Any, Type, Union, cast

from sqlalchemy.engine.result import Result

from pibble.util.log import logger
from pibble.util.encryption import Password
from pibble.util.strings import get_uuid
from pibble.api.exceptions import (
    AuthenticationError,
    PermissionError,
    ConfigurationError,
)
from pibble.api.server.base import APIServerBase
from pibble.api.server.webservice.handler import (
    WebServiceAPIHandlerRegistry,
    WebServiceAPIHandler,
)
from pibble.api.server.webservice.template import (
    TemplateServerHandlerRegistry,
    TemplateHandler,
    TemplateServer,
)
from pibble.api.server.webservice.orm import ORMWebServiceAPIServer
from pibble.ext.user.database.base import UserExtensionObjectBase
from pibble.ext.user.database.user import User
from pibble.ext.user.database.permission import Permission
from pibble.ext.user.database.authentication import AuthenticationToken

DEFAULT_TOKEN_TYPE = "Bearer"


class UserExtensionHandler(WebServiceAPIHandler):
    def __init__(
        self,
        fn: Callable,
        secured: bool = False,
        object_name: Optional[str] = None,
        action: Optional[str] = None,
        secondary_action: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super(UserExtensionHandler, self).__init__(fn, **kwargs)
        self.secured = secured
        self.object_name = object_name
        self.action = action
        self.secondary_action = secondary_action

    def _check_permissions(
        self, server: UserExtensionServerBase, request: Request, **kwargs: Any
    ) -> None:
        if getattr(self, "secured", False):
            if not getattr(request, "token", None):
                raise AuthenticationError("Invalid or no credentials supplied.")

            if self.object_name is not None and self.action is not None:
                server.assert_user_permission(
                    request,
                    self.object_name,
                    self.action,
                    secondary_action=self.secondary_action,
                    **kwargs,
                )

    def __call__(
        self,
        server: APIServerBase,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if isinstance(server, UserExtensionServerBase):
            self._check_permissions(server, request, **kwargs)
        return self.function(server, request, response, *args, **kwargs)


class UserExtensionHandlerRegistry(WebServiceAPIHandlerRegistry):
    def secured(
        self,
        object_name: Optional[Union[str, Type]] = None,
        action: Optional[str] = None,
        secondary_action: Optional[str] = None,
    ) -> Callable[[Callable], Callable]:
        if type(object_name) is type:
            object_name = object_name.__name__

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(
                fn,
                secured=True,
                object_name=cast(str, object_name),
                action=action,
                secondary_action=secondary_action,
            )
            return fn

        return wrap

    def create_handler(self, fn: Callable, **kwargs: Any) -> UserExtensionHandler:
        handler = UserExtensionHandler(fn, **kwargs)
        self.handlers.append(handler)
        return handler


class UserExtensionTemplateHandler(TemplateHandler, UserExtensionHandler):
    def __call__(
        self,
        server: APIServerBase,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if isinstance(server, UserExtensionServerBase):
            self._check_permissions(server, request, **kwargs)
        return TemplateHandler.__call__(
            self, server, request, response, *args, **kwargs
        )


class UserExtensionTemplateHandlerRegistry(
    TemplateServerHandlerRegistry, UserExtensionHandlerRegistry
):
    def create_handler(
        self, fn: Callable, **kwargs: Any
    ) -> UserExtensionTemplateHandler:
        handler = UserExtensionTemplateHandler(fn, **kwargs)
        self.handlers.append(handler)
        return handler


class UserExtensionServerBase(ORMWebServiceAPIServer):
    def parse(
        self, request: Optional[Request] = None, response: Optional[Response] = None
    ) -> None:
        """
        When a request comes in, parse for authorization and look for a valid token/session.
        """

        authorization = (
            None if request is None else request.headers.get("Authorization", None)
        )

        if authorization:
            token_type, _, token = authorization.partition(" ")

            if token_type != self.token_type:
                logger.warning(
                    "Authorization provided is of wrong type '{0}'.".format(
                        DEFAULT_TOKEN_TYPE
                    )
                )
            else:
                token = (
                    self.database.query(self.orm.AuthenticationToken)
                    .filter(self.orm.AuthenticationToken.access_token == token)
                    .one_or_none()
                )

                if not token:
                    logger.warning(
                        "Authorization provided does not match to an authentication token."
                    )
                elif request is not None:
                    setattr(request, "token", token)

    def find_permissions_by_user(
        self, user: User, object_name: str, **kwargs: Any
    ) -> Result:
        """
        Finds permissions by a user.

        :param user pibble.ext.server.user.database.user.User: The user object to find permissions on.
        :param object_name str: The object to find permissions for.
        :params kwargs dict: All other filters. These should be columns on the Permission object.
        :returns list: All permissions tied to this user that matched the arguments.
        """

        global_permission_ids = self.database.query(
            self.orm.GlobalPermission.permission_id.label("permission_id")
        )

        user_permission_ids = (
            self.database.query(
                self.orm.UserPermission.permission_id.label("permission_id")
            )
            .join(self.orm.User)
            .filter(self.orm.User.id == user.id)
        )

        user_permission_group_permission_ids = (
            self.database.query(
                self.orm.PermissionGroupPermission.permission_id.label("permission_id")
            )
            .join(self.orm.PermissionGroup)
            .join(self.orm.UserPermissionGroup)
            .filter(self.orm.UserPermissionGroup.user_id == user.id)
        )

        user_distinct = (
            global_permission_ids.union(user_permission_ids)
            .union(user_permission_group_permission_ids)
            .distinct()
        )

        permission_query = (
            self.database.query(self.orm.Permission)
            .join(user_distinct.cte(name="user_permission_ids"))
            .filter(self.orm.Permission.object_name == object_name)
        )

        for key in kwargs:
            permission_query = permission_query.filter(
                getattr(self.orm.Permission, key) == kwargs[key]
            )

        return permission_query.all()

    def check_user_permission(
        self,
        user: User,
        subject: Any,
        action: str,
        secondary_action: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """
        Check a user's permission to perform an individual action.

        :param user pibble.ext.server.user.database.user.User: The user object to find permissions on.
        :param object_name str: The object being acted against.
        :param action str: The action being performed.
        :param secondary_action str: The secondary action being performed, if any.
        :param kwargs dict: All values passed into the check_permission function. See it for details.
        :returns boolean: Whether or not a user has permission to do the requested scoped action.
        """

        if user.superuser:
            return True

        object_name = getattr(subject, "__name__", str(subject))

        logger.debug(
            "Checking permissions on user {0} for object {1}, action {2}, secondary action {3}".format(
                user.username, object_name, action, secondary_action
            )
        )

        for permission in self.find_permissions_by_user(
            user, object_name, action=action, secondary_action=secondary_action
        ):
            if self.check_permission(user, permission, **kwargs):
                return True
        return False

    def assert_user_permission(
        self,
        request: Request,
        object_name: str,
        action: str,
        secondary_action: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Similar to `check_user_permission`, this just calls that function and raises the appropriate
        PermissionError. Meant to be called by handlers.

        :param request webob.Request: The request object from the handler.
        :param object_name str: The object being acted against.
        :param action str: The action being performed.
        :param secondary_action str: The secondary action being performed, if any.
        :param kwargs dict: All values passed into the check_permission function. See it for details.
        """

        if not self.check_user_permission(
            request.token.user,
            object_name,
            action,
            secondary_action=secondary_action,
            **kwargs,
        ):
            raise PermissionError(
                "User {0} is not authorized to {1} on {2}.".format(
                    request.token.user.username,
                    action
                    if not secondary_action
                    else "{0} - {1}".format(action, secondary_action),
                    object_name,
                )
            )

    def check_permission(
        self, user: User, permission: Permission, **kwargs: Any
    ) -> bool:
        """
        Checks a permission to see if it applies to the scope passed in.

        :param user pibble.ext.server.user.database.user.User: The user object to check the permission against.
        :param permission pibble.ext.server.user.database.permission.Permission: The permission object to check against.
        :param kwargs: The values passed in for explicit scopes.
        """

        logger.debug(
            "Checking permission with scope {0}. Permission is\r\n{1}".format(
                kwargs, permission.format()
            )
        )

        if permission.scope_type == "explicit":
            attribute = permission.explicit_scope_attribute
            value = permission.explicit_scope_value
            if attribute is None:
                logger.debug("Explicit permission granted.")
                return True
            else:
                local_value = kwargs.get(attribute, None)
                if local_value is None and value is not None or local_value != value:
                    logger.debug("Explicit value failed.")
                    return False
                return True
        else:
            permission_object_name = permission.object_name
            inherited_object_name = permission.inherited_scope_object_name
            inherited_scope_source_attribute = (
                permission.inherited_scope_source_attribute
            )
            inherited_scope_action = permission.inherited_scope_action
            inherited_scope_secondary_action = (
                permission.inherited_scope_secondary_action
            )
            inherited_scope_target_attribute = (
                permission.inherited_scope_target_attribute
            )
            inherited_scope_passed_value = kwargs.get(
                inherited_scope_source_attribute, None
            )

            inherited_action = permission.action
            inherited_secondary_action = permission.secondary_action

            if inherited_scope_action:
                inherited_action = inherited_scope_action
            if inherited_scope_secondary_action:
                inherited_secondary_action = inherited_scope_secondary_action

            logger.debug(
                f"Inherited permission recursing on {inherited_object_name} with action = {inherited_action}, secondary_action = {inherited_secondary_action}, {inherited_scope_target_attribute} = {inherited_scope_passed_value} (maps to {permission_object_name}.{inherited_scope_source_attribute})"
            )

            return self.check_user_permission(
                user,
                inherited_object_name,
                inherited_action,
                inherited_secondary_action,
                **{inherited_scope_target_attribute: inherited_scope_passed_value},
            )

    def migrate_permissions(self) -> None:
        with self.orm.session() as session:
            for permission in self.configuration["user.permissions"]:
                permission = {**permission}
                actions = permission.pop("action")
                if not isinstance(actions, list):
                    actions = [actions]
                is_global = permission.pop("global", False)
                group = permission.pop("group", None)

                for action in actions:
                    existing = (
                        session.query(self.orm.Permission)
                        .filter(self.orm.Permission.action == action)
                        .filter_by(**permission)
                        .one_or_none()
                    )
                    if not existing:
                        existing = self.orm.Permission(action=action, **permission)
                        session.add(existing)
                        session.commit()
                    if is_global:
                        existing_global = (
                            session.query(self.orm.GlobalPermission)
                            .filter(
                                self.orm.GlobalPermission.permission_id == existing.id
                            )
                            .one_or_none()
                        )
                        if not existing_global:
                            session.add(
                                self.orm.GlobalPermission(permission_id=existing.id)
                            )
                    if group:
                        existing_group = (
                            session.query(self.orm.PermissionGroup)
                            .filter(self.orm.PermissionGroup.label == group)
                            .one_or_none()
                        )
                        if not existing_group:
                            existing_group = self.orm.PermissionGroup(label=group)
                            session.add(existing_group)
                            session.commit()
                        existing_group_permission = (
                            session.query(self.orm.PermissionGroupPermission)
                            .filter(
                                self.orm.PermissionGroupPermission.permission_id
                                == existing.id
                            )
                            .filter(
                                self.orm.PermissionGroupPermission.group_id
                                == existing_group.id
                            )
                            .one_or_none()
                        )
                        if not existing_group_permission:
                            session.add(
                                self.orm.PermissionGroupPermission(
                                    permission_id=existing.id,
                                    group_id=existing_group.id,
                                )
                            )
            session.commit()

    def migrate_users(self) -> None:
        with self.orm.session() as session:
            for user in self.configuration["user.users"]:
                user = {**user}
                username = user.pop("username")
                password = user.pop("password", None)
                permissions = user.pop("permissions", [])
                groups = user.pop("groups", [])

                existing = (
                    session.query(self.orm.User)
                    .filter(func.lower(self.orm.User.username) == username.lower())
                    .one_or_none()
                )

                if existing:
                    for key in user:
                        if key:
                            setattr(existing, key, user[key])
                else:
                    if password:
                        password = Password.hash(password)
                    existing = self.orm.User(
                        password=password, username=username, **user
                    )
                    session.add(existing)

                for permission in permissions:
                    pass

                for group in groups:
                    group = (
                        session.query(self.orm.PermissionGroup)
                        .filter(self.orm.PermissionGroup.label == group)
                        .one()
                    )
                    user_group = (
                        session.query(self.orm.UserPermissionGroup)
                        .filter(self.orm.UserPermissionGroup.user_id == existing.id)
                        .filter(self.orm.UserPermissionGroup.group_id == group.id)
                        .one_or_none()
                    )
                    if not user_group:
                        session.add(
                            self.orm.UserPermissionGroup(
                                user_id=existing.id, group_id=group.id
                            )
                        )
            session.commit()

    def on_configure(self) -> None:
        """
        When configuration fires, make sure ORM has user objects migrated.
        """
        self.token_type = self.configuration.get("user.token.type", DEFAULT_TOKEN_TYPE)
        if not hasattr(self, "orm"):
            raise ConfigurationError("No ORM configured, cannot use user extension.")
        self.orm.extend_base(
            UserExtensionObjectBase,
            force=self.configuration.get("orm.force", False),
            create=self.configuration.get("orm.create", True),
        )
        if "user.permissions" in self.configuration:
            self.migrate_permissions()
        if "user.users" in self.configuration:
            self.migrate_users()

    def logout(self, request: Request, response: Response) -> None:
        """
        The main logout handler.
        """
        if hasattr(request, "token"):
            self.database.delete(request.token)
            self.database.commit()
        else:
            raise AuthenticationError("Not logged in.")

    def login(self, request: Request, response: Response) -> AuthenticationToken:
        """
        The main login handler.
        """
        if hasattr(request, "parsed") and request.parsed:
            if "username" not in request.parsed or "password" not in request.parsed:
                raise AuthenticationError("Missing username or password.")
            else:
                username = request.parsed["username"]
                password = request.parsed["password"]
        elif "username" not in request.POST or "password" not in request.POST:
            raise AuthenticationError("Missing username or password.")
        else:
            username = request.POST["username"]
            password = request.POST["password"]

        user = (
            self.database.query(self.orm.User)
            .filter(func.lower(self.orm.User.username) == username.lower())
            .one_or_none()
        )
        if not user:
            raise AuthenticationError("Incorrect username or password.")
        if not user.password:
            raise AuthenticationError(
                "Account for user '{0}' not activated.".format(username)
            )
        if not Password.verify(user.password, password):
            raise AuthenticationError("Incorrect username or password.")

        token = self.orm.AuthenticationToken(
            access_token=get_uuid(),
            refresh_token=get_uuid(),
            token_type=self.token_type,
            user_id=user.id,
        )

        user.last_login = datetime.datetime.now()

        self.database.add(token)
        self.database.commit()

        return cast(AuthenticationToken, token)

    def bypass_login(self, request: Request, response: Response) -> AuthenticationToken:
        """
        Generates a 'noauth' authentication token.
        """
        user = (
            self.database.query(self.orm.User)
            .filter(self.orm.User.id == 0)
            .one_or_none()
        )
        if not user:
            user = self.orm.User(id=0, username="noauth", superuser=True)
            self.database.add(user)
            self.database.commit()

        token = self.orm.AuthenticationToken(
            access_token=get_uuid(),
            refresh_token=get_uuid(),
            token_type=self.token_type,
            user_id=user.id,
        )

        user.last_login = datetime.datetime.now()

        self.database.add(token)
        self.database.commit()

        setattr(request, "token", token)

        return cast(AuthenticationToken, token)


class UserExtensionServer(UserExtensionServerBase):
    """
    This base class defines default handlers, if desired.
    """

    handlers = UserExtensionHandlerRegistry()

    @handlers.format()
    @handlers.methods("POST")
    @handlers.path("^/login$")
    def login(self, request: Request, response: Response) -> AuthenticationToken:
        return super(UserExtensionServer, self).login(request, response)

    @handlers.format()
    @handlers.secured()
    @handlers.methods("GET")
    @handlers.path("^/self$")
    def get_self(self, request: Request, response: Response) -> User:
        user = (
            self.database.query(self.orm.User)
            .filter(self.orm.User.id == request.token.user_id)
            .one()
        )
        return cast(User, user)


class UserExtensionTemplateServer(UserExtensionServerBase, TemplateServer):
    """
    This avoids default handler registration and adds cookies, since the template server
    will likely be acting through a browser.
    """

    def on_configure(self) -> None:
        """
        On configure, grab the cookie name from config.
        """
        self.cookie = self.configuration.get("user.cookie", "pibble_token")

    def set_token_cookie(self, response: Response, token: AuthenticationToken) -> None:
        """
        Sets the cookie on the response object that contains the token.
        """
        response.set_cookie(
            self.cookie,
            token.access_token,
            secure=self.configuration.get("server.secure", False),
            domain=self.configuration.get("server.domain", None),
            samesite="strict"
            if self.configuration.get("server.secure", False)
            else None,
            expires=datetime.timedelta(
                days=self.configuration.get("user.token.days", 30)
            ),
        )

    def logout(self, request: Request, response: Response) -> None:
        """
        Override the logout handler to remove token cookie.
        """
        super(UserExtensionTemplateServer, self).logout(request, response)
        response.set_cookie(self.cookie, None, expires=datetime.timedelta(days=-1))

    def login(self, request: Request, response: Response) -> AuthenticationToken:
        """
        Override the login handler to add token cookie.
        """
        token = super(UserExtensionTemplateServer, self).login(request, response)
        logger.debug(
            "Successful login, setting cookie {0} on domain {1}".format(
                self.cookie, self.configuration.get("server.domain", None)
            )
        )
        self.set_token_cookie(response, token)
        return token

    def bypass_login(self, request: Request, response: Response) -> AuthenticationToken:
        """
        Override the bypass_login handler to add token cookie.
        """
        token = super(UserExtensionTemplateServer, self).bypass_login(request, response)
        self.set_token_cookie(response, token)
        return token

    def parse(
        self, request: Optional[Request] = None, response: Optional[Response] = None
    ) -> None:
        """
        Allow for passing token in in cookies in the Template server.
        """
        if request is not None:
            if not hasattr(request, "token"):
                cookie = request.cookies.get(self.cookie, None)

                if cookie:
                    token = (
                        self.database.query(self.orm.AuthenticationToken)
                        .filter(self.orm.AuthenticationToken.access_token == cookie)
                        .one_or_none()
                    )

                    if not token:
                        logger.warning(
                            "Authorization provided does not match to an authentication token."
                        )
                    else:
                        request.token = token

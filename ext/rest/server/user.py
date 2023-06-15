from typing import Callable, Any, List, Dict, Literal
from typing_extensions import Self

from webob import Request, Response

from pibble.api.exceptions import PermissionError, BadRequestError
from pibble.ext.user.server.base import (
    UserExtensionServer,
    UserExtensionHandlerRegistry,
)
from pibble.ext.rest.server.base import RESTExtensionServerBase
from pibble.ext.user.database import *


class UserRESTExtensionServerBase(UserExtensionServer, RESTExtensionServerBase):
    handlers = UserExtensionHandlerRegistry()

    def grant_permission_to_group(
        self, permission: Permission, user_permission_group: UserPermissionGroup
    ) -> None:
        """
        Grants a permission to a user group, if it does not already have it.
        """
        existing = (
            self.database.query(self.orm.PermissionGroupPermission)
            .filter(
                self.orm.PermissionGroupPermission.group_id
                == user_permission_group.group_id
            )
            .filter(self.orm.PermissionGroupPermission.permission_id == permission.id)
            .one_or_none()
        )

        if not existing:
            self.database.add(
                self.orm.PermissionGroupPermission(
                    permission_id=permission.id,
                    group_id=user_permission_group.group_id,
                )
            )
            self.database.commit()

    def grant_permission_to_user(self, permission: Permission, user: User) -> None:
        """
        Grants a permission to a user, if they do not already have it.
        """
        existing = (
            self.database.query(self.orm.UserPermission)
            .filter(self.orm.UserPermission.user_id == user.id)
            .filter(self.orm.UserPermission.permission_id == permission.id)
            .one_or_none()
        )

        if not existing:
            self.database.add(
                self.orm.UserPermission(
                    permission_id=permission.id,
                    user_id=user.id,
                )
            )
            self.database.commit()

    def grant_permission_after_create(
        self,
        user: User,
        grant_type: Literal["user", "group"],
        action: Literal["create", "read", "update", "delete"],
        object_name: str,
        explicit_scope_attribute: str,
        explicit_scope_value: str,
    ) -> None:
        """
        Grants a permission after creation.
        """
        permission = (
            self.database.query(self.orm.Permission)
            .filter(self.orm.Permission.action == action)
            .filter(self.orm.Permission.object_name == object_name)
            .filter(
                self.orm.Permission.explicit_scope_attribute == explicit_scope_attribute
            )
            .filter(self.orm.Permission.explicit_scope_value == explicit_scope_value)
            .one_or_none()
        )

        if not permission:
            permission = self.orm.Permission(
                action=action,
                object_name=object_name,
                scope_type="explicit",
                explicit_scope_attribute=explicit_scope_attribute,
                explicit_scope_value=explicit_scope_value,
            )
            self.database.add(permission)
            self.database.commit()

        if grant_type == "group":
            for user_permission_group in user.permission_groups:  # type: ignore
                self.grant_permission_to_group(permission, user_permission_group)
        elif grant_type == "user":
            self.grant_permission_to_user(permission, user)

    def grant_after(
        self,
        user: User,
        handler_classname: str,
        handler_scope: str,
        grant_items: List[Any],
        grants: Dict[str, List[str]],
    ) -> None:
        """
        Grants configured permissions after creation.
        """
        to_grant: List[Dict[str, str]] = []

        for grant_type in grants:
            for grant_action in grants[grant_type]:
                for grant_item in grant_items:
                    scope_value = getattr(grant_item, handler_scope)
                    permission_data = {
                        "grant_type": grant_type,
                        "object_name": handler_classname,
                        "action": grant_action,
                        "explicit_scope_attribute": handler_scope,
                        "explicit_scope_value": scope_value,
                    }
                    to_grant.append(permission_data)

        for permission_datum in to_grant:
            self.grant_permission_after_create(user, **permission_datum)  # type: ignore[arg-type]

    @classmethod
    def get_scoped_handler(
        cls,
        handler_classname: str,
        handler_root: str,
        handler_parent: List[str],
        handler_scope: str,
        **scope: Any
    ) -> Callable[..., Any]:
        """
        Builds the callable handler.
        """
        handler = RESTExtensionServerBase.get_scoped_handler(
            handler_classname, handler_root, handler_parent, handler_scope, **scope
        )

        def user_rest_scoped_handler(
            self: Self,
            request: Request = None,
            response: Response = None,
            **kwargs: Any
        ) -> Any:
            action = {
                "POST": "create",
                "GET": "read",
                "DELETE": "delete",
                "PUT": "update",
            }.get(request.method, None)

            if request.method == "PUT":
                if any([not kwargs[k] for k in kwargs]):
                    raise BadRequestError("Cannot PUT without scope.")

                orm_object = getattr(self.orm, handler_classname)
                existing = (
                    self.database.query(orm_object).filter_by(**kwargs).one_or_none()
                )
                action = "update" if existing else "create"

            if action:
                if not hasattr(request, "token"):
                    raise PermissionError("Invalid or no credentials supplied.")
                permission = self.check_user_permission(
                    request.token.user, handler_classname, action, **kwargs
                )
                if not permission:
                    raise PermissionError(
                        "User {0} is not authorized to {1} on {2}.".format(
                            request.token.user.username, action, handler_classname
                        )
                    )

            scope_user_fields = scope.get("user", {})
            for field in scope_user_fields:
                kwargs[scope_user_fields[field]] = getattr(
                    request.token.user, field, None
                )

            handler_result = handler(self, request, response, **kwargs)

            if action:
                after = scope.get("actions", {}).get(action, {})
                if isinstance(handler_result, list):
                    results = handler_result
                else:
                    results = [handler_result]  # type: ignore[unreachable]

                if "grant" in after:
                    self.grant_after(
                        request.token.user,
                        handler_classname,
                        handler_scope,
                        results,
                        after["grant"],
                    )

            return handler_result

        return user_rest_scoped_handler

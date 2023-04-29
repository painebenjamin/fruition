from pibble.util.log import logger
from pibble.api.exceptions import PermissionError, BadRequestError
from pibble.ext.user.server.base import (
    UserExtensionServer,
    UserExtensionHandlerRegistry,
)
from pibble.ext.rest.server.base import RESTExtensionServerBase

handlers = UserExtensionHandlerRegistry()


class UserRESTExtensionServerBase(UserExtensionServer, RESTExtensionServerBase):
    @classmethod
    def get_handlers(cls):
        return handlers

    @classmethod
    def get_scoped_handler(
        cls, handler_classname, handler_root, handler_parent, handler_scope, **scope
    ):
        handler = RESTExtensionServerBase.get_scoped_handler(
            handler_classname, handler_root, handler_parent, handler_scope, **scope
        )

        def user_rest_scoped_handler(self, request=None, response=None, **kwargs):
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
                            request.token.user.email, action, handler_classname
                        )
                    )
            try:
                result = handler(self, request, response, **kwargs)
                if action:
                    after = scope.get("actions", {}).get(action, {})
                    results = result
                    if not isinstance(results, list):
                        results = [results]

                    if "grant" in after:
                        for grant_type in after["grant"]:
                            for grant_action in after["grant"][grant_type]:
                                for result in results:
                                    scope_value = getattr(result, handler_scope)

                                    permission_data = {
                                        "scope_type": "explicit",
                                        "object_name": handler_classname,
                                        "action": grant_action,
                                        "explicit_scope_attribute": handler_scope,
                                        "explicit_scope_value": scope_value,
                                    }

                                    granted_permission = (
                                        self.database.query(self.orm.Permission)
                                        .filter_by(**permission_data)
                                        .one_or_none()
                                    )

                                    if not granted_permission:
                                        granted_permission = self.orm.Permission(
                                            **permission_data
                                        )
                                        self.database.add(granted_permission)
                                        self.database.commit()

                                    if grant_type == "group":
                                        for (
                                            user_group
                                        ) in request.token.user.permission_groups:
                                            if (
                                                self.database.query(
                                                    self.orm.PermissionGroupPermission
                                                )
                                                .filter(
                                                    self.orm.PermissionGroupPermission.group_id
                                                    == user_group.group_id
                                                )
                                                .filter(
                                                    self.orm.PermissionGroupPermission.permission_id
                                                    == permission.id
                                                )
                                                .one_or_none()
                                            ):
                                                logger.debug(
                                                    f"REST handler adding permission to group {user_group.group.label} after action '{action}'. Permission permits '{grant_action}' on {handler_classname} for scope {handler_scope} = {scope_value}"
                                                )
                                                self.database.add(
                                                    self.orm.PermissionGroupPermission(
                                                        group_id=user_group.group_id,
                                                        permission_id=granted_permission.id,
                                                    )
                                                )
                                                self.database.commit()

                                    elif grant_type == "user":
                                        if (
                                            not self.database.query(
                                                self.orm.UserPermission
                                            )
                                            .filter(
                                                self.orm.UserPermission.user_id
                                                == request.token.user.id
                                            )
                                            .filter(
                                                Self.orm.UserPermission.permission_id
                                                == granted_permission.id
                                            )
                                            .one_or_none()
                                        ):
                                            logger.debug(
                                                f"REST handler adding permission to user {request.token.user.email} after action '{action}'. Permission permits '{grant_action}' on {handler_classname} for scope {handler_scope} = {scope_value}"
                                            )

                                            self.database.add(
                                                self.orm.UserPermission(
                                                    user_id=request.token.user.id,
                                                    permission_id=granted_permission.id,
                                                )
                                            )
                                            self.database.commit()
            except:
                raise
            return result

        return user_rest_scoped_handler

from sqlalchemy import Column, Integer, String, Enum
from pibble.ext.user.database.base import UserExtensionObjectBase
from pibble.ext.user.database.user import User


class Permission(UserExtensionObjectBase):
    """
    Permission objects are applied into groups or to individual users.

    Permissions are either explicit or inherited:
      - An explicit permission is either granted carte blanche, or are
        based upon a specific scope (e.g., a single item)
      - An inherited permission is granted on objects that should have
        their permissions inherited from the permissions on other objects
        (e.g., if you can edit an item, you can edit it's children.)

    Permissions are quite abstract, so it may help to have an example.
    This is an object and handlers for a singularly-owned object,
    say, for example, a user's personal profile page. It is optional
    (doesn't need to exist), and public (anyone can view), but only
    the user who created it can edit it.

    The object would look like::

      class MySingularyOwnedObject(ORMObjectBase):
        # this object is owned by one user.
        # once created by the user, only they can edit it,
        # but anyone can view it.
        name = Column(String, primary_key = True)

    Base permissions would look like::
      p1 = Permission(scope_type = "explicit", object_name = "MySingularlyOwnedObject", action = "create") # always allow creation.
      p2 = Permission(scope_type = "explicit", object_name = "MySingularlyOwnedObject", action = "read") # always allow reading.
      pg = PermissionGroup()
      session.add_all([p1, p2, pg])
      session.add(PermissionGroupPermission(group_id = pg.id, permission_id = p1.id))
      session.add(PermissionGroupPermission(group_id = pg.id, permission_id = p2.id))
      session.add(GlobalPermissionGroup(group_id = pg.id))

      session.commit()

    And some handlers::

      @handlers.methods("POST")
      @handlers.secured("MySingularlyOwnedObject", "create")
      @handlers.path(r"^/singular$")
      def createSingularObject(self, request, response, name = None):
        # create the object, then add the permission to update and delete on its scope.
        Permission(scope_type = "explicit", action = "update", explicit_scope_attribute = "name", explicit_scope_value = name, user_id = request.token.user.id)

      @handlers.methods("PUT")
      @handlers.secured("MySingularlyOwnedObject", "update")
      @handlers.path(r"^/singular/(?P<name>[a-zA-Z0-9_\-]+)$")
      def modifySingularObject(self, request, response, name = None):
        # this will only be allowed if the associated permission exists, so feel free
        # to just have this handler modify the object.
    """

    __tablename__ = "pibble_permission"

    id = Column(Integer, autoincrement=True, primary_key=True)
    object_name = Column(String, nullable=False)

    action = Column(
        Enum("create", "read", "update", "delete", name="action_enum"),
        default="read",
        nullable=False,
    )
    secondary_action = Column(String)

    scope_type = Column(
        Enum("explicit", "inherited", name="scope_type_enum"),
        default="explicit",
        nullable=False,
    )

    explicit_scope_attribute = Column(String)
    explicit_scope_value = Column(String)

    inherited_scope_object_name = Column(String)
    inherited_scope_source_attribute = Column(String)
    inherited_scope_target_attribute = Column(String)
    inherited_scope_action = Column(String)
    inherited_scope_secondary_action = Column(String)


class PermissionGroup(UserExtensionObjectBase):
    __tablename__ = "pibble_permission_group"

    id = Column(Integer, autoincrement=True, primary_key=True)
    label = Column(String)


class PermissionGroupPermission(UserExtensionObjectBase):
    __tablename__ = "pibble_permission_group_permission"

    group_id = Column(
        Integer,
        PermissionGroup.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    permission_id = Column(
        Integer,
        Permission.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )

    permission = Permission.Relationship()
    group = PermissionGroup.Relationship()


class UserPermission(UserExtensionObjectBase):
    __tablename__ = "pibble_user_permission"

    permission_id = Column(
        Integer,
        Permission.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        User.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )

    permission = Permission.Relationship()


User.Relate(UserPermission, name="permissions", backref="user")


class GlobalPermission(UserExtensionObjectBase):
    __tablename__ = "pibble_global_permission"

    permission_id = Column(
        Integer,
        Permission.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    permission = Permission.Relationship()


class UserPermissionGroup(UserExtensionObjectBase):
    __tablename__ = "pibble_user_permission_group"

    group_id = Column(
        Integer,
        PermissionGroup.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        User.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )

    group = PermissionGroup.Relationship()


User.Relate(UserPermissionGroup, name="permission_groups", backref="user")


class GlobalPermissionGroup(UserExtensionObjectBase):
    __tablename__ = "pibble_global_permission_group"

    group_id = Column(
        Integer,
        PermissionGroup.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    group = PermissionGroup.Relationship()

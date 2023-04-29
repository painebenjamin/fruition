import sqlalchemy
import time

from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import expect_exception
from pibble.util.files import TempfileContext
from pibble.database.orm import ORMObjectBase
from pibble.api.exceptions import (
    NotFoundError,
    AuthenticationError,
    PermissionError,
    BadRequestError,
)
from pibble.api.server.webservice.jsonapi import JSONWebServiceAPIServer
from pibble.api.client.webservice.jsonapi import JSONWebServiceAPIClient
from pibble.ext.user.server.base import (
    UserExtensionServer,
    UserExtensionHandlerRegistry,
)
from pibble.ext.user.client.base import UserExtensionClientBase
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound


class TestObjectBase(ORMObjectBase):
    pass


class OwnedObject(TestObjectBase):
    __tablename__ = "owned_object"
    name = sqlalchemy.Column(sqlalchemy.String, primary_key=True)


class OwnedSubObject(TestObjectBase):
    __tablename__ = "owned_sub_object"
    owned_object_name = sqlalchemy.Column(
        sqlalchemy.String,
        OwnedObject.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    name = sqlalchemy.Column(sqlalchemy.String, primary_key=True)


server_configuration = {"host": "0.0.0.0", "port": "9090", "driver": "werkzeug"}

client_configuration = {
    "host": "localhost",
    "port": "9090",
}

orm_configuration = {
    "base": TestObjectBase,
    "type": "sqlite",
    "connection": {"database": None},
    "migrate": True,
}

user_1_data = {"email": "admin@localhost", "password": "password"}

user_2_data = {"email": "user@localhost", "password": "password"}

user_configuration = {
    "permissions": [
        {
            "scope_type": "explicit",
            "object_name": OwnedObject.__name__,
            "action": action,
            "global": True,
        }
        for action in ["create", "read"]
    ]
    + [
        {
            "scope_type": "inherited",
            "object_name": OwnedSubObject.__name__,
            "inherited_scope_object_name": OwnedObject.__name__,
            "inherited_scope_target_attribute": "name",
            "inherited_scope_source_attribute": "owned_object_name",
            "action": action,
            "global": True,
        }
        for action in ["create", "update", "delete"]
    ],
    "users": [user_1_data, user_2_data],
}

owned_object_data = {"name": "my_owned_object"}

owned_sub_object_data = {
    "sub_object_name": owned_object_data["name"],
    "name": "my_owned_sub_object",
}


class JSONUserClient(JSONWebServiceAPIClient, UserExtensionClientBase):
    pass

handlers = UserExtensionHandlerRegistry()

class JSONUserServer(JSONWebServiceAPIServer, UserExtensionServer):
    @classmethod
    def get_handlers(cls) -> UserExtensionHandlerRegistry:
        return handlers

    @handlers.format()
    @handlers.secured(OwnedObject, action="create")
    @handlers.path("^/owned_object$")
    @handlers.methods("POST")
    def create_owned_object(self, request, response):
        try:
            new_object = self.orm.OwnedObject(name=request.parsed["name"])
            self.database.add(new_object)

            for action in ["update", "delete"]:
                new_permission = self.orm.Permission(
                    scope_type="explicit",
                    object_name=OwnedObject.__name__,
                    action=action,
                    explicit_scope_attribute="name",
                    explicit_scope_value=request.parsed["name"],
                )
                self.database.add(new_permission)
                self.database.commit()
                self.database.add(
                    self.orm.UserPermission(
                        permission_id=new_permission.id, user_id=request.token.user.id
                    )
                )
            self.database.commit()
            return new_object
        except IntegrityError as ex:
            raise BadRequestError(
                "Your request could not be completed: {0}".format(
                    str(ex).splitlines()[0]
                )
            )
        except KeyError as ex:
            raise BadRequestError("Missing required parameter {0}".format(ex))

    @handlers.format()
    @handlers.secured(OwnedObject, action="update")
    @handlers.path("^/owned_object/(?P<name>[a-zA-Z0-9_\-]+)$")
    @handlers.methods("PUT")
    def modify_owned_object(self, request, response, name=None):
        try:
            self.database.query(self.orm.OwnedObject).filter(
                self.orm.OwnedObject.name == name
            ).one()
        except NoResultFound:
            self.assert_user_permission(request, OwnedObject, "create")
            request.parsed["name"] = name
            return self.create_owned_object(request, response)

    @handlers.format()
    @handlers.secured(OwnedSubObject, action="create")
    @handlers.path("^/owned_sub_object/(?P<owned_object_name>[a-zA-Z0-9_\-]+)$")
    @handlers.methods("POST")
    def create_owned_sub_object(self, request, response, owned_object_name=None):
        try:
            self.assert_user_permission(
                request, OwnedObject.__name__, "update", name=owned_object_name
            )
            new_object = self.orm.OwnedSubObject(
                owned_object_name=owned_object_name, name=request.parsed["name"]
            )
            self.database.add(new_object)
            self.database.commit()
            return new_object
        except IntegrityError as ex:
            raise BadRequestError(
                "Your request could not be completed: {0}".format(
                    str(ex).splitlines()[0]
                )
            )
        except KeyError as ex:
            raise BadRequestError("Missing required parameter {0}".format(ex))

    @handlers.format()
    @handlers.secured(OwnedSubObject, action="update")
    @handlers.path(
        "^/owned_sub_object/(?P<owned_object_name>[a-zA-Z0-9_\-]+)/(?P<name>[a-zA-Z0-9_\-]+)$"
    )
    @handlers.methods("PUT")
    def modify_owned_sub_object(
        self, request, response, owned_object_name=None, name=None
    ):
        try:
            self.database.query(self.orm.OwnedSubObject).filter(
                (self.orm.OwnedSubObject.owned_object_name == owned_object_name)
                & (self.orm.OwnedSubObject.name == name)
            ).one()
        except NoResultFound:
            self.assert_user_permission(
                request, OwnedSubObject, "create", owned_object_name=owned_object_name
            )
            request.parsed["name"] = name
            return self.create_owned_sub_object(
                request, response, owned_object_name=owned_object_name
            )


def main():
    with TempfileContext() as temp:
        with DebugUnifiedLoggingContext():
            database = next(temp)
            orm_configuration["connection"]["database"] = database

            server = JSONUserServer()
            server.configure(
                server=server_configuration,
                orm=orm_configuration,
                user=user_configuration,
            )
            server.start()

            try:
                time.sleep(0.125)

                client = JSONWebServiceAPIClient()
                client.configure(client=client_configuration)

                expect_exception(NotFoundError)(client.get)
                expect_exception(AuthenticationError)(lambda: client.get("self"))
                expect_exception(AuthenticationError)(
                    lambda: client.post("owned_object", data=owned_object_data)
                )

                expect_exception(AuthenticationError)(
                    lambda: client.post(
                        "login",
                        data={**user_1_data, **{"password": "not_the_password"}},
                    )
                )

                token_1_response = client.post("login", data=user_1_data).json()["data"]
                token_2_response = client.post("login", data=user_2_data).json()["data"]

                def _set_token(token_response):
                    client.headers["Authorization"] = "{0} {1}".format(
                        token_response["attributes"]["token_type"],
                        token_response["attributes"]["access_token"],
                    )

                _set_token(token_2_response)
                client.get("self")  # Assert this works

                owned_object = client.post("owned_object", data=owned_object_data)
                client.put("owned_object/{0}".format(owned_object_data["name"]))

                _set_token(token_1_response)
                expect_exception(PermissionError)(
                    lambda: client.put(
                        "owned_object/{0}".format(owned_object_data["name"])
                    )
                )
                expect_exception(PermissionError)(
                    lambda: client.put(
                        "owned_sub_object/{0}/{1}".format(
                            owned_object_data["name"], owned_sub_object_data["name"]
                        )
                    )
                )
                expect_exception(PermissionError)(
                    lambda: client.post(
                        "owned_sub_object/{0}".format(owned_object_data["name"]),
                        data=owned_sub_object_data,
                    )
                )

                _set_token(token_2_response)
                client.put(
                    "owned_sub_object/{0}/{1}".format(
                        owned_object_data["name"], owned_sub_object_data["name"]
                    )
                )

                other_client = JSONUserClient()
                other_client.configure(client=client_configuration)
                other_client.login(user_1_data["email"], user_1_data["password"])
                other_client.get("self")

            finally:
                server.stop()


if __name__ == "__main__":
    main()

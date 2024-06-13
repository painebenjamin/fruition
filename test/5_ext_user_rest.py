import time

from sqlalchemy import Column, String, ForeignKeyConstraint

from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion, expect_exception
from fruition.util.strings import random_string
from fruition.util.files import TempfileContext
from fruition.database.orm import ORMObjectBase
from fruition.api.exceptions import NotFoundError, PermissionError
from fruition.api.client.webservice.jsonapi import JSONWebServiceAPIClient
from fruition.api.server.webservice.jsonapi import JSONWebServiceAPIServer
from fruition.ext.rest.server.user import UserRESTExtensionServerBase
from fruition.ext.user.client.base import UserExtensionClientBase


class UserRESTExtensionJSONServer(JSONWebServiceAPIServer, UserRESTExtensionServerBase):
    pass


class UserRESTExtensionJSONClient(JSONWebServiceAPIClient, UserExtensionClientBase):
    pass


class TestObjectBase(ORMObjectBase):
    pass


class TestObject(TestObjectBase):
    __tablename__ = "test_object"
    name = Column(String, primary_key=True)


class ChildTestObject(TestObjectBase):
    __tablename__ = "child_test_object"
    name = Column(String, primary_key=True)
    parent_name = Column(
        String,
        TestObject.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )


TestObject.Relate(
    ChildTestObject,
    name="children",
    backref="parent",
    foreign_keys=[ChildTestObject.parent_name],
)


class GrandchildTestObject(TestObjectBase):
    __tablename__ = "grandchild_test_object"
    __table_args__ = (
        ForeignKeyConstraint(
            ["parent_name", "parent_parent_name"],
            ["child_test_object.name", "child_test_object.parent_name"],
        ),
    )

    name = Column(String, primary_key=True)
    parent_name = Column(String, primary_key=True)
    parent_parent_name = Column(String, primary_key=True)


ChildTestObject.Relate(GrandchildTestObject, name="children", backref="parent")

USER_1 = {
    "username": "user@test.com",
    "password": random_string(),
    "groups": ["Fruition Creators"],
}

USER_2 = {"username": "user2@test.com", "password": random_string()}

CONFIGURATION = {
    "server": {"host": "0.0.0.0", "port": "9090", "driver": "werkzeug"},
    "orm": {
        "type": "sqlite",
        "connection": {"database": None},
        "base": TestObjectBase,
        "migrate": True,
    },
    "user": {
        "users": [USER_1, USER_2],
        "permissions": [
            {
                "object_name": TestObject.__name__,
                "scope_type": "explicit",
                "action": "read",
                "global": True,
            },
            {
                "object_name": TestObject.__name__,
                "scope_type": "explicit",
                "action": "create",
                "group": "Fruition Creators",
            },
        ]
        + [
            {
                "object_name": ChildTestObject.__name__,
                "scope_type": "inherited",
                "action": action,
                "group": "Fruition Creators",
                "inherited_scope_object_name": TestObject.__name__,
                "inherited_scope_source_attribute": "parent_name",
                "inherited_scope_target_attribute": "name",
                "inherited_scope_action": "update",
            }
            for action in ["create", "read", "update", "delete"]
        ]
        + [
            {
                "object_name": GrandchildTestObject.__name__,
                "scope_type": "inherited",
                "action": action,
                "group": "Fruition Creators",
                "inherited_scope_object_name": TestObject.__name__,
                "inherited_scope_source_attribute": "parent_parent_name",
                "inherited_scope_target_attribute": "name",
            }
            for action in ["create", "read", "update", "delete"]
        ],
    },
    "rest": {
        "root": "",
        "scopes": [
            {
                "class": TestObject,
                "scope": "name",
                "secured": True,
                "actions": {"create": {"grant": {"group": ["update", "delete"]}}},
            },
            {
                "class": ChildTestObject,
                "parent": "parent_name",
                "scope": "name",
                "secured": True,
            },
            {
                "class": GrandchildTestObject,
                "parent": ["parent_parent_name", "parent_name"],
                "scope": "name",
                "secured": True,
            },
        ],
    },
}


def main():
    with TempfileContext() as temp:
        with DebugUnifiedLoggingContext():
            database = next(temp)
            CONFIGURATION["orm"]["connection"]["database"] = database

            server = UserRESTExtensionJSONServer()
            server.configure(**CONFIGURATION)
            server.start()

            try:
                time.sleep(0.125)

                client = UserRESTExtensionJSONClient()
                client.configure(client={"host": "127.0.0.1", "port": "9090"})

                test_object_name_1 = "my_test_object_1"
                test_object_response_1 = {
                    "type": "TestObject",
                    "attributes": {"name": test_object_name_1},
                }
                test_object_name_2 = "my_test_object_2"
                test_object_response_2 = {
                    "type": "TestObject",
                    "attributes": {"name": test_object_name_2},
                }

                test_children_object_name = "my_children_test_object"
                test_children_object_response = {
                    "type": "ChildTestObject",
                    "attributes": {
                        "name": test_children_object_name,
                        "parent_name": "my_test_object_1",
                    },
                }

                test_grandchildren_object_name = "my_grandchildren_test_object"
                test_grandchildren_object_response = {
                    "type": "GrandchildTestObject",
                    "attributes": {
                        "name": test_grandchildren_object_name,
                        "parent_name": test_children_object_name,
                        "parent_parent_name": test_object_name_1,
                    },
                }

                test_children_parent_response = {
                    **test_object_response_1,
                    **{"include": {"children": [test_children_object_response]}},
                }
                test_grandchildren_parent_response = {
                    **test_object_response_1,
                    **{
                        "include": {
                            "children": [
                                {
                                    **test_children_object_response,
                                    **{
                                        "include": {
                                            "children": [
                                                test_grandchildren_object_response
                                            ]
                                        }
                                    },
                                }
                            ]
                        }
                    },
                }

                # No login, expect error
                expect_exception(PermissionError)(
                    lambda: client.get(TestObject.__name__)
                )
                client.login(USER_1["username"], USER_1["password"])

                Assertion(Assertion.EQ)(
                    [], client.get(TestObject.__name__).json()["data"]
                )
                Assertion(Assertion.EQ)(
                    test_object_response_1,
                    client.post(
                        TestObject.__name__, data={"name": test_object_name_1}
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_object_response_1],
                    client.get(TestObject.__name__).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_object_response_1],
                    client.get(
                        "{0}/{1}".format(TestObject.__name__, test_object_name_1)
                    ).json()["data"],
                )

                Assertion(Assertion.EQ)(
                    test_object_response_2,
                    client.put(
                        "{0}/{1}".format(TestObject.__name__, test_object_name_2)
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_object_response_1, test_object_response_2],
                    client.get(TestObject.__name__).json()["data"],
                )

                Assertion(Assertion.EQ)(
                    [],
                    client.delete(
                        "{0}/{1}".format(TestObject.__name__, test_object_name_2)
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_object_response_1],
                    client.get(TestObject.__name__).json()["data"],
                )
                expect_exception(NotFoundError)(
                    lambda: client.get(
                        "{0}/{1}".format(TestObject.__name__, test_object_name_2)
                    )
                )

                Assertion(Assertion.EQ)(
                    test_children_object_response,
                    client.post(
                        "{0}/{1}".format(ChildTestObject.__name__, test_object_name_1),
                        data={"name": test_children_object_name},
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_children_object_response],
                    client.get(
                        "{0}/{1}/{2}".format(
                            ChildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                        )
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_children_parent_response],
                    client.get(
                        TestObject.__name__, parameters={"include": "children"}
                    ).json()["data"],
                )

                Assertion(Assertion.EQ)(
                    test_grandchildren_object_response,
                    client.post(
                        "{0}/{1}/{2}".format(
                            GrandchildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                        ),
                        data={"name": test_grandchildren_object_name},
                    ).json()["data"],
                )
                Assertion(Assertion.EQ)(
                    [test_grandchildren_object_response],
                    client.get(
                        "{0}/{1}/{2}/{3}".format(
                            GrandchildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                            test_grandchildren_object_name,
                        )
                    ).json()["data"],
                )

                Assertion(Assertion.EQ)(
                    [test_grandchildren_parent_response],
                    client.get(
                        TestObject.__name__,
                        parameters={"include": ["children", "children.children"]},
                    ).json()["data"],
                )

                client.login(USER_2["username"], USER_2["password"])

                expect_exception(PermissionError)(
                    lambda: client.delete(
                        "{0}/{1}/{2}".format(
                            ChildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                        )
                    )
                )
                expect_exception(PermissionError)(
                    lambda: client.delete(
                        "{0}/{1}/{2}/{3}".format(
                            GrandchildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                            test_grandchildren_object_name,
                        )
                    ).json()["data"]
                )
                expect_exception(PermissionError)(
                    lambda: client.put(
                        "{0}/{1}/{2}/{3}".format(
                            GrandchildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                            test_grandchildren_object_name,
                        )
                    )
                )
                expect_exception(PermissionError)(
                    lambda: client.get(
                        "{0}/{1}/{2}/{3}".format(
                            GrandchildTestObject.__name__,
                            test_object_name_1,
                            test_children_object_name,
                            test_grandchildren_object_name,
                        )
                    )
                )

            finally:
                server.stop()


if __name__ == "__main__":
    main()

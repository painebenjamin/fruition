import time

from sqlalchemy import Column, String, ForeignKeyConstraint

from pibble.util.log import DebugUnifiedLoggingContext
from pibble.util.helpers import expect_exception, Assertion
from pibble.util.files import TempfileContext

from pibble.database.orm import ORMObjectBase
from pibble.api.exceptions import NotFoundError, BadRequestError, PermissionError
from pibble.api.client.webservice.jsonapi import JSONWebServiceAPIClient
from pibble.api.server.webservice.jsonapi import JSONWebServiceAPIServer
from pibble.ext.rest.server.base import RESTExtensionServerBase


class RESTExtensionJSONServer(JSONWebServiceAPIServer, RESTExtensionServerBase):
    pass


class TestObjectBase(ORMObjectBase):
    pass


class TestObject(TestObjectBase):
    __tablename__ = "test_object"
    name = Column(String, primary_key=True)
    hidden_field = Column(String, nullable=True)


TestObject.Hide(columns=["hidden_field"])


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

CONFIGURATION = {
    "server": {"host": "0.0.0.0", "port": "9090", "driver": "werkzeug"},
    "orm": {
        "type": "sqlite",
        "connection": {"database": None},
        "base": TestObjectBase,
        "migrate": True,
    },
    "rest": {
        "root": "",
        "scopes": [
            {"class": TestObject, "scope": "name"},
            {"class": ChildTestObject, "parent": "parent_name", "scope": "name"},
            {
                "class": GrandchildTestObject,
                "parent": ["parent_parent_name", "parent_name"],
                "scope": "name",
            },
        ],
    },
}


def main():
    with TempfileContext() as temp:
        with DebugUnifiedLoggingContext():
            database = next(temp)
            CONFIGURATION["orm"]["connection"]["database"] = database

            server = RESTExtensionJSONServer()
            server.configure(**CONFIGURATION)
            server.start()

            try:

                time.sleep(0.125)

                client = JSONWebServiceAPIClient()
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

                expect_exception(NotFoundError)(
                    lambda: client.patch(
                        "{0}/{1}".format(TestObject.__name__, test_object_name_2)
                    )
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

                expect_exception(PermissionError)(
                    lambda: client.post(
                        TestObject.__name__,
                        data={"name": "failing_name", "hidden_field": "failing_value"},
                    )
                )
                expect_exception(BadRequestError)(
                    lambda: client.post(
                        TestObject.__name__,
                        data={"name": "failing_name", "wrong_field": "failing_value"},
                    )
                )

            finally:
                server.stop()


if __name__ == "__main__":
    main()

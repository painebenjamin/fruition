import os

from typing import Any

from fruition.api.helpers.store import APISessionStore
from fruition.api.configuration import APIConfiguration

from fruition.util.helpers import Assertion, expect_exception
from fruition.util.files import TempfileContext
from fruition.util.log import DebugUnifiedLoggingContext


def main() -> None:
    with DebugUnifiedLoggingContext():
        with TempfileContext() as tempfiles:
            database_store_file = next(tempfiles)

            # connection = sqlite3.connect(database_store_file)
            # cursor = connection.cursor()
            # cursor.execute("CREATE TABLE sessionstore (id INT, sesskey TEXT, sessvalue TEXT, PRIMARY KEY(id, sesskey))")
            # connection.commit()

            base_session_config = {
                "store": {
                    "database": {
                        "type": "sqlite",
                        "key": "sesskey",
                        "value": "sessvalue",
                        "table": "sessionstore",
                        "connection": {"database": database_store_file},
                    }
                }
            }

            def get_session_config(drivername: str, **kwargs: Any) -> APIConfiguration:
                apiconfig = APIConfiguration(session=base_session_config)
                apiconfig.update(session={"store": {"driver": drivername}})
                apiconfig.update(session={"store": kwargs})
                return apiconfig

            memory_store = APISessionStore(get_session_config("memory"))
            database_store = APISessionStore(
                get_session_config("database", database={"constants": {"id": 1}})
            )
            set_a = Assertion(Assertion.EQ, "Set Value")
            upd_a = Assertion(Assertion.EQ, "Update Value")
            del_a = Assertion(Assertion.IS, "Delete Value")

            for store in [memory_store, database_store]:
                print("Testing {0}".format(type(store.driver).DRIVERNAME))
                try:
                    store["my_key"] = "my_value"
                    set_a(store["my_key"], "my_value")

                    store["my_key"] = "my_value_2"
                    upd_a(store["my_key"], "my_value_2")

                    store["my_key"] = 1
                    set_a(store["my_key"], 1)

                    store["my_key"] = {"a": {"b": [2]}}
                    set_a(store["my_key"], {"a": {"b": [2]}})

                    del store["my_key"]
                    expect_exception(KeyError)(lambda: store["my_key"])
                except Exception as ex:
                    print(
                        "Error occurred during testing session store type '{0}': {1}({2})".format(
                            store.driver.DRIVERNAME, type(ex).__name__, str(ex)
                        )
                    )
                    raise

            database_store["my_key"] = "my_value"
            database_store_2 = database_store.getScope("other")
            expect_exception(KeyError)(lambda: database_store_2["my_key"])


if __name__ == "__main__":
    main()

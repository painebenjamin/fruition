from typing import Any
from pibble.util.log import logger
from pibble.api.client.webservice.base import WebServiceAPIClientBase


class UserExtensionClientBase(WebServiceAPIClientBase):
    """
    A small class that adds the 'login' method to get a token and set authorization.
    """

    def login(self, username: str, password: str) -> Any:
        """
        Logs in, in accordance with the schema set by `UserExtensionServerBase`.

        :param username str: The username address of the user to log in as.
        :param password str: The password of the user to log in as.
        :returns dict: The login response.
        """
        response = self.post(
            "login", data={"username": username, "password": password}
        ).json()["data"]
        self.headers["Authorization"] = "{0} {1}".format(
            response["attributes"]["token_type"], response["attributes"]["access_token"]
        )
        logger.info("Logged in as {0}".format(username))
        return response

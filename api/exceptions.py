from typing import Optional, Type
from pibble.util.helpers import qualify

try:
    from thrift.Thrift import TApplicationException
except ImportError:
    TApplicationException: Type = Exception  # type: ignore[no-redef]


class ApacheThriftError(TApplicationException):  # type: ignore
    """
    An exception wrapping around TApplicationExceptions, to pass up to the thrift server layer.

    :param cause Exception: The exception to wrap.
    """

    def __init__(self, cause: Exception):
        self.cause = cause
        super(ApacheThriftError, self).__init__(None, f"{qualify(cause)}: {cause}")


class NotFoundError(Exception):
    """
    An exception to be thrown when a resource cannot be found.

    Translates to a 404 error on web service APIs.

    :param msg str: The message to send in the request. Defaults to "The resource or method you requested could not be found."
    """

    def __init__(
        self, msg: str = "The resource or method you requested could not be located."
    ):
        super(NotFoundError, self).__init__(msg)


class UnsupportedMethodError(Exception):
    """
    An exception to be thrown when a request is understood, but the method of calling is not correct.

    Translates to a 405 error on web service APIs.

    :param msg str: The message to send in the request. Defaults to "The request to the server was understood, but the method of calling it was incorrect."
    """

    def __init__(
        self,
        msg: str = "The request to the server was understood, but the method of calling it was incorrect.",
    ):
        super(UnsupportedMethodError, self).__init__(msg)


class AuthenticationError(Exception):
    """
    An exception indicating an authentication error occurred.

    Implementing authentication mixins should raise this when authentication fails, for whatever reason. Translates to a 401 error in webserver APIs.

    :param msg str: The message to send, defaults to "An authentication error occurred."
    """

    def __init__(self, msg: str = "An authentication error occurred."):
        super(AuthenticationError, self).__init__(msg)


class AuthorizationError(Exception):
    """
    An exception indicating an authorization error occurred.

    As opposed to an AuthenticationError, AuthorizationErrors will often indicate a redirect to a different URL to perform authorization; i.e., an OAuth callback.

    :param url str: The URL to redirect to. If not passed, this will be treated a an error.
    """

    def __init__(self, url: Optional[str] = None):
        if url is not None:
            self.url = url
            super(AuthorizationError, self).__init__(
                "Authorization must be completed by navigating to {0}.".format(self.url)
            )
        else:
            super(AuthorizationError, self).__init__("An authorization error occurred.")


class PermissionError(Exception):
    """
    An exception indicating a permission error occurred.

    This would be thrown when specific permissions need to be checked for an action, and that user does not have that permission. Translates to a 403 error in webserver APIs.

    :param msg str: The message to send, defaults to "You do not have permission to perform this action."
    """

    def __init__(self, msg: str = "You do not have permission to perform this action."):
        super(PermissionError, self).__init__(msg)


class BadRequestError(Exception):
    """
    An exception indicating a request was malformed.

    This would be thrown when the request formatting was off. Translates to a 400 error in webserver APIs.

    :param msg str: The message to send, defaults to "The request was malformed."
    """

    def __init__(self, msg: str = "The request was malformed."):
        super(BadRequestError, self).__init__(msg)


class BadResponseError(Exception):
    """
    An exception indicating a response from the server was malformed.

    :param msg str: The message to send. Defaults to "The server responded, but it could not be parsed."
    """

    def __init__(self, msg: str = "The server responded, but it could not be parsed."):
        super(BadResponseError, self).__init__(msg)


class TooManyRequestsError(Exception):
    """
    An exception indicating the client is making too many requests.
    """

    def __init__(self, msg: str = "Too many requests."):
        super(TooManyRequestsError, self).__init__(msg)


class StateConflictError(Exception):
    """
    An exception indicating something about the users request cannot
    be fulfilled because it violates domain logic.
    """

    def __init__(self, msg: str = "The request cannot be fulfilled."):
        super(StateConflictError, self).__init__(msg)


class UnknownError(Exception):
    """
    An exception indicating somethign went wrong that was unexpected.

    :param msg str: The message to send. Defaults to "An unknown error occurred."
    """

    def __init__(self, msg: str = "An unknown error occurred."):
        super(UnknownError, self).__init__(msg)


class ConfigurationError(Exception):
    """
    An exception indicating some required configuration is not present, or is incorrect.

    :param msg str: The message to send, defaults to "Required configuration values are not present. Please ensure your client or server is properly configured."
    """

    def __init__(
        self,
        msg: str = "Required configuration values are not present. Please ensure your client or server is properly configured.",
    ):
        super(ConfigurationError, self).__init__(msg)


class MissingConfigurationError(ConfigurationError):
    """
    A small helper exception that indicates a required key is not present.

    :param key str: The missing key.
    """

    def __init__(self, key: str):
        super(MissingConfigurationError, self).__init__(
            "Required configuration key '{0}' not present. Please run .configure() with these values.".format(
                key
            )
        )


class DatabaseIntegrityError(Exception):
    """
    An exception indicating that a database integrity clause has been violated; i.e.,
    the state of the database is inconsistent with expectation.
    """

    def __init__(
        self,
        msg: str = "The application's database does not support the action you tried to perform.",
    ):
        super(DatabaseIntegrityError, self).__init__(msg)

import json

from typing import Any, Type

from pibble.api.client.webservice.rpc.base import RPCClientBase
from pibble.api.exceptions import (
    BadRequestError,
    BadResponseError,
    UnknownError,
    UnsupportedMethodError,
)
from pibble.util.strings import Serializer


class JSONRPCClient(RPCClientBase):
    """
    An implementation of a JSON RPC client.

    We can't do an all-encompassing doctest here, as it relies on an externally reachable server.
    """

    def __init__(self) -> None:
        super(JSONRPCClient, self).__init__()
        self.headers["Content-Type"] = "application/json"
        self.request_id = 1

    @staticmethod
    def map_typename(typename: str) -> Type:
        """
        Takes a string typename ("string", "float", etc.) and turns it into a python type.

        >>> from pibble.api.client.webservice.rpc.jsonrpc import JSONRPCClient
        >>> from pibble.util.helpers import expect_exception
        >>> JSONRPCClient.map_typename("int")
        <class 'int'>
        >>> JSONRPCClient.map_typename("array")
        <class 'list'>
        >>> expect_exception(TypeError)(lambda: JSONRPCClient.map_typename("struct"))

        :param typename str: The typname.
        :returns Type: The type of the object.
        :raises TypeError: When no type information is available.
        """
        _type = {
            "float": float,
            "int": int,
            "string": str,
            "array": list,
            "object": dict,
            "boolean": bool,
            "null": None,
        }.get(typename, None)

        if _type is None:
            raise TypeError("Cannot determine type from name '{0}'.".format(typename))
        return _type

    def format_request(self, method_name: str, *args: Any, **kwargs: Any) -> str:
        """
        Formats a request with method_name, *args and **kwargs into a JSONRPC request.

        >>> from pibble.api.client.webservice.rpc.jsonrpc import JSONRPCClient
        >>> client = JSONRPCClient()
        >>> client.format_request("add", 1, 2)
        '{"jsonrpc": "2.0", "method": "add", "id": 1, "params": [1, 2]}'
        >>> client.format_request("pow", base = 2, exponent = 3)
        '{"jsonrpc": "2.0", "method": "pow", "id": 2, "params": {"base": 2, "exponent": 3}}'

        :param methodName str: The method to call.
        :param args tuple: The parameters to pass into the method.
        :param kwargs dict: The named parameters to pass into the method.
        """
        base = {"jsonrpc": "2.0", "method": method_name, "id": self.request_id}
        self.request_id += 1

        if args:
            base["params"] = list(args)
        if kwargs:
            base["params"] = kwargs
        elif args and kwargs:
            raise BadRequestError(
                "Cannot pass both positional and named arguments into a JSONRPC method request."
            )
        return json.dumps(base, default=Serializer.serialize)

    def format_response(self, response: str) -> Any:
        """
        Takes a response from the RPC server, and returns its contents.

        >>> from pibble.api.client.webservice.rpc.jsonrpc import JSONRPCClient
        >>> import json
        >>> JSONRPCClient.format_response(None, json.dumps({"result": 4}))
        4
        >>> JSONRPCClient.format_response(None, json.dumps({"result": {"key": "value"}}))
        {'key': 'value'}

        :param response str: The body returned from the request.
        :returns object: The result of the request, in whatever format they come in.
        """
        try:
            body = json.loads(response)
        except json.decoder.JSONDecodeError:
            raise BadResponseError(
                "Received a response from the request, but was unable to parse it."
            )
        if "code" in body:
            code = int(body["code"])
            msg = body.get("message", None)
            if code == -32700:
                raise BadRequestError(
                    "The request to the server was not well-formed: {0}".format(msg)
                )
            elif code == -32601:
                raise UnsupportedMethodError(
                    "The server did not understand the method called: {0}".format(msg)
                )
            elif code == -32600:
                raise BadRequestError(
                    "The request to the server was understood, but incorrect: {0}".format(
                        msg
                    )
                )
            else:
                raise UnknownError(
                    "An unhandled fault code ({0}) was received. Message: {1}".format(
                        code, msg
                    )
                )
        return Serializer.deserialize(body.get("result", None))

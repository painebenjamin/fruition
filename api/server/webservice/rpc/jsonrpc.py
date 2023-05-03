import datetime
import json

from typing import Type, Any, Optional

from webob import Request, Response

from pibble.api.server.webservice.rpc.base import RPCServerBase
from pibble.api.exceptions import UnsupportedMethodError, BadRequestError
from pibble.util.strings import Serializer, decode


class JSONRPCSerializer(Serializer):
    SERIALIZE_FORMATS = {
        **Serializer.SERIALIZE_FORMATS,
        **{type: lambda p, **k: JSONRPCServer.map_typename(p)},
    }


class JSONRPCServer(RPCServerBase):
    """
    An implementation of the RPC server for parsing and returning XMLRPC objects.

    >>> from pibble.api.server.webservice.rpc.jsonrpc import JSONRPCServer
    >>> import json
    >>> from collections import namedtuple
    >>> Request = namedtuple("Request", ["body"])
    >>> add = lambda a, b: a + b
    >>> server = JSONRPCServer()
    >>> r = server.register("add")(add) # We catch the response, as the register and sign methods return the function itself
    >>> r = server.sign_request(int, int)(add)
    >>> r = server.sign_response(int)(add)
    >>> request = json.dumps({"jsonrpc": "2.0", "method": "add", "params": [1, 2], "id": 1})
    >>> method, args, kwargs = server.parse_method_call(request)
    >>> server.dispatch(method, *args, **kwargs)
    3
    >>> pow = lambda base, exponent = 2: base ** exponent
    >>> r = server.register("exponentiate")(pow)
    >>> r = server.sign_named_request(base = int, exponent = 2)(pow)
    >>> r = server.sign_response(int)(pow)
    >>> request = json.dumps({"jsonrpc": "2.0", "method": "exponentiate", "params": {"base": 2, "exponent": 3}, "id": 2})
    >>> method, args, kwargs = server.parse_method_call(request)
    >>> server.dispatch(method, *args, **kwargs)
    8
    """

    @staticmethod
    def map_typename(_type: Type) -> str:
        """
        Takes a python type and turns it into a string version of it.

        >>> from pibble.api.server.webservice.rpc.jsonrpc import JSONRPCServer
        >>> from pibble.util.helpers import expect_exception
        >>> JSONRPCServer.map_typename(int)
        'int'
        >>> JSONRPCServer.map_typename(list)
        'array'
        >>> expect_exception(TypeError)(lambda: JSONRPCServer.map_typename(type(lambda x: x)))

        :param _type Type: The type.
        :returns str: The typename of the object.
        :raises TypeError: When no type information is available.
        """
        typename = {
            int: "int",
            float: "float",
            datetime.datetime: "string",
            bytes: "string",
            str: "string",
            list: "array",
            dict: "object",
            bool: "boolean",
            type(None): "null",
        }.get(_type, None)

        if typename is None:
            raise TypeError(
                "Cannot determine typename from type '{0}'.".format(_type.__name__)
            )
        return typename

    @staticmethod
    def parse_method_call(body: str) -> tuple[str, Optional[list], Optional[dict]]:
        """
        Takes a string JSON body, and parses it to find the method name and parameters.

        >>> import json
        >>> from pibble.api.server.webservice.rpc.jsonrpc import JSONRPCServer
        >>> JSONRPCServer.parse_method_call(json.dumps({"jsonrpc": "2.0", "method": "add", "params": [1, 2]}))
        ('add', [1, 2], {})
        >>> JSONRPCServer.parse_method_call(json.dumps({"jsonrpc": "2.0", "method": "pow", "params": {"base": 2, "exponent": 3}}))
        ('pow', [], {'base': 2, 'exponent': 3})

        :param body str: The body of a request.
        :returns tuple: A three-tuple of (str, list, dict), the first of which is the method name, the second is a list of all parsed parameters if positional parameters are sent, the third is a dict of all parsed parameters if named parameters are sent.
        :raises pibble.api.exceptions.BadRequestError: When the method name is not present, or the json rpc specifier is not present.
        :raises json.decoder.JSONDecodeError: When the JSON is not well-formed.
        """
        request = json.loads(body)
        if request.get("jsonrpc", None) != "2.0":
            raise BadRequestError(
                "Missing JSONRPC specifier. Must be present and set to '2.0'."
            )
        if "method" not in request:
            raise BadRequestError("Missing method name in request.")
        params = request.get("params", None)
        if params is None:
            return request["method"], [], {}
        elif type(params) is dict:
            params = Serializer.deserialize(params)
            return request["method"], [], params
        elif type(params) is list:
            params = Serializer.deserialize(params)
            return request["method"], params, {}
        else:
            raise BadRequestError(
                "Bad 'params' format. Must be object or array, got {0} instead.".format(
                    type(params).__name__
                )
            )

    def format_response(self, result: Any, request: Request, response: Response) -> str:
        """
        Formats a method response from the dispatcher.

        :param response object: The response from the method.
        :param request webob.Request: The request from the dispatcher.
        :returns str: The response.
        """
        if result is not None:
            id = json.loads(request.body).get("id", None)
            if id is not None:
                return decode(
                    json.dumps(
                        {"jsonrpc": "2.0", "result": result, "id": id},
                        default=JSONRPCSerializer.serialize,
                    )
                )
        return ""

    def format_exception(
        self, exception: Exception, request: Request, response: Response
    ) -> str:
        """
        Formats an exception into a dict.

        :param ex exception: The exception thrown.
        :returns str: The formatted exception response.
        """
        code = -32500
        if isinstance(exception, json.decoder.JSONDecodeError):
            code = -32700
        if isinstance(exception, UnsupportedMethodError):
            code = -32601
        if isinstance(exception, BadRequestError):
            code = -32600
        return decode(
            json.dumps(
                {"jsonrpc": "2.0", "code": code, "message": str(exception)},
                default=JSONRPCSerializer.serialize,
            )
        )

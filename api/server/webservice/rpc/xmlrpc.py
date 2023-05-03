import datetime
import base64
import sys
import lxml.etree as ET

from webob import Request, Response
from typing import Type, Iterable, Any, Optional

from lxml.builder import E
from pibble.api.server.webservice.rpc.base import RPCServerBase
from pibble.api.exceptions import UnsupportedMethodError, BadRequestError
from pibble.util.strings import decode


class XMLRPCServer(RPCServerBase):
    """
    An implementation of the RPC server for parsing and returning XMLRPC objects.

    >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
    >>> import lxml.etree as ET
    >>> from lxml.builder import E
    >>> add = lambda a, b: a + b
    >>> server = XMLRPCServer()
    >>> r = server.register("add")(add) # We catch the response, as the register and sign methods return the function itself
    >>> r = server.sign_request(int, int)(add)
    >>> r = server.sign_response(int)(add)
    >>> request = ET.tostring(E.methodCall(E.methodName("add"), E.params(E.param(E.value(E.int("1"))), E.Param(E.value(E.int("2"))))))
    >>> method, args, kwargs = server.parse_method_call(request)
    >>> server.dispatch(method, *args, **kwargs)
    3
    """

    @staticmethod
    def map_typename(_type: Type) -> str:
        """
        Takes a python type and turns it into a string version of it.

        >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
        >>> from pibble.util.helpers import expect_exception
        >>> XMLRPCServer.map_typename(int)
        'int'
        >>> XMLRPCServer.map_typename(list)
        'array'
        >>> expect_exception(TypeError)(lambda: XMLRPCServer.map_typename(type(None)))

        :param _type Type: The type.
        :returns str: The typename of the object.
        :raises TypeError: When no type information is available.
        """
        typename = {
            int: "int",
            float: "double",
            datetime.datetime: "dateTime.iso8601",
            bytes: "base64",
            str: "string",
            list: "array",
            dict: "struct",
            bool: "boolean",
        }.get(_type, None)

        if typename is None:
            raise TypeError(
                "Cannot determine typename from type '{0}'.".format(_type.__name__)
            )
        return typename

    @staticmethod
    def format_parameter(parameter: Any) -> ET._Element:
        """
        Formats a single datum into a <parameter/> node.

        >>> import lxml.etree as ET
        >>> import datetime
        >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
        >>> ET.tostring(XMLRPCServer.format_parameter("foo"))
        b'<param><value><string>foo</string></value></param>'
        >>> ET.tostring(XMLRPCServer.format_parameter(5))
        b'<param><value><int>5</int></value></param>'
        >>> ET.tostring(XMLRPCServer.format_parameter([datetime.datetime(2018, 1, 1, 0, 0, 0)]))
        b'<param><value><array><data><value><dateTime.iso8601>20180101T00:00:00</dateTime.iso8601></value></data></array></value></param>'
        >>> ET.tostring(XMLRPCServer.format_parameter({"bar": False}))
        b'<param><value><struct><member><value><boolean>0</boolean></value><name>bar</name></member></struct></value></param>'

        :param parameter object: Any value of the acceptable list of value types (see :class:pibble.api.server.webservice.rpc.xmlrpc.XMLRPCServer)
        :return lxml.etree._Element: The <parameter/> element.
        :raises pibble.api.exceptions.BadRequestError: When the parameter is not a known RPC type.
        """

        def _format_parameter(
            value: Any, name: Optional[str] = None
        ) -> Iterable[ET._Element]:
            def _format_value(p: Any) -> ET._Element:
                if isinstance(p, type):
                    return E.value(E.string(XMLRPCServer.map_typename(p)))
                elif isinstance(p, bool):
                    return E.value(E.boolean("1" if p else "0"))
                elif isinstance(p, int):
                    return E.value(E.int(str(p)))
                elif isinstance(p, str):
                    return E.value(E.string(p))
                elif isinstance(p, bytes):
                    return E.value(
                        E.base64(base64.b64encode(p).decode(sys.getdefaultencoding()))
                    )
                elif isinstance(p, float):
                    return E.value(E.double(str(p)))
                elif isinstance(p, datetime.datetime):
                    return E.value(E("dateTime.iso8601", p.strftime("%Y%m%dT%H:%M:%S")))
                elif isinstance(p, list) or isinstance(p, tuple):
                    # Have to be clunky as we can't unpack list comprehensions
                    dnode = E.data()
                    for l in p:
                        dnode.append(*_format_parameter(l))
                    return E.value(E.array(dnode))
                elif isinstance(p, dict):
                    return E.value(
                        E.struct(*[E.member(*_format_parameter(p[k], k)) for k in p])
                    )
                raise BadRequestError(
                    "Cannot encode type {0} into XMLRPC response.".format(
                        type(p).__name__
                    )
                )

            def _format_name(n: Any) -> ET._Element:
                return E.name(str(n))

            if name is not None:
                return (_format_value(value), _format_name(name))
            return (_format_value(value),)

        return E.param(*_format_parameter(parameter))

    @staticmethod
    def format_parameters(*parameters: Any) -> ET._Element:
        """
        Formats an n-tuple of parameters into a single <params/> node.

        >>> import lxml.etree as ET
        >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
        >>> ET.tostring(XMLRPCServer.format_parameters())
        b'<params/>'

        :param parameters tuple: Any number of parameters.
        :returns lxml.etree._Element: The <params/> node.
        """
        return E.params(
            *[XMLRPCServer.format_parameter(parameter) for parameter in parameters]
        )

    @staticmethod
    def parse_method_call(body: str) -> tuple[str, Optional[list], Optional[dict]]:
        """
        Takes a string XML body, and parses it to find the methodName and params.

        >>> import lxml.etree as ET
        >>> from lxml.builder import E
        >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
        >>> XMLRPCServer.parse_method_call(ET.tostring(E.methodCall(E.methodName("my_method"))))
        ('my_method', None, None)

        :param body str: The body of a request.
        :returns tuple: A three-tuple of (str, list, dict), the first of which is the method name, the second is a list of all parsed parameters. The third is returned as an empty dictionary, as XMLRPC does not support named parameters.
        :raises pibble.api.exceptions.BadRequestError: When the methodName is not present, or the XML is not well-formed.
        :raises lxml.etree.XMLSyntaxError: When the XML is not well-formed.
        """
        root = ET.XML(body)
        if root.tag != "methodCall":
            raise BadRequestError(
                "Invalid XML document root tag '{0}'.".format(root.tag)
            )
        method_name_node = root.find("methodName")
        parameter_node = root.find("params")
        if method_name_node is None:
            raise BadRequestError("No methodName node in methodCall request.")
        method_name = method_name_node.text
        if parameter_node is None:
            return method_name, None, None
        parameters = XMLRPCServer.parse_parameters(parameter_node)
        if len(parameters) == 1 and isinstance(parameters[0], dict):
            kwargs = parameters[0]
            parameters = []
        else:
            kwargs = {}
        return method_name, parameters, kwargs

    @staticmethod
    def parse_parameters(node: ET._Element) -> Any:
        """
        Takes the <params/> node from a request, then returns a list of the parsed parameters.

        >>> import lxml.etree as ET
        >>> from lxml.builder import E
        >>> from pibble.api.server.webservice.rpc.xmlrpc import XMLRPCServer
        >>> XMLRPCServer.parse_parameters(E.params(E.param(E.value(E.int("4")))))
        [4]
        >>> XMLRPCServer.parse_parameters(E.params(E.param(E.value(E.int("4"))), E.param(E.value(E.array(E.data(E.value(E.string("foo"))))))))
        [4, ['foo']]
        >>> XMLRPCServer.parse_parameters(E.params(E.param(E.value(E.struct(E.member(E.name("bar"), E.value(E.string("baz"))))))))
        [{'bar': 'baz'}]

        :param node lxml.etree._Element: The <params/> node from the request.
        :returns list: A list of all parameters in a request.
        :raises pibble.api.exceptions.BadRequestError: When the type of the value is incorrect.
        """

        def parse_parameter(param_node: ET._Element) -> Any:
            value = param_node.find("value")
            value_node = value[0]

            def _parse_value(value_node: ET._Element) -> Any:
                if value_node.tag == "value":
                    return _parse_value(value_node[0])
                elif value_node.tag == "int" or value_node.tag == "i4":
                    return int(value_node.text)
                elif value_node.tag == "boolean":
                    return int(value_node.text) == 1
                elif value_node.tag == "double":
                    return float(value_node.text)
                elif value_node.tag == "base64":
                    return base64.b64decode(value_node.text)
                elif value_node.tag == "dateTime.iso8601":
                    return datetime.datetime.strptime(
                        "%Y%m%dT%H:%M:%S", value_node.text
                    )
                elif value_node.tag == "string":
                    return value_node.text
                elif value_node.tag == "array":
                    return [_parse_value(n) for n in value_node[0] if n.tag == "value"]
                elif value_node.tag == "struct":
                    return dict(
                        [
                            (member.find("name").text, parse_parameter(member))
                            for member in value_node
                        ]
                    )
                raise BadRequestError(
                    "Unknown value type '{0}'.".format(value_node.tag)
                )

            return _parse_value(value_node)

        return [parse_parameter(param) for param in node]

    def format_response(self, result: Any, request: Request, response: Response) -> str:
        """
        Formats a method response from the dispatcher.

        :param response object: The response from the method.
        :returns str: The <methodResponse/> node.
        """
        if result is None:
            return decode(ET.tostring(E.methodResponse(E.params())))
        return decode(
            ET.tostring(E.methodResponse(XMLRPCServer.format_parameters(result)))
        )

    def format_exception(
        self, exception: Exception, request: Request, response: Response
    ) -> str:
        """
        Formats an exception into a <fault/> node.

        :param ex exception: The exception thrown.
        :return str: The <fault/> node.
        """
        code = -32500
        if isinstance(exception, ET.XMLSyntaxError):
            code = -32700
        if isinstance(exception, UnsupportedMethodError):
            code = -32601
        if isinstance(exception, BadRequestError):
            code = -32600
        return decode(
            ET.tostring(
                E.methodResponse(
                    E.fault(
                        XMLRPCServer.format_parameter(
                            {"faultCode": code, "faultString": str(exception)}
                        )[0]
                    )
                )
            )
        )

import sys
import base64
import datetime
import lxml.etree as ET
from lxml.builder import E
from pibble.api.client.webservice.rpc.base import RPCClientBase
from pibble.api.exceptions import (
    BadRequestError,
    BadResponseError,
    UnknownError,
    UnsupportedMethodError,
)
from typing import Type, Any, Optional


class XMLRPCClient(RPCClientBase):
    """
    An implementation of an XML RPC client.

    We can't do an all-encompassing doctest here, as it relies on an externally reachable server.
    """

    @staticmethod
    def format_parameter(parameter: Any) -> ET._Element:
        """
        Formats a single datum into a <parameter/> node.

        >>> import lxml.etree as ET
        >>> import datetime
        >>> from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
        >>> ET.tostring(XMLRPCClient.format_parameter("foo"))
        b'<param><value><string>foo</string></value></param>'
        >>> ET.tostring(XMLRPCClient.format_parameter(5))
        b'<param><value><int>5</int></value></param>'
        >>> ET.tostring(XMLRPCClient.format_parameter([datetime.datetime(2018, 1, 1, 0, 0, 0)]))
        b'<param><value><array><data><value><dateTime.iso8601>20180101T00:00:00</dateTime.iso8601></value></data></array></value></param>'
        >>> ET.tostring(XMLRPCClient.format_parameter({"bar": False}))
        b'<param><value><struct><member><value><boolean>0</boolean></value><name>bar</name></member></struct></value></param>'

        :param parameter object: Any value of the acceptable list of value types (see :class:`pibble.api.client.webservice.rpc.xmlrpc.XMLRPCClient`)
        :return lxml.etree._Element: The <parameter/> element.
        :raises pibble.api.exceptions.BadRequestError: When the parameter is not a known RPC type.
        """

        def _format_parameter(value: Any, name: Optional[str] = None) -> ET._Element:
            def _format_value(p: Any) -> ET._Element:
                if isinstance(p, bool):
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
    def map_typename(typename: str) -> Type:
        """
        Takes a string typename ("string", "float", etc.) and turns it into a python type.

        >>> from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
        >>> from pibble.util.helpers import expect_exception
        >>> XMLRPCClient.map_typename("int")
        <class 'int'>
        >>> XMLRPCClient.map_typename("array")
        <class 'list'>
        >>> expect_exception(TypeError)(lambda: XMLRPCClient.map_typename("null"))

        :param typename str: The typname.
        :returns Type: The type of the object.
        :raises TypeError: When no type information is available.
        """
        _type = {
            "int": int,
            "double": float,
            "dateTime.iso8601": datetime.datetime,
            "base64": bytes,
            "string": str,
            "array": list,
            "struct": dict,
            "boolean": bool,
        }.get(typename, None)

        if _type is None:
            raise TypeError("Cannot determine type from name '{0}'.".format(typename))
        return _type

    @staticmethod
    def format_parameters(*parameters: Any) -> ET._Element:
        """
        Formats an n-tuple of parameters into a single <params/> node.

        >>> import lxml.etree as ET
        >>> from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
        >>> ET.tostring(XMLRPCClient.format_parameters())
        b'<params/>'

        :param parameters tuple: Any number of parameters.
        :returns lxml.etree._Element: The <params/> node.
        """
        return E.params(
            *[XMLRPCClient.format_parameter(parameter) for parameter in parameters]
        )

    def format_request(
        self, method_name: str, *args: Any, **kwargs: Any
    ) -> ET._Element:
        """
        Formats a request with method_name and *args into XML syntax.

        >>> from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
        >>> XMLRPCClient.format_request(None, "print", "my_message")
        b'<methodCall><methodName>print</methodName><params><param><value><string>my_message</string></value></param></params></methodCall>'

        :param methodName str: The method to call.
        :param args tuple: The parameters to pass into the method.
        """

        base = E.methodCall(E.methodName(method_name))
        if args:
            base.append(XMLRPCClient.format_parameters(*args))
        elif kwargs:
            base.append(XMLRPCClient.format_parameters(kwargs))
        return ET.tostring(base)

    @staticmethod
    def parse_parameters(node: ET._Element) -> list:
        """
        Takes the <params/> node from a request, then returns a list of the parsed parameters.

        >>> import lxml.etree as ET
        >>> from lxml.builder import E
        >>> from pibble.api.client.webservice.rpc.xmlrpc import XMLRPCClient
        >>> XMLRPCClient.parse_parameters(E.params(E.param(E.value(E.int("4")))))
        [4]
        >>> XMLRPCClient.parse_parameters(E.params(E.param(E.value(E.int("4"))), E.param(E.value(E.array(E.data(E.value(E.string("foo"))))))))
        [4, ['foo']]
        >>> XMLRPCClient.parse_parameters(E.params(E.param(E.value(E.struct(E.member(E.name("bar"), E.value(E.string("baz"))))))))
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

    def format_response(self, response: str) -> Any:
        try:
            node = ET.XML(response)
        except ET.XMLSyntaxError:
            raise BadResponseError(
                "Received a response from the request, but was unable to parse it."
            )
        if node.tag == "fault":
            try:
                fault = XMLRPCClient.parse_parameters(E.params(node[0]))[0]
                code = fault["faultCode"]
                msg = fault["faultString"]
                if code == -32700:
                    raise BadRequestError(
                        "The request to the server was not well-formed: {0}".format(msg)
                    )
                elif code == -32601:
                    raise UnsupportedMethodError(
                        "The server did not understand the method called: {0}".format(
                            msg
                        )
                    )
                elif code == -32600:
                    raise BadRequestError(
                        "The request to the server was understood, but incorrect: {0}".format(
                            msg
                        )
                    )
                else:
                    raise UnknownError(
                        "An unhandle fault code ({0}) was received. Message: {1}".format(
                            code, msg
                        )
                    )
            except (IndexError, KeyError):
                raise BadResponseError(
                    "Received a fault response from the request, but was unable to parse it."
                )
        response_parts = XMLRPCClient.parse_parameters(node[0])
        if len(response_parts) == 1:
            return response_parts[0]
        return response_parts

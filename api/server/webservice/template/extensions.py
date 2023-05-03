from __future__ import annotations
import math
import jinja2.exceptions

from jinja2 import nodes
from jinja2.ext import Extension
from jinja2.parser import Parser

from typing import Callable, Any, Union, List

from pibble.api.base import APIBase
from pibble.api.configuration import APIConfiguration


class ExtensionBase:
    getConfiguration: Callable[[], APIConfiguration]
    getServer: Callable[[], APIBase]


class ContextExtensionBase(ExtensionBase, Extension):
    """
    A class for extending context-based processors.

    A context processor starts with a {% tag %} and ends with and {% endtag %}. Within
    that context will be a string, the result of all nested context expressions, which
    can then be processed.

    When making a context extension, you should extend the __call__ function. Take note
    of the method signature, as to get the inner content of context you must call `caller()`.

    These can take any number of arguments, but take care to use valid jinja2 expressions.

    >>> from pibble.api.server.webservice.template.extensions import ContextExtensionBase
    >>> import jinja2
    >>> environment = jinja2.Environment(extensions = [ContextExtensionBase])
    >>> environment.from_string("{% context_extension_base %}my context{% endcontext_extension_base %}").render()
    ''
    """

    tags = {"context_extension_base"}

    def parse(self, parser: Parser) -> nodes.Node:
        line = next(parser.stream).lineno
        context = nodes.ContextReference()
        args: List[Any] = [context]

        while True:
            try:
                args.append(parser.parse_expression())
            except jinja2.exceptions.TemplateSyntaxError:
                break

        body = parser.parse_statements(
            ("name:end{0}".format(list(self.tags)[0]),), drop_needle=True
        )
        return nodes.CallBlock(
            self.call_method("_extension_callback", args), [], [], body
        ).set_lineno(line)

    def _extension_callback(
        self, context: Any, *args: Any, caller: Callable[[], str] = lambda: ""
    ) -> str:
        return self(context, *args, caller=caller)

    def __call__(
        self, context: Any, *args: Any, caller: Callable[[], str] = lambda: ""
    ) -> str:
        return ""


class StatementExtensionBase(ExtensionBase, Extension):
    """
    This class extends statements.

    Statements are employed similar to contexts, but without a nested caller and
    without and end tag - simply {% statement %}.

    As before, extend to __call__ function.

    >>> from pibble.api.server.webservice.template.extensions import StatementExtensionBase
    >>> import jinja2
    >>> environment = jinja2.Environment(extensions = [StatementExtensionBase])
    >>> environment.from_string("Add result here: {% statement_extension_base %}").render()
    'Add result here: '
    """

    tags = {"statement_extension_base"}

    def parse(self, parser: Parser) -> nodes.Node:
        line = next(parser.stream).lineno
        args = []
        while True:
            try:
                args.append(parser.parse_expression())
            except jinja2.exceptions.TemplateSyntaxError:
                break
        return nodes.Output(
            [self.call_method("_extension_callback", args, lineno=line)], lineno=line
        )

    def _extension_callback(self, *args: Any) -> str:
        return self(*args)

    def __call__(self, *args: Any) -> str:
        return ""


class TestExtensionBase(ExtensionBase):
    """
    This class extends tests.

    Tests are done using the "is" operator, for example, {% if var is prime %}{{ var }} is prime{% endif %}.

    The __call__ function will always get at least one argument, the left-hand side of the "is" operator. You _can_ have other arguments passed.

    >>> from pibble.api.server.webservice.template.extensions import TestExtensionBase
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> TestExtensionBase.assign(environment)
    >>> environment.from_string("{% if var is test_extension_base %}{{ var }}{% endif %}").render(var = "foo")
    ''
    """

    name = "test_extension_base"

    @classmethod
    def assign(cls, environment: jinja2.Environment) -> None:
        environment.tests[cls.name] = cls()  # type: ignore

    def __call__(self, var: Any, *args: Any) -> bool:
        return False


class FilterExtensionBase(ExtensionBase):
    """
    An extension for filters.

    Filters are executed using the pipe `|` syntax, and will always take one vargument - the
    previous variable in the filter chain.

    >>> from pibble.api.server.webservice.template.extensions import FilterExtensionBase
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> FilterExtensionBase.assign(environment)
    >>> template = environment.from_string("{{ var|filter_extension_base }}")
    >>> template.render(var = "foo")
    'foo'
    """

    name = "filter_extension_base"

    @classmethod
    def assign(cls, environment: jinja2.Environment) -> None:
        environment.filters[cls.name] = cls()

    def __call__(self, var: Any) -> Any:
        return var


class FunctionExtensionBase(ExtensionBase):
    """
    An extension for functions.

    These are completely open-ended, but are made always available using the
    global environment namespace.

    >>> from pibble.api.server.webservice.template.extensions import FunctionExtensionBase
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> FunctionExtensionBase.assign(environment)
    >>> template = environment.from_string("{{ function_extension_base(var) }}")
    >>> template.render(var = "foo")
    'foo'
    """

    name = "function_extension_base"

    @classmethod
    def assign(cls, environment: jinja2.Environment) -> None:
        environment.globals[cls.name] = cls()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if args:
            return args[0]
        return None


class ExampleFunctionExtension(FunctionExtensionBase):
    """
    >>> from pibble.api.server.webservice.template.extensions import ExampleFunctionExtension
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> ExampleFunctionExtension.assign(environment)
    >>> environment.from_string("{{ square(var) }}").render(var = 2)
    '4'
    >>> environment.from_string("{{ square(square(var)) }}").render(var = 2)
    '16'
    """

    name = "square"

    def __call__(self, var: Union[int, float]) -> Union[int, float]:
        return var**2


class ExampleFilterExtension(FilterExtensionBase):
    """
    >>> from pibble.api.server.webservice.template.extensions import ExampleFilterExtension
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> ExampleFilterExtension.assign(environment)
    >>> environment.from_string("{{ var|square }}").render(var = 2)
    '4'
    >>> environment.from_string("{{ var|square|square }}").render(var = 2)
    '16'
    """

    name = "square"

    def __call__(self, var: Union[int, float]) -> Union[int, float]:
        return var**2


class ExampleTestExtension(TestExtensionBase):
    """
    >>> from pibble.api.server.webservice.template.extensions import ExampleTestExtension
    >>> import jinja2
    >>> environment = jinja2.Environment()
    >>> ExampleTestExtension.assign(environment)
    >>> template = environment.from_string("{% if var is prime %}{{ var }} is prime{% else %}{{ var }} is not prime{% endif %}")
    >>> template.render(var = 5)
    '5 is prime'
    >>> template.render(var = 6)
    '6 is not prime'
    """

    name = "prime"

    @classmethod
    def __call__(self, var: Any, *args: Any) -> bool:
        if var == 2:
            return True
        for i in range(2, int(math.ceil(math.sqrt(var))) + 1):
            if var % i == 0:
                return False
        return True


class ExampleContextExtension(ContextExtensionBase):
    """
    >>> from pibble.api.server.webservice.template.extensions import ExampleContextExtension
    >>> import jinja2
    >>> environment = jinja2.Environment(extensions = [ExampleContextExtension])
    >>> environment.from_string("{% example_context 'prefix' %}foo{% endexample_context %} bar {% example_context %}baz{% endexample_context %}").render()
    'prefixFOO bar BAZ'
    """

    tags = {"example_context"}

    def __call__(
        self, context: Any, *args: Any, caller: Callable[[], str] = lambda: ""
    ) -> str:
        result = caller().upper()
        if len(args) == 1:
            result = args[0] + result
        return result


class ExampleStatementExtension(StatementExtensionBase):
    """
    >>> from pibble.api.server.webservice.template.extensions import ExampleStatementExtension
    >>> import jinja2
    >>> environment = jinja2.Environment(extensions = [ExampleStatementExtension])
    >>> environment.from_string("{% example_statement 5 %}{% example_statement 5 'n' %}").render()
    'xxxxxnnnnn'
    """

    tags = {"example_statement"}

    def __call__(self, *args: Any) -> str:
        if len(args) == 1:
            char, n = "x", int(args[0])
        else:
            char, n = args[1], int(args[0])
        return char * n

from __future__ import annotations

from re import sub
from functools import partial
from typing import (
    Type,
    Callable,
    Any,
    Optional,
    Sequence,
    Mapping,
    Union,
    Dict,
    List,
    cast,
)

from pibble.api.base import APIBase
from pibble.api.server.webservice.base import MethodBasedWebServiceAPIServerBase
from pibble.util.helpers import resolve


class MetaTestClass:
    def add(self, a: int, b: int) -> int:
        return a + b


class MetaFunction:
    """
    This allows for defining short functions within a service.

    Permitted languages are presently javascript and python. Anything that exposes this interface
    SHOULD NOT allow for python MetaFunction definition, but javascript is easy enough to contextualize.

    >>> from pibble.api.meta.base import MetaFunction
    >>> func = MetaFunction("python", "result = 1")
    >>> func()
    1
    >>> func2 = MetaFunction("python", "result = sum([arg for arg in args if isinstance(arg, int)])")
    >>> func2(1, 2, 3)
    6
    >>> func3 = MetaFunction("python", "'I forgot to set a variable in here'")
    >>> func3() # Expect nothing

    :param language str: The language.
    :param script str: The script to call.
    :param context Any: Any context to pass to the function.
    """

    def __init__(
        self, language: str, script: str, register: bool = False, **context: Any
    ):
        self.language = language
        self.script = script
        self.context = context
        self.register = register

    def passthrough(self, **kwargs: Any) -> None:
        """
        Adds more context to the call.
        """
        self.context.update(kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        service = kwargs.get("service", None)
        if self.language == "python":
            environment = {
                **self.context,
                **{
                    "args": args,
                    "kwargs": kwargs,
                    "service": None if not service else service.instance,
                },
            }
            exec(self.script, globals(), environment)
            if "result" in environment:
                return environment["result"]
        # elif self.language == "javascript":
        #  context = pyduktape.DuktapeContext()
        #  context.set_globals(service = None if not service else service.instance, args = args, kwargs = kwargs)
        #  context.set_globals(**self.context)
        #  return context.eval_js(self.script)
        else:
            raise TypeError(
                "Unsupported scripting language '{0}'.".format(self.language)
            )


class MetaService:
    """
    The MetaService class does the heavy lifting for definition a service.

    Services can be either clients or servers, and _most_ functions will be partially imported into this object. If the function overrides any functions provided by MetaService (i.e., `instance` and `__introspect`), you'll need to use the __call__ syntax.

    >>> from pibble.api.meta.base import MetaService, MetaTestClass
    >>> service = MetaService( "myclass", [ "pibble.api.base.APIBase", MetaTestClass ] )
    >>> service.add(1, 2)
    3
    >>> service("add", 1, 2)
    3

    :param name str: The name of the meta service. This is used for type definition.
    :param classes list: The list of classes to inherit. If these are strings, they will be resolved.
    :param configuration dict: The configuration to pass into the instances `configure()` function.
    :param functions dict: A dictionary of `MetaFunction`s.
    """

    _class_instance: Optional[APIBase]

    def __init__(
        self,
        name: str,
        classes: Sequence[Union[str, Type]],
        configuration: dict = {},
        functions: Mapping[str, Union[Callable, MetaFunction]] = {},
    ):
        self.name = name
        self.classes = classes
        self.configuration = configuration
        self.functions = functions
        self._class_instance = None

    @property
    def instance(self) -> APIBase:
        if getattr(self, "_class_instance", None) is None:
            self._class_instance = cast(
                APIBase,
                type(
                    sub(r"[^0-9a-zA-Z]", "", self.name).title(),
                    tuple(
                        [
                            classname if type(classname) is type else resolve(classname)
                            for classname in self.classes
                        ]
                    ),
                    {},
                )(),
            )
            self._class_instance.configure(**self.configuration)
            if isinstance(self._class_instance, MethodBasedWebServiceAPIServerBase):
                for function in self.functions:
                    if getattr(self.functions[function], "register", False):
                        self._class_instance.register(function)(
                            self.functions[function]
                        )
        return cast(APIBase, self._class_instance)

    @instance.deleter
    def instance(self) -> None:
        if self._class_instance is not None:
            self._class_instance.destroy()
            self._class_instance = None

    def listMethods(self) -> List[str]:
        """
        Lists methods in the underlying layer.
        """
        functions = [func for func in self.functions.keys()]
        has_list_methods = getattr(self.instance, "listMethods", None) is not None
        if has_list_methods:
            try:
                functions += self.instance.listMethods()
            except NotImplementedError:
                has_list_methods = False
        if not has_list_methods:
            functions += [
                func
                for func in dir(self.instance)
                if callable(getattr(self.instance, func)) and not func.startswith("_")
            ]
        return list(set(functions))

    def __getitem__(self, method: str) -> Callable:
        """
        If a method name is present in the list of methods, return it.
        """
        if method in self.listMethods():
            return partial(self.__call__, method)
        raise KeyError(
            "Unknown or disallowed method '{0}' on class {1}.".format(
                method, type(self.instance).__name__
            )
        )

    def __getattr__(self, method: str) -> Callable:
        """
        Another shorthand for service[method].
        """
        return self[method]

    def destroy(self) -> None:
        """
        Destroys the service.
        """
        del self.instance

    def __call__(self, function_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Calls the function in the service. Always prioritizes `MetaFunction` first.
        """
        if function_name in self.functions:
            return self.functions[function_name](
                *args, **{**{"service": self}, **kwargs}
            )
        return getattr(self.instance, function_name)(*args, **kwargs)

    def __repr__(self) -> str:
        return "MetaService<{0}>".format(sub(r"[^0-9a-zA-Z]", "", self.name).title())


class MetaServiceFactory:
    """
    The MetaServiceFactory simply stores and creates metaservices.

    See :class:`pibble.api.meta.base.MetaService` for more information.
    """

    services: Dict[str, MetaService]

    def __init__(self) -> None:
        self.services = {}

    def __getattr__(self, name: str) -> MetaService:
        """
        A helpful syntax for getting services.

        >>> from pibble.api.meta.base import MetaServiceFactory
        >>> factory = MetaServiceFactory()
        >>> factory.define("myclass", ["pibble.api.base.APIBase"])
        MetaService<Myclass>
        >>> factory.myclass
        MetaService<Myclass>
        """

        return self.services[name]

    def define(
        self,
        name: str,
        classes: List[Union[Type, str]],
        configuration: dict = {},
        functions: Dict[str, Callable] = {},
    ) -> MetaService:
        """
        Defines a service.

        >>> from pibble.api.meta.base import MetaServiceFactory
        >>> factory = MetaServiceFactory()
        >>> factory.define("myclass", ["pibble.api.base.APIBase", "pibble.api.meta.base.MetaTestClass"])
        MetaService<Myclass>
        >>> factory.myclass("add", 1, 2)
        3
        >>> factory.myclass.add(2, 2)
        4
        >>> from pibble.api.meta.base import MetaFunction
        >>> from pibble.api.meta.base import MetaTestClass
        >>> from pibble.api.base import APIBase
        >>> add3 = MetaFunction("python", "result = args[0] + service.add(args[1], args[2])")
        >>> factory = MetaServiceFactory()
        >>> factory.define("myclass", [APIBase, MetaTestClass], {}, { "add3": add3 })
        MetaService<Myclass>
        >>> factory.myclass("add3", 1, 2, 3)
        6
        >>> factory.myclass.add3(4, 5, 6)
        15

        :param name str: The name of the class. Should be unique for each factory.
        :param classes list: The name of a class. Can be a string (which will be resolved), or a type.
        :param configuration dict: The configuration to pass into the .configure() function.
        :param functions dict: A dictionary of MetaFunctions. See :class:`pibble.api.meta.base.MetaFunction` for more information.
        """
        self.services[name] = MetaService(name, classes, configuration, functions)
        return self.services[name]

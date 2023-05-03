from __future__ import annotations

import sys
import os
import tempfile
import shutil
import copy

from typing import (
    Optional,
    Type,
    Callable,
    Any,
    Iterator,
    Iterable,
    Union,
    List,
    Dict,
    cast,
)
from types import ModuleType

from google.protobuf import symbol_database as SDB
from google.protobuf.message import Message

from grpc_tools import protoc

from pibble.util.log import logger
from pibble.api.exceptions import ConfigurationError, UnsupportedMethodError
from pibble.api.configuration import APIConfiguration


class GRPCRequest:
    fields: Dict[str, Any]

    def __init__(self, service: GRPCService, method: str, **kwargs: Any) -> None:
        self.service = service
        self.method = method
        for descriptor_method in self.service.descriptor.methods:
            if descriptor_method.name == self.method:
                self.descriptor = descriptor_method
                break
        if not hasattr(self, "descriptor"):
            raise UnsupportedMethodError("Unknown method '{0}'.".format(method))
        self.input = self.descriptor.input_type
        self.output = self.descriptor.output_type
        self.kwargs = kwargs
        self.fields = {}

    def __call__(self) -> Message:
        return cast(Message, self.input._concrete_class(**self.fields))


class GRPCResponse:
    fields: Dict[str, Any]

    def __init__(self, request: GRPCRequest) -> None:
        self.request = request
        self.fields = {}

    def load(self, message: Any) -> None:
        for field in self.request.output.fields:
            self.fields[field.name] = getattr(message, field.name)

    def __call__(self) -> Message:
        return cast(Message, self.request.output._concrete_class(**self.fields))


class GRPCConfiguration:
    """
    Finally, this class reads an API configuration and appropriately retrieves the
    necessary parts of a service.

    Required Configuration:
      - grpc.service - The name of the service to locate.
    One of the following:
      - grpc.compile - The directory of .proto files to compile.
      - grpc.directory - The directory of pre-compiled protocol files.

    Optional Configuration:
      - grpc.namespace - The namespace of the service. If not provided, the first service matching the service name will be taken. This can increase import time.
      - grpc.proto - The name of the .proto file that defines the service. When used in conjunction with namespace, this can greatly reduce searching time.

    :param configuration pibble.api.configuration.APIConfiguration: The API configuration.
    """

    def __init__(self, configuration: APIConfiguration) -> None:
        self.configuration = configuration

        compile_directory = configuration.get("grpc.compile", None)
        directory = configuration.get("grpc.directory", None)
        service_name = configuration.get("grpc.service", None)
        service_namespace = configuration.get("grpc.namespace", None)
        service_proto = configuration.get("grpc.proto", None)

        if not compile_directory and not directory:
            raise ConfigurationError(
                "One of 'grpc.compile' or 'grpc.directory' must be defined."
            )
        if not service_name:
            raise ConfigurationError("'grpc.service' must be defined.")

        if compile_directory:
            with GRPCCompiler(compile_directory) as directory:
                with GRPCImporter(directory) as module:
                    explorer = GRPCServiceExplorer(module)
                    self.service = explorer.find(
                        service_name, service_namespace, service_proto
                    )
        else:
            with GRPCImporter(directory) as module:
                explorer = GRPCServiceExplorer(module)
                self.service = explorer.find(
                    service_name, service_namespace, service_proto
                )


class GRPCService:
    """
    This class abstracts a gRPC "service" by getting the various classes needed to use it.

    :param qualified_name str: The fully qualified name of the service.
    :param name str: The short name of the service.
    :param namespace str: The namespace of the service.
    :param descriptor `google.protobuf.pyext._message.ServiceDescriptor: The descriptor, as compiled by protoc.
    :param servicer type: The servicer class type. Used for servers.
    :param stub type: The stub type. Used for clients.
    :param assigner callable: The callable function that applies a servicer to a transport.
    """

    def __init__(
        self,
        qualified_name: str,
        name: str,
        namespace: str,
        descriptor: Any,
        servicer: Type,
        stub: Type,
        assigner: Callable,
    ) -> None:
        self.qualified_name = qualified_name
        self.name = name
        self.namespace = namespace
        self.descriptor = descriptor
        self.servicer = servicer
        self.assigner = assigner
        self.stub = stub
        self.messages = GRPCService.GRPCMessages()  # type: ignore

    def addMessage(self, message: Any) -> Any:
        """
        Adds messages to the message list after inspecting the descriptor for them.

        :param message `google.protobuf.pyext._message.MessageDescriptor`: the message description, compiled by protoc.
        """
        try:
            added = self.messages.add(message)  # type: ignore
        except Exception as ex:
            raise AttributeError(
                "Error adding message {0} to {1}: {2}".format(
                    message.name, self.name, str(ex)
                )
            )
        if added:
            logger.info(
                "Registering message {0} to service {1}".format(message.name, self.name)
            )
        return added

    class GRPCMessages:
        """
        This class holds the message objects added to a service.
        """

        messages: List[GRPCMessage]

        def __init__(self) -> None:
            self.messages = []

        def _find_by_name(self, name: str) -> List[GRPCMessage]:
            """
            Finds by a name.

            :param str name: The name of the message to find.
            :returns list: All messages matching this name. It's possible to have multiple.
            :raises KeyError: When a message cannot be found.
            """
            messages = [message for message in self.messages if message.name == name]
            if not messages:
                raise KeyError(name)
            return messages

        def _find_by_qualified_name(self, qualified_name: str) -> GRPCMessage:
            """
            Finds by a qualified name. Unlike `_find_by_name`, this can only have one result.

            :param str qualifier_name: The fully qualified message to find.
            :returns `pibble.api.helpers.googlerpc.GRPCService.GRPCMessages.GRPCMessage`: The message object.
            """
            for message in self.messages:
                if message.qualified_name == qualified_name:
                    return message
            raise KeyError(qualified_name)

        def get(self, name: str, namespace: Optional[str] = None) -> GRPCMessage:
            """
            Retrieves an item by name or qualified name.

            :param name str: The name. Required.
            :param namespace str: The namespace of the item. Optional.
            """
            if namespace is None:
                return self[name]
            else:
                return self._find_by_qualified_name("{0}.{1}".format(namespace, name))

        def __getitem__(self, item: str) -> GRPCMessage:
            """
            Retrieves an unqualified message name.

            :param item str: The item name.
            :raises KeyError: When not found, or ambiguous.
            """
            message = self._find_by_name(item)
            if len(message) > 1:
                raise KeyError(
                    "Name {0} is ambiguous, use `.get()` instead and pass one of {1}.".format(
                        item, ", ".join([msg.namespace for msg in message])
                    )
                )
            return message[0]

        def __getattr__(self, item: str) -> GRPCMessage:
            """
            A wrapper around self[item].
            """
            try:
                return self[item]
            except KeyError as ex:
                raise AttributeError(str(ex))

        def add(self, message: Any) -> bool:
            """
            Adds a message to this list. Called by the parent class.
            """
            namespace = ".".join(os.path.splitext(message.file.name)[0].split("/"))  # type: ignore
            qualified_name = "{0}.{1}".format(namespace, message.name)
            try:
                existing = self._find_by_qualified_name(qualified_name)
                return False
            except KeyError:
                self.messages.append(
                    GRPCService.GRPCMessages.GRPCMessage(self, message)
                )
                return True

        def __repr__(self) -> str:
            return "{0}({1})".format(
                type(self).__name__,
                ", ".join([message.name for message in self.messages]),
            )

        class GRPCMessage:
            """
            Holds various variables related to a message.

            Calling this object instantiates the concrete class below.
            """

            def __init__(self, parent: GRPCService.GRPCMessages, descriptor: Any):
                self.parent = parent
                self.descriptor = descriptor
                self.name = descriptor.name
                self.cls = descriptor._concrete_class
                self.namespace = ".".join(
                    os.path.splitext(descriptor.file.name)[0].split("/")
                )
                self.qualified_name = "{0}.{1}".format(self.namespace, self.name)

            def __repr__(self) -> str:
                field_descriptions = []
                for field in self.descriptor.fields:
                    if field.message_type is None:
                        typename = "<unknown>"
                        for name in dir(field):
                            if not name.startswith("TYPE"):
                                continue
                            if type(getattr(field, name)) is not int:
                                continue
                            if getattr(field, name) != field.type:
                                continue
                            typename = "<{0}>".format(
                                "_".join(name.split("_")[1:]).lower()
                            )
                            break
                        field_descriptions.append((field.name, typename))
                    else:
                        field_descriptions.append(
                            (field.name, str(self.parent.get(field.message_type.name)))
                        )
                return "{0}({1})".format(
                    self.name,
                    ", ".join(
                        [
                            "{0} = {1}".format(name, usage)
                            for name, usage in field_descriptions
                        ]
                    ),
                )

            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                return self.cls(*args, **kwargs)


class GRPCServiceExplorer:
    """
    This is the final destination of importing an entire gRPC module,
    i.e., a categorized and aliased list of the important services present
    within a gRPC module.

    :param module `pibble.api.helpers.googlerpc.GRPCModuleExplorer`: the module to search through.
    """

    services: List[GRPCService]

    def __init__(self, module: GRPCModuleExplorer) -> None:
        self.module = module
        self.services = []

    def find(
        self,
        service_name: str,
        namespace: Optional[str] = "",
        proto: Optional[str] = None,
    ) -> GRPCService:
        """
        Finds a service by name.

        :param service_name str: The name of the service.
        :param namespace str: The namespace to search through. This can be empty, if it's not namespaced.
        :param proto_file str: The proto file, optional. If it is unknown, all proto files will be looked through.
        :returns `pibble.api.helpers.googlerpc.GRPCService`: The final imported service.
        :raises KeyError: When the service name cannot be found.
        """
        if not service_name:
            raise AttributeError("Service name cannot be empty.")

        if namespace is None:
            namespace = ""

        for service in self.services:
            if service.name == service_name and service.namespace == namespace:
                return service

        database = SDB.Default()
        for grpc_module in iter(self.module):
            if grpc_module.namespace == namespace and grpc_module.name.endswith("grpc"):
                if proto is not None and grpc_module.proto != proto:
                    continue

                imported = grpc_module.module()
                logger.debug(
                    "Searching for service from proto file {0}".format(grpc_module.path)
                )

                db_proto = database.pool.FindFileByName(grpc_module.path)

                for name, proto_service in db_proto.services_by_name.items():
                    if namespace:
                        qualified_name = ".".join([namespace, grpc_module.proto, name])
                    else:
                        qualified_name = ".".join([grpc_module.proto, name])

                    logger.info("Inspection yielded service {0}".format(qualified_name))

                    grpc_service = GRPCService(
                        qualified_name,
                        name,
                        namespace,
                        proto_service,
                        getattr(imported, "{0}Servicer".format(name)),
                        getattr(imported, "{0}Stub".format(name)),
                        getattr(imported, "add_{0}Servicer_to_server".format(name)),
                    )

                    def inspect_message(message: Any) -> None:
                        if grpc_service.addMessage(message):
                            for field in message.fields:
                                if field.message_type:
                                    inspect_message(field.message_type)

                    for method in proto_service.methods:
                        if method.input_type:
                            inspect_message(method.input_type)
                        if method.output_type:
                            inspect_message(method.output_type)

                    self.services.append(grpc_service)

                    if grpc_service.name == service_name:
                        return grpc_service

        raise KeyError(
            "Could not find service {0} with namespace {1}".format(
                service_name, namespace
            )
        )


class GRPCModule:
    """
    This class holds a module, including its path and fromlist.

    It is not actually imported until the `.module()` function is called.
    """

    def __init__(self, name: str, fromlist: List[str]):
        self.name = name
        self.fromlist = fromlist

        if self.name.endswith("pb2"):
            self.proto = "_".join(name.split("_")[:-1])
        elif self.name.endswith("pb2_grpc"):
            self.proto = "_".join(name.split("_")[:-2])

        self.namespace = ".".join(self.fromlist)
        self.proto_file = "{0}.proto".format(self.proto)
        self.path = "/".join(fromlist + [self.proto_file])

    def module(self) -> ModuleType:
        """
        Calls the underlying __import__ machinery to import the module.

        Note that this will perform other imports, which all pollute the namespace, so
        we should try our best to only import that which is necessary.
        """
        if not hasattr(self, "_module"):
            logger.info(
                "Importing gRPC Module {0}".format(
                    ".".join(self.fromlist + [self.name])
                )
            )
            self._module = __import__(
                ".".join(self.fromlist + [self.name]),
                locals(),
                globals(),
                fromlist=[".".join(self.fromlist)],
            )
        return self._module


class GRPCModuleExplorer:
    """
    This class holds all modules and submodules represented in a gRPC module.

    Submodules are, in turn, also GRPCModules, allowing for chaining of __getattr__ calls.
    """

    modules: Dict[str, GRPCModule]
    submodules: Dict[str, GRPCModuleExplorer]

    def __init__(self) -> None:
        self.modules = {}
        self.submodules = {}

    def find(self, path: str) -> Union[GRPCModule, GRPCModuleExplorer]:
        """
        Finds a module by dot-separated path.

        :param path str: The path, dot-separated, e.g. `google.ads.googleads.v2.services`.
        """
        path_parts = path.split(".")
        if len(path_parts) == 1:
            return self[path]
        result = self[path_parts[0]]
        if not isinstance(result, GRPCModuleExplorer):
            raise TypeError(f"{path} is a module, not a submodule.")
        return result.find(".".join(path_parts[1:]))

    def add(self, path: str, fromlist: List[str] = []) -> None:
        """
        This adds a .py file from the module into this object.

        This is invoking the __import__ machinery, and likely shouldn't be used except when
        being called from GRPCImporter.module.

        :param path str: The path of this file.
        :param fromlist list: The directories that had to be traversed from the initial module path to reach this file.
        """
        name = os.path.splitext(path)[0]
        self.modules[name] = GRPCModule(name, fromlist)

    def submodule(self, path: str) -> GRPCModuleExplorer:
        """
        This adds another GRPCModule within this one, so that
        importing can continue.
        """
        new = GRPCModuleExplorer()
        self.submodules[path] = new
        return new

    def clean(self) -> None:
        """
        Removes any submodules that have no modules.
        """
        for submodule in list(self.submodules.keys()):
            if (
                not self.submodules[submodule].modules
                and not self.submodules[submodule].submodules
            ):
                logger.debug("Removing empty submodule {0}".format(submodule))
                del self.submodules[submodule]
            else:
                self.submodules[submodule].clean()

    def __iter__(self) -> Iterator[GRPCModule]:
        """
        Iterates through all modules, depth first.
        """
        for module in self.modules.values():
            yield module
        for submodule in self.submodules:
            for module in self.submodules[submodule]:
                yield module

    def descriptors(self) -> Iterable[str]:
        """
        Iterates through all file descriptors presented by the module.
        """
        for filename in set([module.path for module in self.modules.values()]):
            yield filename
        for submodule in self.submodules:
            for filename in self.submodules[submodule].descriptors():
                yield filename

    def __str__(self) -> str:
        return "GRPCModule(modules = {0}, submodules = {1})".format(
            ", ".join(self.modules.keys()), ", ".join(self.submodules.keys())
        )

    def __getitem__(self, key: str) -> Union[GRPCModule, GRPCModuleExplorer]:
        """
        This returns modules in importance order.
        """
        if key in self.submodules:
            return self.submodules[key]
        elif key in self.modules:
            return self.modules[key]
        raise KeyError(key)

    def __getattr__(self, key: str) -> Union[GRPCModule, GRPCModuleExplorer]:
        """
        This is where we can chain together calls to get a module, i.e.,
        module.service_pb2.ServiceServicer.
        """
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class GRPCImporter:
    """
    Imports a directory of compiled GRPC files, and returns an explorer on that directory.

    Presents as a context manager, which modifies the system path on entry and returns it
    to the previous value on exit.

    :param directory str: The directory, in which the compiled _pb2 and _pb2_grpc files are.
    """

    def __init__(self, directory: str):
        self.directory = directory

    def __enter__(self) -> GRPCModuleExplorer:
        logger.info("Recursively importing gRPC Module at {0}".format(self.directory))
        self.path = copy.deepcopy(sys.path)
        sys.path.append(self.directory)

        module = GRPCModuleExplorer()

        def recurse(
            module: GRPCModuleExplorer, path: str, fromlist: List[str] = []
        ) -> None:
            for subpath in os.listdir(path):
                if os.path.isdir(os.path.join(path, subpath)):
                    recurse(
                        module.submodule(subpath),
                        os.path.join(path, subpath),
                        fromlist + [subpath],
                    )
                elif subpath.endswith(".py"):
                    module.add(subpath, fromlist)

        recurse(module, self.directory)
        module.clean()

        if not module.modules and not module.submodules:
            raise ImportError(
                "Could not import any gRPC modules within directory {0}.".format(
                    self.directory
                )
            )
        return module

    def __exit__(self, *args: Any) -> None:
        sys.path = self.path


class GRPCCompiler:
    """
    An on-the-fly gRPC compiler.

    Should not be used in production. This presents as a context manager, where entry is
    file copying and compilation, and exit removes it. Therefore, it should be imported during
    the context.

    :param directory str: The directory which contains the .proto files for compilation.
    :param protobuf str: The directory for the google protobuf libraries. This should be in /usr/local/include, if installed correctly.
    :returns `pibble.api.helpers.googlerpc.GRPCModule`: The compiled module.
    """

    def __init__(self, directory: str, protobuf: str = "/usr/include"):
        self.directory = os.path.abspath(os.path.realpath(directory))
        self.protobuf = os.path.abspath(os.path.realpath(protobuf))

    def __enter__(self) -> str:
        logger.info("On-the-fly compiling gRPC IDL at {0}".format(self.directory))
        if not os.path.exists(os.path.join(self.protobuf, "google")):
            raise IOError(
                "Cannot find Google protocol buffer IDL directory at {0}.".format(
                    os.path.join(self.protobuf, "google")
                )
            )

        self.indir = tempfile.mkdtemp()
        self.outdir = tempfile.mkdtemp()

        for path in os.listdir(self.directory):
            src = os.path.join(self.directory, path)
            dest = os.path.join(self.indir, path)

            if os.path.isdir(src):
                logger.debug("Copying subdirectory for compilation: {0}".format(src))
                shutil.copytree(src, dest)
            else:
                logger.debug("Copying file for compilation: {0}".format(src))
                shutil.copy(src, dest)

        for dirname, subdirs, filenames in os.walk(self.indir):
            for filename in filenames:
                if filename.endswith(".proto"):
                    logger.debug(
                        "Compiling gRPC IDL file {0}".format(
                            os.path.join(dirname, filename)
                        )
                    )
                    args = (
                        "",
                        "-I",
                        self.indir,
                        "-I",
                        "/usr/local/include",
                        "--python_out={0}".format(self.outdir),
                        "--grpc_python_out={0}".format(self.outdir),
                        os.path.join(dirname, filename),
                    )
                    protoc.main(args)

        return self.outdir

    def __exit__(self, *args: Any) -> None:
        try:
            shutil.rmtree(self.indir)
        except:
            pass
        try:
            shutil.rmtree(self.outdir)
        except:
            pass

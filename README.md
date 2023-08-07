# Pibble

The Pibble framework turbocharges Python web applications with a huge array of features and easy-to-use interface.

# Installation

The `pibble` package is available on PYPI. Simply run:

```
pip install pibble
```
# Features
## API Integration Layer

APIs are broken up into server and client modules.

### Server

All web server APIs should be extended from `pibble.api.server.webservice.base.WebServiceAPIServerBase`. For the most part, each implementation must only register some handlers using the `pibble.api.server.webservice.base.WebServiceAPIHandlerRegistry`, which will handle all requests using a method and path. A class is not recommended to use the parent handler function, as this will provider handlers for all classes in this module that extend from `pibble.api.webservice.base.WebServiceAPIServerBase`, instead defining their own. For example, if we simply wanted to serve files from a directory over HTTP, we could use something like this:

```python3
import os
from typing import Optional
from webob import Request, Response
from pibble.api.exceptions import NotFoundError
from pibble.api.server.webservice.base import (
    WebServiceAPIServerBase,
    WebServiceAPIHandlerRegistry
)

class HelloWorldServer(WebServiceAPIServerBase):
    """
    This class provides a single endpoint at the root URL displaying a simple message.
    It creates a handler registry, then uses the registries decorators to configure the handler.
    """
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.path("^$")
    @handlers.methods("GET")
    def hello_world(self, request: Request, response: Response) -> None:
        """
        Handles the request at the root and sends a simple message.
  
        :param request webob.Request: The request object.
        :param response webob.Response: The response object.
        """
        response.text = "<!DOCTYPE html><html lang='en_US'><body>Hello, world!</body></html>"

class SimpleFileServer(HelloWorldServer):
    """
    This class creates a more complicated handler than allows for downloading files.

    It also extends the class above, inheriting the handlers above.

    Classes should always name their handler registry 'handlers'. If you want to name your registry
    something else, you need to add a `get_handlers()` classmethod that returns the registry for it
    to be recognized by the dispatcher.
    """
    handlers = WebServiceAPIHandlerRegistry()
    base_directory = "/var/www/html"

    @handlers.path("(?P<file_path>.*)")
    @handlers.methods("GET")
    def retrieve_file(self, request: Request, response: Response, file_path: Optional[str] = None) -> None:
        """
        Handles the request by looking for the path in ``self.base_directory``.
  
        :param request webob.Request: The request object.
        :param response webob.Response: The response object.
        :param file_path str: The file path, captured from the URI.
        :throws: :class:`pibble.api.exceptions.NotFoundError`
        """
  
        file_path = os.path.join(self.base_directory, file_path)
        if not os.path.isfile(file_path):
            raise NotFoundError("Could not find file at {0}".format(file_path))
  
        response.body = open(file_path, "r").read()
```

The request and response parameters are webob.Request and webob.Response objects, respectively. See [The WebOb Documentation](https://docs.pylonsproject.org/projects/webob/en/stable/) for help with their usage. Note the method name does not matter, so use a naming schema relevant to your project.

Deploying the API can be done using anything that conforms to wsgi standards. For development, we can deploy a server using werkzeug or gunicorn, binding to a local port with a configured listening host. Using the above server definition, we can do this with::

```python
server = SimpleFileServer()
server.configure(server = {"driver": "werkzeug", "host": "0.0.0.0", "port": 9090})

# Serve synchronously
server.serve()

# Serve asynchronously
server.start()
# Use the server
server.stop()
```

For production, most servers will simply import a file and look for a globally-available `application` that conforms to WSGI standards. The easiest way to configure this is thusly:

```python
# wsgi.py
from mypackage.server import SimpleFileServer
server = SimpleFileServer()
application = server.wsgi()
```

Pointing something like Apache's `mod_wsgi` to this `wsgi.py` file will allow Pibble to be ran through Apache.

#### RPC

Using one of the RPC servers is as simple as defining functions and registering them to the server:

```python
from pibble.api.server.webservice.rpc.xml.server import XMLRPCServer

server = XMLRPCServer()

@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def add(x, y):
    return x + y

@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def subtract(x, y):
    return x - y

@server.register
@server.sign_request(int, int)
@server.sign_response(int)
def multiply(x, y):
    return x * y

@server.register
@server.sign_request(int, int)
@server.sign_response(float)
def divide(x, y):
    return x / y

server.configure(server = {"driver": "werkzeug", "host": "0.0.0.0", "port": 9090})
print("Running server, listening on 0.0.0.0:9090. Hit Ctrl+C to exit.")
server.serve()
```

The base server defines methods for registration and dispatching of requests. The two implementations (XML and JSON) are responsible for parsing and formatting of requests and responses.

### Client

The simplest client possible is one that simply communicates with a webserver, and doesn't need to parse the response in any meaningful way. Unlike with servers, the base webservice API client is instantiable.

```python
from pibble.api.client.webservice.base import WebServiceAPIClientBase

base = WebServiceAPIClientBase("google.com")
print(base.get().text)
```
When executing any methods via .get(), .post(), etc., you will receive a `requests.models.Response` object. See the the requests documentation for assistance with these objects. Clients use a session (r`equests.models.Session`) object to maintain some state (cookies, etc.), but should generally assume themselves to be stateless.

#### RPC

Using an XML RPC Client is very simple. Once a client is instantiated, it will queue up a call to system.listMethods, a built-in RPC function that will list the methods of a client. After that, calling them is as simple as calling the method with the appropriate variables

```python
from pibble.api.client.webservice.rpc.xml.client import XMLRPCClient
from pibble.api.exceptions import (
    BadRequestError,
    UnsupportedMethodError
)

client = XMLRPCClient("127.0.0.1")

# Use a method with reserved characters
methods = client["system.listMethods"]()

for method in methods:
    # Get method signature - note this is automatically retrieved and checked when calling any function, but you can retrieve it for yourself if you need to.
    signature = client["system.methodSignature"](method)
    return_type, parameter_types = signature[0], signature[1:] # RPC specification
    print("Method {0} takes ({1}) and returns ({2})".format(method, ", ".join(parameter_types), return_type))

try:
    method.pow(1, 2, 3)
except BadRequestError:
    # Wrong parameters
except BadResponseError:
    # Wrong response time
except UnsupportedMethodError:
    # Method does not exist
```

The base client has handlers for introspection and dispatching requests. Implementations are responsible for formatting requests and parsing responses.

RPC (Remote Procedure Call)
===========================

Example Usage
-------------

Using an XML RPC Client is very simple. Once a client is instantiated, it will queue up a call to ``system.listMethods``, a built-in RPC function that will list the methods of a client. After that, calling them is as simple as calling the method with the appropriate variables ::

  from goodylib.api.client.webservice.rpc.xml.client import XMLRPCClient
  from goodylib.api.exceptions import BadRequestError
  from goodylib.api.exceptions import UnsupportedMethodError

  client = XMLRPCClient("127.0.0.1")

  # Use a method with reserved characters
  methods = client["system.listMethods"]()

  for method in methods:
    # Get method signature - note this is automatically retrieved and checked when calling any function,
    # but you can retrieve it for yourself if you need to.
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


Base
----

The base client has handlers for introspection and dispatching requests. Implementations are responsible for formatting requests and parsing responses.

.. autoclass:: goodylib.api.client.webservice.rpc.base.RPCClientBase
   :members:

XML
---

.. autoclass:: goodylib.api.client.webservice.rpc.xml.client.XMLRPCClient
   :members:

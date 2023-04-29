RPC (Remote Procedure Call)
===========================

Example Usage
-------------

Using one of the RPC servers is as simple as defining functions and registering them to the server::

  from goodylib.api.server.webservice.rpc.xml.server import XMLRPCServer

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

Base
----

The base server defines methods for registration and dispatching of requests. The two implementations (XML and JSON) are responsible for parsing and formatting of requests and responses.

.. autoclass:: goodylib.api.server.webservice.rpc.base.RPCServerBase
   :members:

XML
---

.. autoclass:: goodylib.api.server.webservice.rpc.xml.server.XMLRPCServer
   :members:

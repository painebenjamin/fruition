Web Service API Client
======================

.. autoclass:: goodylib.api.client.webservice.base.WebServiceAPIClientBase
  :members:

Once again, we define a **webservice** as any client that communicates over TCP/IP.

The simplest client possible is one that simply communicates with a webserver, and doesn't need to parse the response in any meaningful way. Unlike with servers, the base webservice API client is instantiable. ::

  from goodylib.api.client.webservice.base import WebServiceAPIClientBase
  
  base = WebServiceAPIClientBase("google.com")
  print(base.get().text)

When executing any methods via ``.get()``, ``.post()``, etc., you will receive a ``requests.models.Response`` object. See the `the requests documentation <http://docs.python-requests.org/en/master/>`_ for assistance with these objects. Clients use a session (``requests.models.Session``) object to maintain some state (cookies, etc.), but should generally assume themselves to be stateless.

See below for specific implementations of various webservice APIs.

.. toctree::
   :maxdepth: 2

   rpc

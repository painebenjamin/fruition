Web Service API Server
======================

.. autoclass:: goodylib.api.server.webservice.base.WebServiceAPIServerBase
   :members:

We defined a **Web Service** as one that communicates over TCP/IP.

All web server APIs should be extended from :class:`goodylib.api.server.webservice.base.WebServiceAPIServerBase`. For the most part, each implementation must only register some ``handlers`` using the :class:`goodylib.api.server.webservice.base.WebServiceAPIHandlerRegistry`, which will handle all requests using a method and path. A class is **not** recommended to use the parent ``handler`` function, as this will provider handlers for **all** classes in this module that extend from :class:`goodylib.api.webservice.base.WebServiceAPIServerBase`, instead defining their own. For example, if we simply wanted to serve files from a directory over HTTP, we could use something like this::

  import os
  from goodylib.api.exceptions import NotFoundError
  from goodylib.api.server.webservice.base import WebServiceAPIServerBase
  from goodylib.api.server.webservice.base import WebServiceAPIHandlerRegistry

  class SimpleFileServer(WebServiceAPIServerBase):
    base_directory = "/var/www/html"
    handlers = WebServiceAPIHandlerRegistry()

    @handlers.path("(?P<file_path>.*)")
    @handlers.methods("GET")
    def retrieve_file(self, request, response, file_path = None):
      """
      Handles the request by looking for the path in ``self.base_directory``.

      :param request webob.Request: The request object.
      :param response webob.Response: The response object.
      :param file_path str: The file path, captured from the URI.
      :throws: :class:`goodylib.api.exceptions.NotFoundError`
      """

      file_path = os.path.join(self.base_directory, file_path)
      if not os.path.isfile(file_path):
        raise NotFoundError("Could not find file at {0}".format(file_path))

      response.body = open(file_path, "r").read()

The ``request`` and ``response`` parameters are ``webob.Request`` and ``webob.Response`` objects, respectively. See `The WebOb Documentation <https://docs.pylonsproject.org/projects/webob/en/stable/reference.html>`_ for help with their usage. Note the method name does not matter, so use a naming schema relevant to your project.

Deploying the API can be done using anything that conforms to ``wsgi`` standards. For development, we can deploy a server using ``werkzeug`` or ``gunicorn``, binding to a local port with a configured listening host. Using the above server definition, we can do this with:::

  server = SimpleFileServer()
  server.configure(server = {"driver": "werkzeug", "host": "0.0.0.0", "port": 9090})

  # Serve synchronously
  server.serve()

  # Serve asynchronously
  server.start()
  # Use the server
  server.stop()

See below for all presently included implementations.

.. toctree::
   :maxdepth: 2

   rpc

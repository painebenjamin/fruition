from pibble.api.server.webservice.handler import WebServiceAPIHandler


class WebServiceAPIServerMixinBase:
    """
    A class to hold mixins.

    Mixins are made to register handlers after the initial objects has been instantiated.
    These can be methods that provide meta-information (such as a .wsdl document), authentication information
    or handlers (callbacks for oauth), etc.

    They're expected to use the ``register`` function to register handlers.
    """

    def register(self, handler: WebServiceAPIHandler):
        """
        Registers an individual handler.

        :param handler pibble.api.server.webservice.base.WebServiceAPIHandlerRegistry: The handler registry.
        """
        pass

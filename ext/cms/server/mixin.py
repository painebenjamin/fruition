from pibble.api.server.webservice.mixin.base import WebServiceAPIServerMixinBase


class CMSExtensionContextMixin(WebServiceAPIServerMixinBase):
    """
    This mixin passes through any base context configured
    on the server.
    """

    def prepare_context(self, request, response):
        return self.configuration["server.cms.context.base"]

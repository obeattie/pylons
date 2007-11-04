from pylons.controllers import WSGIController
from formencode.variabledecode import variable_decode
from formencode import htmlfill, Schema
from paste.util.multidict import UnicodeMultiDict

import sys
import logging
import pylons
import urlparse
import formencode

log = logging.getLogger(__name__)


def _configured_engines():
    """Returns set with the currently configured template engine's names from
    the active application's globals"""
    g = pylons.g._current_obj()
    if not hasattr(g, 'tg_configured_engines'):
        g.tg_configured_engines = set()
    return g.tg_configured_engines


class DecoratedController(WSGIController):
    
    def _perform_validate(self, controller, params):
        params.update(dict(pylons.request.params))
        
        validation = getattr(controller.decoration, 'validation', None)
        if validation is None:
            return params
        
        if isinstance(validation.validators, dict):
            errors = {}
            for field, validator in validation.validators.iteritems():
                try:
                    params[field] = \
                        validator.to_python(params.get(field))
                except formencode.api.Invalid, inv:
                    errors[field] = inv
            
            if errors:
                raise formencode.api.Invalid(
                    formencode.schema.format_compound_error(errors),
                    params, None, error_dict=errors
                )
        elif isinstance(validation.validators, Schema):
            params = validation.validators.to_python(params)
            
        return params        
    
    def _render_response(self, controller, response):
        '''Render response takes the dictionary returned by the controller calls
        the apropriate template engine. It uses information off of the decoration 
        object to decide which engine and template to use, and removes anything 
        in the exclude_names list from the returned dictionary. 

        The exclude_names funtionality  allows you to pass variables to some 
        template rendering engines, but not others. This behavior is particularly 
        usefull for rendering engines like JSON or other "web service" style 
        engines which don't use and explicit template.

        All of these values are populated into the context object by the 
        expose decorator. 
        '''
        content_type, engine_name, template_name, exclude_names = \
                      controller.decoration.lookup_template_engine(pylons.request)
        if template_name is None: return response
        if engine_name not in _configured_engines():
            pylons.buffet.prepare(engine_name)
            _configured_engines().add(engine_name)
        namespace = dict(context=pylons.c)
        namespace.update(response)
        for name in exclude_names:
            namespace.pop(name)
        result = pylons.buffet.render(engine_name=engine_name,
                                      template_name=template_name,
                                      include_pylons_variables=False,
                                      namespace=namespace)                          
        pylons.response.headers['Content-Type'] = content_type
        return result

    def _handle_validation_errors(self, controller, exception):
        pylons.c.form_errors = exception.error_dict
        pylons.c.form_values = exception.value
        
        error_handler = controller.decoration.validation.error_handler
        if error_handler is None:
            error_handler = controller
        
        output = error_handler(controller.im_self)
        
        return error_handler, output
        
        # TG2 OLD VALIDATION CODE 
        # pylons.c.form_errors = exception.error_dict
        # pylons.c.form_values = exception.value
        # error_handler = controller.decoration.error_handler
        # if not error_handler: raise
        # if isinstance(error_handler, basestring):
        #     controller_url = pylons.c.controller_url
        #     error_handler_absolute_url = urlparse.urljoin(controller_url, error_handler)
        #     # TODO: fix this commented out code
        #     # error_handler, remainder = object_dispatch(self, error_handler_absolute_url.split('/'))
        #     # if remainder and remainder[-1] == '': remainder.pop()
        #     # output = error_handler(*remainder)
        # else:
        #     output = error_handler(controller.im_self)
        # return error_handler, output
    
    def _perform_call(self, func, args, remainder=[]):
        try:
            controller, params = func, args
            pylons.request.headers['tg_format'] = params.pop('tg_format', None)

            # Validate user input
            controller.decoration.run_hooks('before_validate', remainder, params)
            params = self._perform_validate(controller, params)
            pylons.c.form_values = params
            
            # call controller method
            controller.decoration.run_hooks('before_call', remainder, params)
            output = controller(*remainder, **dict(params))

        except formencode.api.Invalid, inv:
            controller, output = self._handle_validation_errors(controller, inv)

        # Render template
        controller.decoration.run_hooks('before_render', remainder, params, output)
        response = self._render_response(controller, output)
        controller.decoration.run_hooks('after_render', response)
        return response
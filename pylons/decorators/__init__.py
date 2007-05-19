"""Pylons Decorators: ``jsonify``, ``validate``, REST, and Cache decorators"""
import sys
import warnings
import logging
log = logging.getLogger('pylons.decorators')

import simplejson as json
from decorator import decorator

from paste.util.multidict import UnicodeMultiDict
import formencode.api as api
import formencode.variabledecode as variabledecode
from formencode import htmlfill

import pylons

def jsonify(func, *args, **kwargs):
    """Action decorator that formats output for JSON
    
    Given a function that will return content, this decorator will
    turn the result into JSON, with a content-type of 'text/javascript'
    and output it.
    """
    response = pylons.Response()
    response.headers['Content-Type'] = 'text/javascript'
    data = func(*args, **kwargs)
    if isinstance(data, list):
        msg = "JSON responses with Array envelopes are susceptible to " \
              "cross-site data leak attacks, see " \
              "http://pylonshq.com/warnings/JSONArray"
        warnings.warn(msg, Warning, 2)
        log.warning(msg)
    response.content.append(json.dumps(data))
    log.debug("Returning JSON wrapped action output")
    return response
jsonify = decorator(jsonify)

def validate(schema=None, validators=None, form=None, variable_decode=False,
             dict_char='.', list_char='-', post_only=True):
    """Validate input either for a FormEncode schema, or individual validators
    
    Given a form schema or dict of validators, validate will attempt to
    validate the schema or validator list as long as a POST request is made. No
    validation is performed on GET requests.
    
    If validation was succesfull, the valid result dict will be saved
    as ``self.form_result``. Otherwise, the action will be re-run as if it was
    a GET, and the output will be filled by FormEncode's htmlfill to fill in
    the form field errors.
    
    If you'd like validate to also check GET (query) variables (**not** GET
    requests!) during its validation, set the ``post_only`` keyword argument 
    to False.
    
    .. warning::
        ``post_only`` applies to *where* the arguments to be validated come 
        from. The validate decorator *only* validates during a POST, it does
        *not* validate during a GET request. 
    
    Example:
    
    .. code-block:: Python
        
        class SomeController(BaseController):
            
            def create(self, id):
                return render_response('/myform.myt')
            
            @validate(schema=model.forms.myshema(), form='create')
            def update(self, id):
                # Do something with self.form_result
                pass
    """
    def wrapper(func, self, *args, **kwargs):
        """Decorator Wrapper function"""
        errors = {}
        if not pylons.request.method == 'POST':
            log.debug("Method was not a form post, validate skipped")
            return func(self, *args, **kwargs)
        if post_only:
            params = pylons.request.POST
        else:
            params = pylons.request.params
        is_unicode_params = isinstance(params, UnicodeMultiDict)
        params = params.mixed()
        if variable_decode:
            log.debug("Running variable_decode on params")
            decoded = variabledecode.variable_decode(params, dict_char,
                                                     list_char)
        else:
            decoded = params

        if schema:
            log.debug("Validating against a schema")
            try:
                self.form_result = schema.to_python(decoded)
            except api.Invalid, e:
                errors = e.unpack_errors(variable_decode, dict_char, list_char)
        if validators:
            log.debug("Validating against provided validators")
            if isinstance(validators, dict):
                if not hasattr(self, 'form_result'):
                    self.form_result = {}
                for field, validator in validators.iteritems():
                    try:
                        self.form_result[field] = \
                            validator.to_python(decoded.get(field))
                    except api.Invalid, error:
                        errors[field] = error
        if errors:
            log.debug("Errors found in validation, parsing form with htmlfill for errors")
            pylons.request.environ['REQUEST_METHOD'] = 'GET'
            pylons.request.environ['pylons.routes_dict']['action'] = form
            response = self._dispatch_call()
            form_content = ''.join(response.content)
            # Ensure htmlfill can safely combine the form_content, params and
            # errors variables (that they're all of the same string type)
            if not is_unicode_params:
                log.debug("Raw string form params: ensuring the '%s' form and "
                          "FormEncode errors are converted to raw strings for "
                          "htmlfill", form)
                encoding = determine_response_charset(response)

                # WSGIResponse's content may (unlikely) be unicode
                if isinstance(form_content, unicode):
                    form_content = form_content.encode(encoding,
                                                       response.errors)

                # FormEncode>=0.7 errors are unicode (due to being localized
                # via ugettext). Convert any of the possible formencode
                # unpack_errors formats to contain raw strings
                errors = encode_formencode_errors(errors, encoding,
                                                  response.errors)
            elif not isinstance(form_content, unicode):
                log.debug("Unicode form params: ensuring the '%s' form is "
                          "converted to unicode for htmlfill", form)
                encoding = determine_response_charset(response)
                form_content = form_content.decode(encoding)
            response.content = [htmlfill.render(form_content, params, errors)]
            return response
        return func(self, *args, **kwargs)
    return decorator(wrapper)

def determine_response_charset(response):
    """Determine the charset of the specified Response object, returning the
    default system encoding when none is set"""
    charset = response.determine_charset()
    if charset is None:
        charset = sys.getdefaultencoding()
    log.debug("Determined result charset to be: %s", charset)
    return charset

def encode_formencode_errors(errors, encoding, encoding_errors='strict'):
    """Encode any unicode values contained in a FormEncode errors dict to raw
    strings of the specified encoding"""
    if errors is None or isinstance(errors, str):
        # None or Just incase this is FormEncode<=0.7
        pass
    elif isinstance(errors, unicode):
        errors = errors.encode(encoding, encoding_errors)
    elif isinstance(errors, dict):
        for key, value in errors.iteritems():
            errors[key] = encode_formencode_errors(value, encoding,
                                                   encoding_errors)
    else:
        # Fallback to an iterable (a list)
        errors = [encode_formencode_errors(error, encoding, encoding_errors) \
                      for error in errors]
    return errors

__all__ = ['jsonify', 'validate']

import os

def app(environ, start_response):
    status = '200 OK'
    response_headers = [('Content-type','text/plain')]
    start_response(status, response_headers)
    return [b'One of the nice things about the new operator framework is how easy it is to get started.\n']

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import os


def app(environ, start_response):
    status = "200 OK"
    response_headers = [("Content-type", "text/plain")]
    start_response(status, response_headers)
    ret = [
        b"One of the nice things about the new operator framework is how easy it is to get started.\n"
    ]
    for i, x in sorted(os.environ.items()):
        ret.append("{}: {}\n".format(i, x).encode("utf-8"))

    return ret

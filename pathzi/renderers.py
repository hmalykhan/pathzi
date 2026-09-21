"""
JSON renderer that states its charset.

DRF's JSONRenderer sends `Content-Type: application/json` with no charset,
on the grounds that RFC 8259 already requires JSON to be UTF-8. That is
correct, but clients that trust the header rather than the specification
have to guess, and some guess latin-1 - which turns £ into Â£.

Saying so explicitly costs nothing.
"""
from rest_framework.renderers import JSONRenderer


class Utf8JSONRenderer(JSONRenderer):
    charset = "utf-8"

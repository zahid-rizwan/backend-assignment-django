# core/exception_handler.py
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "success": False,
            "data": None,
            "error": {
                "code": exc.__class__.__name__.upper(),
                "message": str(response.data),
            },
            "meta": {},
        }
    return response
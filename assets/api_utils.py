from rest_framework.response import Response


def success_response(data=None, status=200, meta=None):
    return Response({
        "success": True,
        "data": data,
        "error": None,
        "meta": meta or {},
    }, status=status)


def error_response(message, code="ERROR", status=400, meta=None):
    return Response({
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
        "meta": meta or {},
    }, status=status)
from .request_id import accept_or_new, reset_request_id, set_request_id

HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """Reads or creates X-Request-ID and returns it on every response, errors included."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = accept_or_new(request.headers.get(HEADER))
        request.request_id = request_id
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response[HEADER] = request_id
        return response

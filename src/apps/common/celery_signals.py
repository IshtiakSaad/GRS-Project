"""Propagate the request id from the enqueuing request into the task that runs later."""

from celery.signals import before_task_publish, task_postrun, task_prerun

from .request_id import accept_or_new, get_request_id, reset_request_id, set_request_id

HEADER = "request_id"
_tokens: dict[str, object] = {}


@before_task_publish.connect
def _attach(headers=None, **_):
    if headers is not None and HEADER not in headers:
        headers[HEADER] = get_request_id()


@task_prerun.connect
def _restore(task_id=None, task=None, **_):
    incoming = getattr(task.request, HEADER, None) if task else None
    _tokens[task_id] = set_request_id(accept_or_new(incoming))


@task_postrun.connect
def _clear(task_id=None, **_):
    token = _tokens.pop(task_id, None)
    if token is not None:
        reset_request_id(token)

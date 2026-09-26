"""gunicorn worker for App Service: uvicorn without its `Server: uvicorn` banner."""
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)  # uvicorn.workers still works; see uvicorn-worker
    from uvicorn.workers import UvicornWorker


class Worker(UvicornWorker):
    CONFIG_KWARGS = {**UvicornWorker.CONFIG_KWARGS, "server_header": False}

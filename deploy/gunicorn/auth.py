"""Gunicorn for api-auth, the password-hashing bulkhead.

Password hashing is deliberately slow and CPU-bound. A login storm at 9am could otherwise
occupy every API worker and stall submissions. These routes run in their own container with
a fixed number of workers, so the storm queues here and the rest of the API keeps serving.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from api import *  # noqa: E402, F403

workers = int(os.environ.get("GUNICORN_WORKERS", "2"))

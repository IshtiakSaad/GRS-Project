from rest_framework.pagination import CursorPagination


class KeysetPagination(CursorPagination):
    """Keyset pagination: page 500 costs the same as page 1, and inserts never shift pages."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


class OldestFirstPagination(KeysetPagination):
    """For conversations, which read top to bottom."""

    ordering = ("created_at", "id")

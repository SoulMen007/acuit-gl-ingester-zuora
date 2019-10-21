"""
Datastore utilities
"""

DATASTORE_FETCH_PAGE_SIZE = 100

def emit_items(query, keys_only=False):
    """
    Generator that emits items while fetching them efficiently for the provided query.

    Args:
        query(Query): ndb query to produce items for
        keys_only(bool): whether to produce ndb.Key or ndb.Model items
    Yields:
        ndb.Item or ndb.Key: the retrieved items
    """
    more = True
    cursor = None

    while more:
        items, cursor, more = query.fetch_page(
            DATASTORE_FETCH_PAGE_SIZE,
            keys_only=keys_only,
            start_cursor=cursor
        )

        for item in items:
            yield item

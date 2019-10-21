"""
Utilities for generating and managing tasks.
"""
from itertools import izip_longest

from google.appengine.api import taskqueue


def query_to_tasks(query, queue, task_generator):
    """
    Runs the specified query (paginated) and adds tasks asynchronously to a queue.

    Args:
        query(Query): ndb query to produce keys
        queue(Queue): queue to add tasks to
        task_generator(function): a function that is called for each fetched key to generate tasks with
    Returns:
        int: count of the number of tasks added to the queue
    """
    more = True
    cursor = None
    task_rpcs = []
    count = 0

    # Only fetch keys and batch the fetch by the maximum we can add to the taskqueue in one call.
    while more:
        keys, cursor, more = query.fetch_page(
            taskqueue.MAX_TASKS_PER_ADD,
            keys_only=True,
            start_cursor=cursor
        )

        if len(keys) > 0:
            tasks = [task_generator(key) for key in keys]
            task_rpcs.append(queue.add_async(tasks))
            count += len(keys)

    # Wait for all async taskqueue adds to finish
    for task_rpc in task_rpcs:
        task_rpc.get_result()

    return count


def items_to_tasks(items, queue, task_generator):
    """
    Add tasks asynchronously to a queue for the provided items.

    Args:
        items(list): items to produce tasks for
        queue(Queue): queue to add tasks to
        task_generator(function): a function that is called for each item to generate tasks for
    Returns:
        int: count of the number of tasks added to the queue
    """
    task_rpcs = []
    # Group items by an optimal number for task enqueueing
    # https://docs.python.org/2/library/itertools.html#recipes
    for group in izip_longest(*([iter(items)] * taskqueue.MAX_TASKS_PER_ADD)):
        tasks = [task_generator(item) for item in group if item is not None]
        task_rpcs.append(queue.add_async(tasks))

    # Wait for all async taskqueue adds to finish
    for task_rpc in task_rpcs:
        task_rpc.get_result()

    return len(items)

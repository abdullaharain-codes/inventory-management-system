"""
Thread-safe in-process pub-sub for real-time notification delivery via SSE.

Each connected SSE client registers a Queue. When create_notification()
publishes, only matching subscribers (based on the same visibility rules as
get_notifications()) receive the event on their queue.
"""

import threading
import queue


_lock = threading.Lock()
_subscribers = {}


def subscribe(subscriber_id, user_id, role):
    q = queue.Queue(maxsize=100)
    with _lock:
        _subscribers[subscriber_id] = {
            'queue': q,
            'user_id': user_id,
            'role': role,
        }
    return q


def unsubscribe(subscriber_id):
    with _lock:
        _subscribers.pop(subscriber_id, None)


def publish(notification_dict):
    """Put notification onto every matching subscriber's queue.
    Non-blocking — silently drops if a queue is full."""
    with _lock:
        snapshot = list(_subscribers.values())

    for sub in snapshot:
        if _is_visible(notification_dict, sub['user_id'], sub['role']):
            try:
                sub['queue'].put_nowait(notification_dict)
            except queue.Full:
                pass


def _is_visible(notification, viewer_user_id, viewer_role):
    """Same visibility rule as get_notifications() WHERE clause."""
    n_uid = notification.get('user_id')
    n_role = notification.get('target_role', 'all')
    if n_uid is not None and n_uid == viewer_user_id:
        return True
    if n_role == 'all':
        return True
    if n_role == viewer_role:
        return True
    return False

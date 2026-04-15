from flask_socketio import emit

# Global socketio instance to be set by app.py
socketio = None

def emit_notification(user_id, notif_data):
    """
    Helper function to emit a notification to a specific user via WebSocket.
    """
    if socketio:
        socketio.emit('new_notification', notif_data, room=f"user_{user_id}")
    else:
        print(f"[Warning] socketio not initialized. Cannot emit notification to user_{user_id}")

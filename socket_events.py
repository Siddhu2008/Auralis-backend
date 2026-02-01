from flask_socketio import emit, join_room, leave_room
from flask import request
import os
import wave
import uuid
from utils.transcriber import transcribe_audio
from utils.summarizer import summarize_text
from models.meeting import create_meeting
from utils.ai_response import generate_avatar_chat

# In-memory room tracking
# rooms[room_id] = [user_sid, ...]
rooms = {}
# room_hosts[room_id] = host_sid
room_hosts = {}

# Audio buffers: room_audio_buffers[room_id] = [byte_chunk, ...]
room_audio_buffers = {}

def register_socket_events(socketio):
    @socketio.on('connect')
    def handle_connect():
        print(f"Client connected: {request.sid}")

    @socketio.on('disconnect')
    def handle_disconnect():
        print(f"Client disconnected: {request.sid}")
        # Clean up User from Rooms
        for room in list(rooms.keys()): # Copy keys to avoid size change iteration error
            users = rooms[room]
            if request.sid in users:
                users.remove(request.sid)
                emit('user_left', {'sid': request.sid}, to=room)
                
                # Logic to reassign host or cleanup
                if room in room_hosts and room_hosts[room] == request.sid:
                    if users:
                        # Assign next user as host
                        new_host = users[0]
                        room_hosts[room] = new_host
                        emit('role_assigned', {'role': 'host'}, to=new_host) # Notify new host
                        print(f"Host left. New host for {room} is {new_host}")
                    else:
                        # Room empty
                        del room_hosts[room]
                        del rooms[room] # Clean up empty room
                        if room in room_audio_buffers:
                            del room_audio_buffers[room]
                        print(f"Room {room} is now empty and deleted.")

    @socketio.on('join_room')
    def handle_join_room(data):
        room = data['room']
        
        # Check if room exists and has users
        if room not in rooms or not rooms[room]:
            # Create/Initialize Room
            rooms[room] = []
            room_hosts[room] = request.sid # First joiner is host
            room_audio_buffers[room] = [] # Initialize buffer
            
            join_room(room)
            rooms[room].append(request.sid)
            
            emit('user_joined', {'sid': request.sid}, to=room, include_self=False)
            emit('role_assigned', {'role': 'host'}) # Explicitly tell client they are host
            print(f"Room {room} created/initialized by Host {request.sid}")
            return

        # If room exists and has a host
        host_sid = room_hosts.get(room)
        
        if host_sid:
            # Check if this user is re-joining (e.g. refresh) - naive check
            # For now, treat all new socket connections as new users requiring approval
            
            # Notify Host
            emit('entry_requested', {'sid': request.sid}, to=host_sid)
            print(f"User {request.sid} asking to join Room {room}. Notification sent to Host {host_sid}")
        else:
            # Fallback: Room exists but no host?? (Should be covered by disconnect logic, but just in case)
            # Make this user the host
            room_hosts[room] = request.sid
            join_room(room)
            rooms[room].append(request.sid)
            emit('role_assigned', {'role': 'host'})
            emit('user_joined', {'sid': request.sid}, to=room, include_self=False)
            print(f"Room {room} recovered. Host assigned to {request.sid}")

    @socketio.on('approve_entry')
    def handle_approve_entry(data):
        target_sid = data.get('target_sid')
        room = data.get('room')
        
        if not target_sid or not room: return

        current_host = room_hosts.get(room)
        
        # Verify request is from host
        if current_host == request.sid:
            # Force join target
            join_room(room, sid=target_sid) 
            
            # Ensure lists are updated
            if room not in rooms: rooms[room] = []
            if request.sid not in rooms[room]: rooms[room].append(request.sid)
            if target_sid not in rooms[room]: rooms[room].append(target_sid)
            
            # Notify everyone
            emit('user_joined', {'sid': target_sid}, to=room)
            
            # Send list of users to the new person
            existing_users = [u for u in rooms[room] if u != target_sid]
            emit('all_users', {'users': existing_users}, to=target_sid)
            emit('room_joined_success', {'role': 'participant'}, to=target_sid)
            
            print(f"Host {request.sid} approved {target_sid} for Room {room}")
        else:
            print(f"Unauthorized approve attempt by {request.sid} for room {room}")

    @socketio.on('deny_entry')
    def handle_deny_entry(data):
        target_sid = data.get('target_sid')
        emit('entry_denied', {}, to=target_sid)

    @socketio.on('leave_room')
    def handle_leave_room(data):
        room = data['room']
        leave_room(room)
        if room in rooms and request.sid in rooms[room]:
            rooms[room].remove(request.sid)
        emit('user_left', {'sid': request.sid}, to=room)

    # Audio Handling
    @socketio.on('audio_chunk')
    def handle_audio_chunk(data):
        room = data.get('room')
        chunk = data.get('chunk') # Expecting bytes or specific format
        
        if room and chunk and room in room_audio_buffers:
            # Assuming chunk is raw bytes or can be appended. 
            # In a real app, you'd want to be careful about mixing streams.
            # For this MVP, we just append to the room's single buffer.
            room_audio_buffers[room].append(chunk)

    @socketio.on('end_meeting')
    def handle_end_meeting(data):
        room = data.get('room')
        user_id = data.get('user_id') # Identify who is saving it
        title = data.get('title', 'Untitled Meeting')
        
        if not room or room not in room_audio_buffers:
            print(f"No audio buffer for room {room}")
            return

        print(f"Processing meeting {room}...")
        emit('processing_status', {'status': 'processing'}, to=room)
        
        # Save Audio to Temp WAV
        chunks = room_audio_buffers[room]
        if not chunks:
            print("Audio buffer empty.")
            return

        temp_filename = f"temp_{uuid.uuid4()}.wav"
        try:
            # Assuming incoming data is suitable for wave write (e.g. PCM blob)
            # If the frontend sends a Blob/File, we might need to write binary.
            with open(temp_filename, 'wb') as f:
                for chunk in chunks:
                    f.write(chunk)
            
            # Verify/Fix WAV header if needed. 
            # If frontend sends raw PCM, we need `wave` module to write header.
            # If frontend sends WebM/WAV file chunks, we just concatenated them.
            # Start with Assuming Frontend sends a valid WAV or we use ffmpeg later.
            # For this step, let's assume we pass the file to transcriber.

            # Transcribe
            transcript_result = transcribe_audio(temp_filename)
            transcript_text = transcript_result.get('text', '')
            
            # Summarize
            summary_text = summarize_text(transcript_text)
            
            # Save to DB
            if user_id:
               create_meeting(user_id, room, title, transcript_text, summary_text)

            # Add to Digital Twin Memory (Vector Store)
            try:
                from utils.vector_store import vector_store
                print(f"Indexing meeting {room} into Vector Store...")
                vector_store.add_meeting(room, transcript_text, metadata={'title': title, 'date': str(uuid.uuid4())}) # simplified date
            except Exception as vs_e:
                print(f"Vector Store Indexing Error: {vs_e}")
            
            emit('processing_status', {'status': 'completed', 'summary': summary_text}, to=room)
            
            # Clear buffer
            room_audio_buffers[room] = []
            
        except Exception as e:
            print(f"Error processing meeting: {e}")
            emit('processing_status', {'status': 'error', 'error': str(e)}, to=room)
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

    # Signaling
    @socketio.on('offer')
    def handle_offer(data):
        emit('offer', {'sdp': data['sdp'], 'caller': request.sid}, to=data['target'])

    @socketio.on('answer')
    def handle_answer(data):
        emit('answer', {'sdp': data['sdp'], 'responder': request.sid}, to=data['target'])

    @socketio.on('ice_candidate')
    def handle_ice_candidate(data):
        emit('ice_candidate', {'candidate': data['candidate'], 'sender': request.sid}, to=data['target'])

    # Features

    @socketio.on('raise_hand')
    def handle_raise_hand(data):
        emit('hand_raised', {'sid': request.sid, 'isRaised': data['isRaised']}, to=data['room'])

    @socketio.on('reaction')
    def handle_reaction(data):
        emit('reaction_received', {'sid': request.sid, 'emoji': data['emoji']}, to=data['room'])

    # AI Avatar Integration
    @socketio.on('spawn_ai_avatar')
    def handle_spawn_avatar(data):
        room = data.get('room')
        print(f"Spawning AI Avatar in room {room}")
        # Notify everyone that Auralis AI has joined
        emit('user_joined', {'sid': 'Auralis_AI', 'name': 'Auralis AI'}, to=room)
        emit('chat_message', {
            'sender': 'Auralis_AI',
            'message': "Hello everyone! I'm Auralis AI, your meeting assistant. I'll be taking notes and I'm ready for your questions.",
            'timestamp': datetime.utcnow().isoformat()
        }, to=room)

    @socketio.on('avatar_chat')
    def handle_avatar_chat(data):
        room = data.get('room')
        message = data.get('message')
        
        # Generate Response
        response = generate_avatar_chat(message)
        
        emit('chat_message', {
            'sender': 'Auralis_AI',
            'message': response,
            'timestamp': datetime.utcnow().isoformat()
        }, to=room)

    # Automatically trigger avatar if mentioned in regular chat
    @socketio.on('chat_message')
    def handle_chat_message_with_ai(data):
        room = data['room']
        message = data['message']
        
        # Original emit
        emit('chat_message', {
            'sender': request.sid,
            'message': message,
            'timestamp': data.get('timestamp')
        }, to=room)
        
        # Check for trigger
        if "@ai" in message.lower() or "auralis" in message.lower():
            response = generate_avatar_chat(message)
            emit('chat_message', {
                'sender': 'Auralis_AI',
                'message': response,
                'timestamp': datetime.utcnow().isoformat()
            }, to=room)


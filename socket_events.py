from flask_socketio import emit, join_room, leave_room
from flask import request
import os
import wave
import uuid
from utils.transcriber import transcribe_audio
from utils.summarizer import summarize_text
from models.meeting import create_meeting
from utils.ai_response import generate_avatar_chat
from datetime import datetime

# In-memory room tracking
# rooms[room_id] = [user_sid, ...]
rooms = {}
# room_hosts[room_id] = host_sid
room_hosts = {}

# Audio buffers: room_audio_buffers[room_id] = [byte_chunk, ...]
room_audio_buffers = {}

# Live Transcripts: live_transcripts[room_id] = [text_chunk, ...]
live_transcripts = {}

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
        room = data.get('room')
        if not room: return
        
        # Check if room exists and has users
        if room not in rooms or not rooms[room]:
            # Initializing Room as Host
            rooms[room] = []
            room_hosts[room] = request.sid
            room_audio_buffers[room] = []
            live_transcripts[room] = [] # Initialize transcript buffer
            
            join_room(room)
            rooms[room].append(request.sid)
            
            emit('role_assigned', {'role': 'host'})
            print(f"Room {room} initialized by Host {request.sid}")
            return

        # If room exists, check if user is already in it (e.g. refresh)
        if request.sid in rooms[room]:
            emit('room_joined_success', {'role': 'host' if room_hosts.get(room) == request.sid else 'participant'})
            return

        # If joining as guest, notify host
        host_sid = room_hosts.get(room)
        if host_sid:
            emit('entry_requested', {'sid': request.sid}, to=host_sid)
            print(f"User {request.sid} requesting entry to Room {room}. Notifying Host {host_sid}")
        else:
            # Host missing but users exist? Make this user host.
            room_hosts[room] = request.sid
            join_room(room)
            rooms[room].append(request.sid)
            emit('role_assigned', {'role': 'host'})
            print(f"Host recovered for Room {room}: {request.sid}")

    @socketio.on('approve_entry')
    def handle_approve_entry(data):
        target_sid = data.get('target_sid')
        room = data.get('room')
        
        if not target_sid or not room: return

        # Verify requester is the host
        if room_hosts.get(room) == request.sid:
            join_room(room, sid=target_sid) 
            
            if room not in rooms: rooms[room] = []
            if target_sid not in rooms[room]: rooms[room].append(target_sid)
            
            # 1. Notify the new joiner they are in
            emit('room_joined_success', {'role': 'participant'}, to=target_sid)
            
            # 2. Tell the new joiner about everyone else
            existing_users = [u for u in rooms[room] if u != target_sid]
            emit('all_users', {'users': existing_users}, to=target_sid)
            
            # 3. Tell everyone else about the new joiner
            emit('user_joined', {'sid': target_sid}, to=room, include_self=False)
            
            print(f"Host {request.sid} admitted {target_sid} to Room {room}")

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

    @socketio.on('transcript_update')
    def handle_transcript_update(data):
        room = data.get('room')
        text = data.get('text')
        if room and text:
            if room not in live_transcripts:
                live_transcripts[room] = []
            live_transcripts[room].append(text)
            # print(f"Transcript update for {room}: {text}")

    @socketio.on('end_meeting')
    def handle_end_meeting(data):
        room = data.get('room')
        user_id = data.get('user_id') 
        title = data.get('title', 'Untitled Meeting')
        
        print(f"Processing meeting {room}...")
        emit('processing_status', {'status': 'processing'}, to=room)
        
        transcript_text = ""
        
        # Prioritize Live Transcript
        if room in live_transcripts and live_transcripts[room]:
            print("Using Live Transcript for summary.")
            transcript_text = " ".join(live_transcripts[room])
        
        # Fallback to Audio Buffer if Live Transcript is empty
        if not transcript_text and room in room_audio_buffers and room_audio_buffers[room]:
            print("Live Transcript empty. Falling back to Audio Buffer...")
            chunks = room_audio_buffers[room]
            temp_filename = f"temp_{uuid.uuid4()}.wav"
            try:
                with open(temp_filename, 'wb') as f:
                    for chunk in chunks:
                        f.write(chunk)
                transcript_result = transcribe_audio(temp_filename)
                transcript_text = transcript_result.get('text', '')
            except Exception as e:
                print(f"Audio Buffer Transcription Error: {e}")
            finally:
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

        if not transcript_text:
            print("No content to summarize.")
            emit('processing_status', {'status': 'completed', 'summary': "No content recorded."}, to=room)
            return

        # Summarize
        try:
            summary_text = summarize_text(transcript_text)
            
            # Save to DB
            if user_id:
               create_meeting(user_id, room, title, transcript_text, summary_text)

            # Add to Vector Store
            try:
                from utils.vector_store import vector_store
                vector_store.add_meeting(room, transcript_text, metadata={'title': title, 'date': str(uuid.uuid4())})
            except Exception as vs_e:
                print(f"Vector Store Indexing Error: {vs_e}")
            
            emit('processing_status', {'status': 'completed', 'summary': summary_text}, to=room)
            
            # Clear buffers
            if room in room_audio_buffers: room_audio_buffers[room] = []
            if room in live_transcripts: live_transcripts[room] = []
            
        except Exception as e:
            print(f"Error processing meeting: {e}")
            emit('processing_status', {'status': 'error', 'error': str(e)}, to=room)

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
        transcript = " ".join(live_transcripts.get(room, []))
        response = generate_avatar_chat(message, transcript=transcript)
        
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
            transcript = " ".join(live_transcripts.get(room, []))
            response = generate_avatar_chat(message, transcript=transcript)
            emit('chat_message', {
                'sender': 'Auralis_AI',
                'message': response,
                'timestamp': datetime.utcnow().isoformat()
            }, to=room)


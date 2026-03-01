from flask_socketio import emit, join_room, leave_room
from flask import request
import os
import wave
import uuid
from utils.transcriber import transcribe_audio
import threading
from utils.summarizer import summarize_text
from models.meeting import create_meeting
from utils.ai_response import generate_avatar_chat
from utils.ai_service import ai_service
from models.schedule import Schedule
from datetime import datetime

# Room User Details: room_user_details[room_id][sid] = {'name': 'John Doe', ...}
room_user_details = {}
rooms = {}
room_hosts = {}
room_host_ids = {} # NEW: Track host user_id
room_audio_buffers = {}
live_transcripts = {}
proxy_states = {} # Track if user has proxy enabled: proxy_states[sid] = True/False
room_cleanup_tasks = {} # room_id -> greenlet
"NO_RESPONSE_NEEDED" # Sentinel for AI Proxy

def _schedule_room_cleanup(room):
    if room_cleanup_tasks.get(room):
        return

    def cleanup():
        try:
            users = rooms.get(room, [])
            if users:
                return

            # Trigger Auto-Summarization
            if room in live_transcripts and live_transcripts[room]:
                full_text = " ".join(live_transcripts[room])
                if len(full_text) > 50:
                    print(f"[AI] Room {room} empty after grace. Generating automatic summary...")

                    def auto_summarize():
                        try:
                            summary = summarize_text(full_text)
                            host_id = room_host_ids.get(room)
                            if host_id:
                                create_meeting(
                                    user_id=host_id,
                                    room_id=room,
                                    title=f"AI Summary: {room}",
                                    transcript=full_text,
                                    summary=summary,
                                    duration='Automated'
                                )
                                print(f"[AI] Summary saved for room {room}")
                        except Exception as ex:
                            print(f"[AI] Auto-summary failed: {ex}")

                    threading.Thread(target=auto_summarize).start()

            if room in rooms:
                del rooms[room]
            if room in room_hosts:
                del room_hosts[room]
            if room in room_user_details:
                del room_user_details[room]
            if room in room_host_ids:
                del room_host_ids[room]
            if room in room_audio_buffers:
                del room_audio_buffers[room]
            if room in live_transcripts:
                del live_transcripts[room]
            print(f"Room {room} cleaned up after grace period.")
        finally:
            room_cleanup_tasks.pop(room, None)

    task = threading.Timer(30, cleanup)
    task.start()
    room_cleanup_tasks[room] = task

def _cancel_room_cleanup(room):
    task = room_cleanup_tasks.pop(room, None)
    if task:
        try:
            task.cancel()
        except Exception:
            pass

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
                
                # Create user_left payload
                left_payload = {'sid': request.sid}
                if room in room_user_details and request.sid in room_user_details[room]:
                   left_payload['name'] = room_user_details[room][request.sid].get('name', 'Unknown')
                   del room_user_details[room][request.sid]

                emit('user_left', left_payload, to=room)
                
                # Logic to reassign host or cleanup
                if room in room_hosts and room_hosts[room] == request.sid:
                    if users:
                        # Assign next user as host
                        new_host = users[0]
                        room_hosts[room] = new_host
                        emit('role_assigned', {'role': 'host'}, to=new_host) # Notify new host
                        print(f"Host left. New host for {room} is {new_host}")
                    else:
                        _schedule_room_cleanup(room)
                        print(f"Room {room} empty; scheduled cleanup grace period.")

    @socketio.on('join_room')
    def handle_join_room(data):
        room = data.get('room', '').strip().lower() # Case-insensitive normalization
        user_name = data.get('user_name', 'Guest')
        user_id = data.get('user_id')

        if not room: return

        _cancel_room_cleanup(room)
        
        print(f"DEBUG: join_room. Room: '{room}', User: '{user_name}', ID: {user_id}")
        print(f"DEBUG: Global Status - sessions: {list(room_host_ids.keys())}, active_hosts: {list(room_hosts.keys())}")

        # 1. Prune stale sessions for this user_id in this room
        if user_id:
            stale_sids = []
            for rid, details in room_user_details.get(room, {}).items():
                if details.get('user_id') == user_id and rid != request.sid:
                    stale_sids.append(rid)
            
            for stale_sid in stale_sids:
                print(f"DEBUG: Pruning and notifying of stale SID {stale_sid} for user {user_id}")
                # Notify others to remove this ghost
                emit('user_left', {'sid': stale_sid}, to=room)
                
                if room in rooms and stale_sid in rooms[room]:
                    rooms[room].remove(stale_sid)
                if room in room_user_details and stale_sid in room_user_details[room]:
                    del room_user_details[room][stale_sid]

        # --- AI Proxy Logic ---
        # 1. Cancel any active proxy timer for this user
        ai_service.cancel_absence_timer(room, user_id)
        # 2. If a proxy was already active for this ID, notify others to remove it
        emit('proxy_retired', {'user_id': user_id}, to=room)
        # ----------------------

        # 2. Does a session for this room already exist?
        session_exists = room in room_host_ids
        
        # 3. Is this the original host returning?
        is_returning_host = user_id and session_exists and room_host_ids[room] == user_id
        
        # 4. Handle First-Time Initialization
        if not session_exists:
            print(f"DEBUG: Initializing new room session: {room}")
            rooms[room] = []
            room_audio_buffers[room] = [] 
            live_transcripts[room] = []
            room_user_details[room] = {}
            room_host_ids[room] = user_id 
            
            room_hosts[room] = request.sid
            join_room(room)
            rooms[room].append(request.sid)
            room_user_details[room][request.sid] = {'name': user_name, 'user_id': user_id}
            
            # Add Hidden AI Participant
            room_user_details[room]['auralis_ai'] = {'name': 'Auralis AI', 'role': 'background_ai', 'user_id': 'system_ai'}
            
            # Check for scheduled participants to start proxy timers
            try:
                # Simple lookup: match schedule where room_id or title contains room name
                schedule = Schedule.query.filter(
                    (Schedule.user_id == user_id) & 
                    (Schedule.status == 'upcoming')
                ).first()
                
                if schedule and schedule.participants:
                    print(f"[AI] Found schedule for room {room}. Monitoring participants: {schedule.participants}")
                    for p_email in schedule.participants:
                        # Start timer for each participant (except the joining host)
                        # We need an identifier for them. For now, using email as user_id proxy.
                        ai_service.start_absence_timer(room, p_email, p_email.split('@')[0], 'participant', emit)
            except Exception as e:
                print(f"[AI] Schedule lookup error: {e}")

            emit('role_assigned', {'role': 'host'})
            print(f"Room {room} session STARTED by Host {request.sid}")
            return

        # 5. Handle Host Reclamation
        if is_returning_host:
            print(f"DEBUG: Host RECLAIMING session for {room}")
            room_hosts[room] = request.sid
            join_room(room)
            if request.sid not in rooms[room]:
                rooms[room].append(request.sid)
            
            if room not in room_user_details: room_user_details[room] = {}
            room_user_details[room][request.sid] = {'name': user_name, 'user_id': user_id}
            
            emit('role_assigned', {'role': 'host'})
            
            # Sync Host with existing participants
            existing_users = []
            for uid in rooms.get(room, []):
                if uid != request.sid:
                    details = room_user_details.get(room, {}).get(uid, {})
                    uname = details.get('name', 'Participant')
                    u_id = details.get('user_id')
                    existing_users.append({'sid': uid, 'name': uname, 'role': 'participant', 'user_id': u_id})
            
            if existing_users:
                emit('all_users', {'users': existing_users})
            
            # Notify others the host is back
            emit('user_joined', {'sid': request.sid, 'name': user_name, 'role': 'host', 'user_id': user_id}, to=room, include_self=False)
            
            # Re-notify about waiting guests
            waiting_others = room_user_details.get(room, {})
            for other_sid, details in waiting_others.items():
                if other_sid not in rooms.get(room, []) and other_sid != request.sid:
                    print(f"DEBUG: Notifying host of waiting guest: {other_sid}")
                    emit('entry_requested', {'sid': other_sid, 'name': details.get('name', 'Guest')})
            
            return

        # 6. Handle Guest Join (Existing Session)
        print(f"DEBUG: Guest {user_name} joining existing session {room}")
        if request.sid not in rooms.get(room, []):
            # MANDATORY: Notify Guest they are waiting
            emit('waiting_for_approval', {}, to=request.sid)
            
            # Store guest details
            if room not in room_user_details: room_user_details[room] = {}
            room_user_details[room][request.sid] = {'name': user_name, 'user_id': user_id}
            
            # Notify host if online
            host_sid = room_hosts.get(room)
            if host_sid:
                emit('entry_requested', {'sid': request.sid, 'name': user_name}, to=host_sid)
            else:
                print(f"DEBUG: Host for {room} is currently offline. Guest {request.sid} queued.")
        else:
            # Already in room (rejoin after approval)
            emit('room_joined_success', {'role': 'participant'})

    @socketio.on('approve_entry')
    def handle_approve_entry(data):
        target_sid = data.get('target_sid')
        room = data.get('room')
        
        if not target_sid or not room: return
        room = room.strip()

        # Verify requester is the host
        if room_hosts.get(room) == request.sid:
            try:
                join_room(room, sid=target_sid) 
                
                if room not in rooms: rooms[room] = []
                if target_sid not in rooms[room]: rooms[room].append(target_sid)
                
                # 1. Notify the new joiner they are in
                emit('room_joined_success', {'role': 'participant'}, to=target_sid)
                
                # 2. Tell the new joiner about everyone else
                existing_users_details = []
                for uid in rooms[room]:
                    if uid != target_sid:
                        details = room_user_details.get(room, {}).get(uid, {})
                        uname = details.get('name', 'Unknown')
                        u_id = details.get('user_id')
                        urole = 'host' if room_hosts.get(room) == uid else 'participant'
                        existing_users_details.append({'sid': uid, 'name': uname, 'role': urole, 'user_id': u_id})

                emit('all_users', {'users': existing_users_details}, to=target_sid)
                
                # 3. Tell everyone else about the new joiner
                details = room_user_details.get(room, {}).get(target_sid, {})
                target_name = details.get('name', 'Guest')
                target_user_id = details.get('user_id')
                
                print(f"DEBUG: Approving entry for {target_sid} in {room}. Found name: {target_name}, ID: {target_user_id}")
                emit('user_joined', {'sid': target_sid, 'name': target_name, 'role': 'participant', 'user_id': target_user_id}, to=room, include_self=False)
                
                print(f"Host {request.sid} admitted {target_sid} to Room {room}")
            except Exception as e:
                print(f"Error admitting user {target_sid} (likely disconnected): {e}")
                # Clean up if needed
                if room in rooms and target_sid in rooms[room]:
                    rooms[room].remove(target_sid)
                if room in room_user_details and target_sid in room_user_details[room]:
                    del room_user_details[room][target_sid]

    @socketio.on('deny_entry')
    def handle_deny_entry(data):
        target_sid = data.get('target_sid')
        emit('entry_denied', {}, to=target_sid)

    # --- Host Controls ---
    @socketio.on('kick_user')
    def handle_kick_user(data):
        room = data.get('room')
        if room: room = room.strip()
        target_sid = data.get('target_sid')
        
        if room_hosts.get(room) != request.sid: return
        
        emit('kicked', {}, to=target_sid)
        if room in rooms and target_sid in rooms[room]:
            rooms[room].remove(target_sid)
            
        # Clean up user details
        if room in room_user_details and target_sid in room_user_details[room]:
            del room_user_details[room][target_sid]
            
        emit('user_left', {'sid': target_sid}, to=room)
        print(f"Host {request.sid} kicked {target_sid} from {room}")

    @socketio.on('mute_all')
    def handle_mute_all(data):
        room = data.get('room')
        if room: room = room.strip()
        if room_hosts.get(room) != request.sid: return
        
        # Emit to everyone EXCEPT host
        emit('mute_force', {}, to=room, include_self=False)
        print(f"Host {request.sid} muted all in {room}")

    @socketio.on('end_meeting_for_all')
    def handle_end_meeting_for_all(data):
        room = data.get('room')
        if room: room = room.strip()
        if room_hosts.get(room) != request.sid: return
        
        emit('meeting_ended', {}, to=room)
        
        # Cleanup
        if room in rooms: del rooms[room]
        if room in room_hosts: del room_hosts[room]
        if room in room_user_details: del room_user_details[room]
        print(f"Host {request.sid} ended meeting {room} for all")

    @socketio.on('leave_room')
    def handle_leave_room(data):
        room = data.get('room')
        if room: room = room.strip()
        if not room: return
        leave_room(room)
        if room in rooms and request.sid in rooms[room]:
            rooms[room].remove(request.sid)
        emit('user_left', {'sid': request.sid}, to=room)

    # Audio Handling
    @socketio.on('audio_chunk')
    def handle_audio_chunk(data):
        room = data.get('room')
        if room: room = room.strip()
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
        
        # Trigger proxy check for other users
        handle_proxy_check({'room': room, 'message': message})

        # Check for trigger
        if "@ai" in message.lower() or "auralis" in message.lower():
            transcript = " ".join(live_transcripts.get(room, []))
            response = generate_avatar_chat(message, transcript=transcript)
            emit('chat_message', {
                'sender': 'Auralis_AI',
                'message': response,
                'timestamp': datetime.utcnow().isoformat()
            }, to=room)

    @socketio.on('toggle_proxy')
    def handle_toggle_proxy(data):
        room = data.get('room')
        enabled = data.get('enabled', False)
        proxy_states[request.sid] = enabled
        print(f"Proxy Mode {'Enabled' if enabled else 'Disabled'} for {request.sid} in {room}")
        
        # Notify others (optional, for UI indicators)
        emit('proxy_status_updated', {'sid': request.sid, 'enabled': enabled}, to=room)

    # Automatically trigger proxy if enabled for other users
    @socketio.on('chat_message_proxy_check')
    def handle_proxy_check(data):
        room = data.get('room')
        message = data.get('message')
        sender_sid = request.sid
        
        transcript = " ".join(live_transcripts.get(room, []))
        
        # Check all other users in the room for proxy mode
        for sid, details in room_user_details.get(room, {}).items():
            if sid != sender_sid and proxy_states.get(sid):
                from utils.ai_response import generate_proxy_response
                user_name = details.get('name', 'User')
                # In a real app, we'd fetch user_profile from DB
                response = generate_proxy_response(user_name, "A team member", message, transcript)
                
                if response:
                    emit('chat_message', {
                        'sender': sid,
                        'message': f"[Proxy] {response}",
                        'timestamp': datetime.utcnow().isoformat()
                    }, to=room)
    @socketio.on('send_reaction')
    def handle_reaction(data):
        room = data.get('room')
        reaction = data.get('reaction')
        emit('reaction_received', {'sid': request.sid, 'reaction': reaction}, to=room)

    @socketio.on('raise_hand')
    def handle_raise_hand(data):
        room = data.get('room')
        is_raised = data.get('is_raised', False)
        emit('hand_status_updated', {'sid': request.sid, 'is_raised': is_raised}, to=room)

    @socketio.on('create_poll')
    def handle_create_poll(data):
        room = data.get('room')
        poll = {
            'id': datetime.utcnow().timestamp(),
            'creator': request.sid,
            'question': data.get('question'),
            'options': data.get('options'),
            'votes': {opt: [] for opt in data.get('options', [])},
            'active': True
        }
        emit('poll_created', poll, to=room)

    @socketio.on('cast_vote')
    def handle_cast_vote(data):
        room = data.get('room')
        poll_id = data.get('poll_id')
        option = data.get('option')
        emit('vote_received', {'poll_id': poll_id, 'option': option, 'voter': request.sid}, to=room)

    @socketio.on('breakout_move')
    def handle_breakout_move(data):
        room = data.get('room')
        target_sid = data.get('target_sid')
        breakout_id = data.get('breakout_id')
        emit('move_to_breakout', {'room': breakout_id}, to=target_sid)

    @socketio.on('proxy_joined')
    def handle_proxy_joined(data):
        room = data.get('room')
        if not room: return
        # Store proxy in room_user_details
        proxy_sid = f"proxy_{data['user_id']}"
        if room not in room_user_details: room_user_details[room] = {}
        room_user_details[room][proxy_sid] = {
            'name': data['name'],
            'role': 'proxy',
            'user_id': data['user_id']
        }
        emit('user_joined', {
            'sid': proxy_sid,
            'name': data['name'],
            'role': 'proxy',
            'user_id': data['user_id']
        }, to=room)

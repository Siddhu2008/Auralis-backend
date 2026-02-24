# Backend README

## Google OAuth Setup

### Google Cloud Console Configuration

**Authorized JavaScript Origins:**
- http://localhost:5173
- https://auralis-frontend.vercel.app

**Authorized Redirect URIs:**
- http://localhost:5000/api/auth/google/callback
- https://auralis-backend-eq1o.onrender.com/api/auth/google/callback

### Environment Variables

Set these in your `.env` (see `.env.example`):
- GOOGLE_CLIENT_ID=your-google-client-id
- GOOGLE_CLIENT_SECRET=your-google-client-secret
- GOOGLE_REDIRECT_URI=http://localhost:5000/api/auth/google/callback

For production, set:
- GOOGLE_REDIRECT_URI=https://auralis-backend-eq1o.onrender.com/api/auth/google/callback

### Notes
- Never hardcode client IDs, secrets, or URLs in code.
- Use environment variables for all secrets and URLs.

## Meeting System v2 (Production Track)

New REST base path: `/api/v2/meetings`

Key endpoints:
- `POST /schedule`
- `POST /{meetingCodeOrId}/join-request`
- `POST /{meetingCodeOrId}/token`
- `POST /{meetingId}/waiting-room/{entryId}/decision`
- `POST /{meetingId}/chat`
- `POST /{meetingId}/transcript`
- `POST /{meetingId}/summary/live`
- `POST /{meetingId}/recording`
- `POST /{meetingId}/complete`
- `GET /past`
- `GET /{meetingCodeOrId}`

Real-time events (Socket.IO):
- `meeting:join`, `meeting:leave`, `meeting:signal`
- `meeting:chat`, `meeting:transcript`, `meeting:raise_hand`, `meeting:reaction`
- `meeting:host_control` (`mute_participant`, `remove_participant`, `disable_screen_share`, `lock_meeting`, `end_for_all`)

Recommended env:
- `DATABASE_URL=postgresql://...`
- `SECRET_KEY=...`
- `MAIL_USERNAME=...`
- `MAIL_PASSWORD=...`
- `GEMINI_API_KEY=...`

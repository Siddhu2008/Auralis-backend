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

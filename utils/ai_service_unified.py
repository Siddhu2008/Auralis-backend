import os
import logging
import requests
import time
import threading
import hashlib
from collections import deque
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple in-memory response cache to avoid duplicate calls
# ---------------------------------------------------------------------------
_response_cache = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_get(key):
    entry = _response_cache.get(key)
    if entry and (time.time() - entry['ts']) < _CACHE_TTL:
        return entry['val']
    return None


def _cache_set(key, val):
    _response_cache[key] = {'val': val, 'ts': time.time()}
    # Prune old entries
    now = time.time()
    expired = [k for k, v in _response_cache.items() if now - v['ts'] > _CACHE_TTL * 2]
    for k in expired:
        _response_cache.pop(k, None)


class KeyRateLimiter:
    def __init__(self, max_per_minute=13):
        self._max = max_per_minute
        self._window = 60
        self._calls = {}  # key -> deque of timestamps
        self._lock = threading.Lock()

    def can_call(self, key):
        with self._lock:
            now = time.time()
            if key not in self._calls:
                self._calls[key] = deque()
            q = self._calls[key]
            # Remove calls older than 60s
            while q and now - q[0] > self._window:
                q.popleft()
            return len(q) < self._max

    def record(self, key):
        with self._lock:
            self._calls[key].append(time.time())

    def wait_until_ready(self, key, timeout=30):
        """Block until the key is ready, up to timeout seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.can_call(key):
                return True
            time.sleep(1)
        return False


# ---------------------------------------------------------------------------
# Key Health Manager: Tracks "bad" keys to avoid latency
# ---------------------------------------------------------------------------
class KeyHealthManager:
    def __init__(self):
        self._dead_until = {}  # key -> timestamp
        self._lock = threading.Lock()

    def mark_bad(self, key, reason="unknown"):
        """
        Mark a key as bad for a duration based on the failure reason.
        - AUTH: Permanent for session (24h)
        - QUOTA: 1 hour
        - TRANS: 5 minutes
        """
        with self._lock:
            duration = 3600  # Default 1 hour
            if reason == "AUTH":
                duration = 86400  # 24 hours
            elif reason == "TRANS":
                duration = 300   # 5 minutes
            
            logger.warning(f"[KeyHealth] Marking key {key[:4]}... as BAD ({reason}) for {duration}s")
            self._dead_until[key] = time.time() + duration

    def is_healthy(self, key):
        with self._lock:
            until = self._dead_until.get(key, 0)
            if time.time() > until:
                if key in self._dead_until:
                    self._dead_until.pop(key)
                return True
            return False


_health_manager = KeyHealthManager()
_rate_limiter = KeyRateLimiter(max_per_minute=60)


class AIService:
    _instance = None
    _keys = []
    _last_key_count = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIService, cls).__new__(cls)
            cls._instance._initialize_clients()
        return cls._instance

    def _initialize_clients(self, force=False):
        """Initialize all available API keys from environment."""
        keys = []
        key_names = [
            'GROQ_API_KEY', 'GROQ_API_KEY1', 'GROQ_API_KEY2', 'GROQ_API_KEY3',
            'GEMINI_API_KEY', 'GOOGLE_API_KEY',
            'GEMINI_API_KEY2', 'GEMINI_API_KEY3',
            'GEMINI_API_KEY4', 'GEMINI_API_KEY5',
            'OPENAI_API_KEY', 'XAI_API_KEY', 'GROK_API_KEY'
        ]
        for name in key_names:
            val = os.getenv(name)
            if val and val.strip() and val not in keys:
                keys.append(val.strip())

        if not force and len(keys) == self._last_key_count and self._keys:
            return

        self._keys = keys
        self._last_key_count = len(self._keys)
        if self._keys:
            logger.info(f"[AIService] System online with {len(self._keys)} keys.")

    @property
    def client(self):
        return self._keys[0] if self._keys else None

    def _get_provider(self, key):
        if key.startswith("sk-"):
            return "openai"
        if key.startswith("gsk_"):
            return "groq"
        if key.startswith("xai-"):
            return "xai"
        return "gemini"

    def _mask_key(self, key):
        if not key: return "None"
        return f"{key[:4]}...{key[-4:]}"

    def _generate_gemini(self, prompt, model, key, config):
        if not _rate_limiter.wait_until_ready(key, timeout=15):
            return "ERR_RATE_LIMIT"

        target_model = model if model.startswith("models/") else f"models/{model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            _rate_limiter.record(key)
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code == 200:
                data = res.json()
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Handle specific failure cases
            if res.status_code == 429:
                _health_manager.mark_bad(key, "QUOTA")
                return "ERR_QUOTA"
            if res.status_code in (401, 403):
                _health_manager.mark_bad(key, "AUTH")
                return "ERR_AUTH"
            
            return f"ERR_{res.status_code}"
        except Exception as e:
            logger.error(f"[AIService] Exception on {self._mask_key(key)}: {str(e)}")
            return "ERR_TRANS"

    def _generate_openai(self, prompt, model, key, config):
        target_model = model if "gpt" in model else "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": [{"role": "user", "content": prompt}]}
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
            
            print(f"[DEBUG] OpenAI Failed: {res.status_code} - {res.text}")
            if res.status_code in (401, 403):
                _health_manager.mark_bad(key, "AUTH")
                return "ERR_AUTH"
            return f"ERR_{res.status_code}"
        except Exception as e:
            print(f"[DEBUG] OpenAI Exception: {e}")
            return "ERR_TRANS"

    def _generate_groq(self, prompt, model, key, config):
        """Generate content using Groq (Llama). compatible with OpenAI API."""
        target_model = model if model else "llama-3.3-70b-versatile"
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": [{"role": "user", "content": prompt}]}
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
            
            print(f"[DEBUG] Groq Failed: {res.status_code} - {res.text}")
            if res.status_code in (401, 403):
                _health_manager.mark_bad(key, "AUTH")
                return "ERR_AUTH"
            if res.status_code == 429:
                _health_manager.mark_bad(key, "QUOTA")
                return "ERR_QUOTA"
            return f"ERR_{res.status_code}"
        except Exception as e:
            print(f"[DEBUG] Groq Exception: {e}")
            return "ERR_TRANS"

    def _generate_xai(self, prompt, model, key, config):
        """Generate content using xAI (Grok). compatible with OpenAI API."""
        target_model = model if model else "grok-beta"
        url = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": [{"role": "user", "content": prompt}]}
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
            
            print(f"[DEBUG] xAI Failed: {res.status_code} - {res.text}")
            if res.status_code in (401, 403):
                _health_manager.mark_bad(key, "AUTH")
                return "ERR_AUTH"
            if res.status_code == 429:
                _health_manager.mark_bad(key, "QUOTA")
                return "ERR_QUOTA"
            return f"ERR_{res.status_code}"
        except Exception as e:
            print(f"[DEBUG] xAI Exception: {e}")
            return "ERR_TRANS"

    def generate_content(self, prompt, model='gemini-2.0-flash', config=None):
        if not self._keys:
            self._initialize_clients(force=True)
            if not self._keys: return None

        # Cache check - Prompt-only key for maximum quota protection
        cache_key = hashlib.md5(prompt.encode()).hexdigest()
        cached = _cache_get(cache_key)
        if cached: return cached

        # Prioritize requested model
        gemini_models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash']
        openai_models = ['gpt-4o-mini', 'gpt-4o']
        groq_models = ['llama-3.1-8b-instant', 'llama-3.3-70b-versatile', 'mixtral-8x7b-32768']
        
        req_model = (model or 'gemini-1.5-flash').replace('models/', '')

        for key_idx, key in enumerate(self._keys):
            if not _health_manager.is_healthy(key):
                continue

            provider = self._get_provider(key)
            
            # Model Routing Logic: ONLY try models the provider supports
            if provider == "gemini":
                target_models = [req_model] if req_model in gemini_models else []
                target_models += [m for m in gemini_models if m != req_model]
            elif provider == "openai":
                # Map Gemini defaults to OpenAI defaults if needed
                use_model = req_model if req_model in openai_models else "gpt-4o-mini"
                target_models = [use_model] + [m for m in openai_models if m != use_model]
            elif provider == "groq":
                # Map any request to Llama if using Groq
                use_model = req_model if req_model in groq_models else "llama-3.3-70b-versatile"
                target_models = [use_model] + [m for m in groq_models if m != use_model]
            elif provider == "xai":
                xai_models = ['grok-beta', 'grok-2', 'grok-vision-beta']
                use_model = req_model if req_model in xai_models else "grok-beta"
                target_models = [use_model] + [m for m in xai_models if m != use_model]
            else:
                target_models = [req_model]

            if not target_models:
                continue

            for tm in target_models:
                for attempt in range(3): # Increased to 3 attempts
                    try:
                        if provider == "openai":
                            result = self._generate_openai(prompt, tm, key, config)
                        elif provider == "groq":
                            result = self._generate_groq(prompt, tm, key, config)
                        elif provider == "xai":
                            result = self._generate_xai(prompt, tm, key, config)
                        else:
                            result = self._generate_gemini(prompt, tm, key, config)

                        if result and not result.startswith("ERR_"):
                            _cache_set(cache_key, result)
                            return result
                        
                        print(f"[DEBUG] generate_content result: {result}")
                        
                        if result in ("ERR_AUTH", "ERR_QUOTA", "ERR_404"):
                            break # Key marked bad or model not found, move to next key/model
                        
                        # Exponential backoff for transient errors
                        wait_time = 2 ** attempt
                        print(f"[AIService] Transient error {result}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ne:
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(f"[AIService] Network error on key {self._mask_key(key)}: {ne}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    except Exception as e:
                        logger.error(f"[AIService] Unexpected error on key {self._mask_key(key)}: {e}")
                        break # Unexpected, transition to next key
        
        return None

    def get_proactive_insight(self, behavior_summary):
        """Generates a proactive suggestion based on user behavior logs."""
        prompt = f"""
        You are 'Auralis AI', a proactive personal assistant.
        Based on these recent user behavior logs:
        {behavior_summary}
        
        Generate a concise, helpful, and premium proactive suggestion for the user.
        Example: "You have a gap in your schedule, would you like me to find a slot for your 1:1?"
        Example: "You usually check meeting reports around this time. Shall I prepare a summary of your last meeting?"
        
        STRICT RULES:
        1. Keep it under 2 lines.
        2. Sound intelligent and helpful.
        3. Do NOT mention you are an AI.
        
        Insight:
        """
        return self.generate_content(prompt, model='gemini-1.5-flash')

    def get_embeddings(self, text):
        """Generates embeddings using Gemini REST API with key and model rotation."""
        if not text:
            return None

        if not self._keys:
            self._initialize_clients(force=True)
        
        gemini_keys = [k for k in self._keys if self._get_provider(k) == "gemini"]
        if not gemini_keys:
            logger.error("[AIService] No Gemini keys available for embeddings.")
            return None

        # Preference order for models and API versions
        configs = [
            {"version": "v1beta", "model": "gemini-embedding-001"},
            {"version": "v1", "model": "text-embedding-004"},
            {"version": "v1", "model": "embedding-001"},
            {"version": "v1beta", "model": "text-embedding-004"}
        ]

        for key in gemini_keys:
            for config in configs:
                version = config["version"]
                model = config["model"]
                url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:embedContent?key={key}"
                payload = {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]}
                }

                try:
                    res = requests.post(url, json=payload, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        if 'embedding' in data and 'values' in data['embedding']:
                            return data['embedding']['values']
                    
                    # Silent fallback for 404/403/429
                    if res.status_code not in [404, 403, 429]:
                        logger.debug(f"[AIService] Embedding config failed ({model}, {version}): {res.status_code}")
                except Exception as e:
                    continue
        
        logger.error("[AIService] All embedding attempts failed after exhaustion.")
        return None

ai_service = AIService()

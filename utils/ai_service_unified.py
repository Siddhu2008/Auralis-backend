import os
import json
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
_CACHE_TTL = 30  # seconds


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


# ---------------------------------------------------------------------------
# Per-key rate limiter: max 13 req/min (safe floor for 15 req/min free tier)
# ---------------------------------------------------------------------------
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


_rate_limiter = KeyRateLimiter(max_per_minute=13)


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
            'GEMINI_API_KEY', 'GOOGLE_API_KEY',
            'GEMINI_API_KEY2', 'GEMINI_API_KEY3',
            'GEMINI_API_KEY4', 'GEMINI_API_KEY5',
            'OPENAI_API_KEY'
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
            logger.info(f"[AIService] Initialized with {len(self._keys)} key(s).")

    @property
    def client(self):
        return self._keys[0] if self._keys else None

    def _get_provider(self, key):
        if key.startswith("sk-"):
            return "openai"
        return "gemini"

    def _generate_gemini(self, prompt, model, key, config):
        # Wait for rate limit window if needed
        if not _rate_limiter.wait_until_ready(key, timeout=20):
            logger.warning(f"[AIService] Key rate limit not cleared in time, skipping.")
            return f"ERR_RATE_LIMIT"

        target_model = model if model.startswith("models/") else f"models/{model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {}}
        if config:
            if "response_mime_type" in config:
                payload["generationConfig"]["response_mime_type"] = config["response_mime_type"]
            if "max_output_tokens" in config:
                payload["generationConfig"]["max_output_tokens"] = config["max_output_tokens"]

        try:
            _rate_limiter.record(key)
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
            elif res.status_code == 429:
                logger.warning(f"[AIService] 429 on {target_model} - rate limited.")
                return f"ERR_429"
            else:
                logger.error(f"[AIService] FAIL: {target_model} -> {res.status_code} {res.text[:150]}")
                return f"ERR_{res.status_code}"
        except Exception as e:
            return f"EXC_{str(e)[:80]}"

    def _generate_openai(self, prompt, model, key, config):
        target_model = "gpt-4o-mini"  # cheapest reliable model
        if "gpt" in model:
            target_model = model

        if not _rate_limiter.wait_until_ready(key, timeout=20):
            return f"ERR_RATE_LIMIT"

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": [{"role": "user", "content": prompt}]}
        if config:
            if config.get("response_mime_type") == "application/json":
                payload["response_format"] = {"type": "json_object"}
            if "max_output_tokens" in config:
                payload["max_tokens"] = config["max_output_tokens"]

        try:
            _rate_limiter.record(key)
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
            return f"ERR_{res.status_code}_{res.text[:100]}"
        except Exception as e:
            return f"EXC_{str(e)[:80]}"

    def generate_content(self, prompt, model='gemini-2.5-flash', config=None):
        # Re-initialize keys if not loaded yet (handles late dotenv load)
        if not self._keys:
            self._initialize_clients(force=True)
            if not self._keys:
                logger.error("[AIService] No API keys available.")
                return None

        # Check cache for identical prompts
        cache_key = hashlib.md5((prompt + model).encode()).hexdigest()
        cached = _cache_get(cache_key)
        if cached:
            logger.info("[AIService] Cache hit.")
            return cached

        # BUG-009 FIX: Try multiple models in order of preference/availability
        gemini_models = [
            'gemini-1.5-flash-8b',
            'gemini-2.0-flash',
            'gemini-1.5-flash',
            'gemini-1.5-pro',
        ]
        openai_models = ['gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo']

        for key_idx, key in enumerate(self._keys):
            provider = self._get_provider(key)
            models_to_try = openai_models if provider == "openai" else gemini_models

            for target_model in models_to_try:
                if provider == "openai":
                    result = self._generate_openai(prompt, target_model, key, config)
                else:
                    result = self._generate_gemini(prompt, target_model, key, config)

                if result and not result.startswith("ERR_") and not result.startswith("EXC_"):
                    logger.info(f"[AIService] SUCCESS: Provider[{provider}] Key[{key_idx}] Model[{target_model}]")
                    _cache_set(cache_key, result)
                    return result
                else:
                    logger.warning(f"[AIService] FAIL: Provider[{provider}] Key[{key_idx}] Model[{target_model}] -> {result}")
                    if result in ("ERR_429", "ERR_RATE_LIMIT"):
                        break  # This key is exhausted, try next key

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


ai_service = AIService()

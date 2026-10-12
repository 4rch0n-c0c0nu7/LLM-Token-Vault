"""
Shared uplink table + usage ledger for Lumi and the Token Dashboard.

- One provider table (name, endpoint, model) so the dashboard and Lumi can't drift apart.
  Model overrides picked in the dashboard live in ~/lumi_providers.json.
- A usage ledger (~/.lumi_usage.json) that Lumi writes after every cloud call: real token
  counts, last success/error, and the provider's own rate-limit headers.
- Real health checks: a tiny chat call against the configured model (a key check alone
  can't tell you the model was retired).
- Passphrase-protected key export/import, because the vault is locked to this machine.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

CONFIG_FILE = os.path.expanduser("~/lumi_providers.json")
USAGE_FILE = os.path.expanduser("~/.lumi_usage.json")
ROUTING_FILE = os.path.expanduser("~/lumi_routing.json")
STATE_FILE = "/dev/shm/lumi_active_provider.json" if os.path.isdir("/dev/shm") else os.path.expanduser("~/.lumi_active_provider.json")

# id = routing value the dashboard writes; name = what Lumi prints and the GUI shows.
DEFAULT_PROVIDERS = [
    {"id": "GROQ", "name": "Groq", "key_env": "GROQ_API_KEY",
     "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "tools": True},
    {"id": "GOOGLE", "name": "Google Gemini", "key_env": "GOOGLE_API_KEY",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-3.6-flash", "tools": False},
    {"id": "CEREBRAS", "name": "Cerebras", "key_env": "CEREBRAS_API_KEY",
     "base_url": "https://api.cerebras.ai/v1", "model": "qwen-3.8-27b", "tools": True},
    {"id": "OPENROUTER", "name": "OpenRouter", "key_env": "OPENROUTER_API_KEY",
     "base_url": "https://openrouter.ai/api/v1", "model": "nvidia/nemotron-3-super-120b-a12b:free", "tools": True},
    {"id": "MISTRAL", "name": "Mistral", "key_env": "MISTRAL_API_KEY",
     "base_url": "https://api.mistral.ai/v1", "model": "ministral-8b-latest", "tools": True},
]
ROUTE_IDS = ["LOCAL"] + [p["id"] for p in DEFAULT_PROVIDERS] + ["AUTO"]


# ---------- small file helpers ----------

def _read_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ---------- providers & routing ----------

def load_providers():
    """Default table with the dashboard's per-provider overrides (model) applied."""
    overrides = _read_json(CONFIG_FILE, {})
    out = []
    for p in DEFAULT_PROVIDERS:
        q = dict(p)
        q.update({k: v for k, v in overrides.get(p["id"], {}).items() if k in ("model",)})
        out.append(q)
    return out


def set_model(pid, model):
    overrides = _read_json(CONFIG_FILE, {})
    overrides.setdefault(pid, {})["model"] = model
    _write_json(CONFIG_FILE, overrides)


def get_route():
    mode = str(_read_json(ROUTING_FILE, {}).get("default_mode", "LOCAL")).upper()
    return mode if mode in ROUTE_IDS else "LOCAL"


def set_route(mode):
    _write_json(ROUTING_FILE, {"default_mode": mode, "strategy": "auto" if mode == "AUTO" else "manual"})


def get_last_active():
    return _read_json(STATE_FILE, {}).get("active_provider")


def set_last_active(name):
    try:
        _write_json(STATE_FILE, {"active_provider": name})
    except Exception:
        pass


def ordered_providers(route=None):
    """
    Cloud try-order. A specific provider picked in the dashboard always goes first (the rest are
    fallbacks); AUTO starts with whichever answered last. LOCAL -> empty list.
    """
    route = route or get_route()
    provs = load_providers()
    if route == "LOCAL":
        return []
    if route == "AUTO":
        first = (get_last_active() or "").upper()
        return sorted(provs, key=lambda p: 0 if p["name"].upper() == first else 1)
    return sorted(provs, key=lambda p: 0 if p["id"] == route else 1)


# ---------- usage ledger ----------

def _ratelimits(headers):
    """Keep the provider's own x-ratelimit-* headers (Groq, Cerebras, Mistral send them)."""
    if not headers:
        return {}
    return {k.lower(): str(v) for k, v in dict(headers).items() if k.lower().startswith("x-ratelimit")}


def record(pid, ok, usage=None, headers=None, error=None, model=None):
    """Called by Lumi after each cloud attempt. Counters reset at local midnight."""
    try:
        data = _read_json(USAGE_FILE, {})
        today = time.strftime("%Y-%m-%d")
        e = data.get(pid) or {}
        if e.get("day") != today:
            e.update({"day": today, "requests_today": 0, "tokens_today": 0, "errors_today": 0})
        now = time.time()
        if ok:
            e["requests_today"] += 1
            if usage:
                total = usage.get("total_tokens") if isinstance(usage, dict) else getattr(usage, "total_tokens", None)
                e["tokens_today"] += int(total or 0)
            e["last_ok"] = now
            if model:
                e["last_model"] = model
        else:
            e["errors_today"] += 1
            e["last_error"] = now
            e["last_error_msg"] = str(error)[:300] if error else "unknown error"
        rl = _ratelimits(headers)
        if rl:
            e["ratelimits"] = rl
            e["ratelimits_at"] = now
        data[pid] = e
        _write_json(USAGE_FILE, data)
    except Exception:
        pass  # usage tracking must never break a conversation


def load_usage():
    data = _read_json(USAGE_FILE, {})
    today = time.strftime("%Y-%m-%d")
    for e in data.values():
        if e.get("day") != today:
            e.update({"requests_today": 0, "tokens_today": 0, "errors_today": 0})
    return data


RL_LABELS = {
    "requests": "requests", "tokens": "tokens/min",
    "requests-day": "requests/day", "tokens-day": "tokens/day",
    "requests-minute": "requests/min", "tokens-minute": "tokens/min",
    "tokens-month": "tokens/month", "requests-month": "requests/month", "req-minute": "requests/min",
}


def ratelimit_meters(rl, pid=None):
    """[(label, remaining, limit)] from stored headers. Groq's plain 'requests' is per day."""
    out = []
    for k, lim in rl.items():
        if not k.startswith("x-ratelimit-limit-"):
            continue
        suffix = k[len("x-ratelimit-limit-"):]
        rem = rl.get("x-ratelimit-remaining-" + suffix)
        try:
            lim_i, rem_i = int(float(lim)), int(float(rem))
        except (TypeError, ValueError):
            continue
        if lim_i <= 0:
            continue
        label = RL_LABELS.get(suffix, suffix)
        if pid == "GROQ" and suffix == "requests":
            label = "requests/day"
        out.append((label, rem_i, lim_i))
    return sorted(out, key=lambda m: m[0])


# ---------- live checks (dashboard) ----------

def _request(url, key, body=None, timeout=20):
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "lumi-uplink/2", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}"), r.headers


def _http_error_text(e):
    try:
        body = json.loads(e.read().decode())
        err = body.get("error", body)
        if isinstance(err, list):
            err = err[0] if err else {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return f"HTTP {e.code}: {msg}"[:300]
    except Exception:
        return f"HTTP {e.code}: {e.reason}"


def test_provider(p, key):
    """
    A real (tiny) chat call on the configured model. Returns (ok, message).
    Records the result in the ledger so the card reflects it.
    """
    url = p["base_url"].rstrip("/") + "/chat/completions"
    body = {"model": p["model"], "messages": [{"role": "user", "content": "Reply with: ok"}], "max_tokens": 16}
    try:
        resp, headers = _request(url, key, body)
        record(p["id"], True, resp.get("usage"), headers, model=p["model"])
        return True, f"OK ({p['model']})"
    except urllib.error.HTTPError as e:
        msg = _http_error_text(e)
        record(p["id"], False, headers=e.headers, error=msg)
        return False, msg
    except Exception as e:
        record(p["id"], False, error=e)
        return False, str(e)[:300]


def list_models(p, key):
    resp, _ = _request(p["base_url"].rstrip("/") + "/models", key)
    ids = [m.get("id", "") for m in resp.get("data", [])]
    return sorted(i[len("models/"):] if i.startswith("models/") else i for i in ids if i)


def openrouter_credit(key):
    """OpenRouter's own account usage (USD) — free GET, no tokens spent."""
    resp, _ = _request("https://openrouter.ai/api/v1/key", key)
    return resp.get("data", {})


# ---------- moving keys to another machine ----------

def _pass_cipher(passphrase, salt):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode())))


def export_keys(keys, passphrase, path):
    """The vault only opens on this machine; this file opens anywhere with the passphrase."""
    salt = os.urandom(16)
    token = _pass_cipher(passphrase, salt).encrypt(json.dumps(keys).encode())
    with open(path, "w") as f:
        json.dump({"format": "lumi-keys-export-v1", "salt": base64.b64encode(salt).decode(),
                   "data": token.decode()}, f)
    os.chmod(path, 0o600)


def import_keys(path, passphrase):
    with open(path) as f:
        blob = json.load(f)
    if blob.get("format") != "lumi-keys-export-v1":
        raise ValueError("not a Lumi key export file")
    salt = base64.b64decode(blob["salt"])
    return json.loads(_pass_cipher(passphrase, salt).decrypt(blob["data"].encode()))

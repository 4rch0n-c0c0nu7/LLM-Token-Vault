import os
import json
import base64
import uuid
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEYS_FILE = os.path.expanduser("~/lumi_keys.json")

# Vault format v1: MAGIC(5) | salt(16) | nonce(12) | AES-256-GCM ciphertext.
# MAGIC also serves as the GCM associated data, so the header is authenticated.
MAGIC = b"LVLT1"
KDF_ITERS = 200_000


def _machine_secret():
    """Hardware binding: /etc/machine-id if present, else the MAC-derived node id.

    The derived key only works on this machine, so a stolen vault file is useless
    elsewhere. Set LUMI_VAULT_PASSPHRASE to additionally require a secret that is
    never written to disk (protects against local compromise too).
    """
    secret = str(uuid.getnode()).encode("utf-8")
    if os.path.exists("/etc/machine-id"):
        try:
            with open("/etc/machine-id", "rb") as f:
                secret = f.read().strip()
        except OSError:
            pass
    passphrase = os.environ.get("LUMI_VAULT_PASSPHRASE", "")
    if passphrase:
        secret = secret + b"|" + passphrase.encode("utf-8")
    return secret


def _derive_key(salt):
    """256-bit AES key from the machine secret and a random per-vault salt."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=KDF_ITERS)
    return kdf.derive(_machine_secret())


def _load_v1(raw):
    salt, nonce, ct = raw[5:21], raw[21:33], raw[33:]
    pt = AESGCM(_derive_key(salt)).decrypt(nonce, ct, MAGIC)
    return json.loads(pt.decode("utf-8"))


def _load_legacy_fernet(raw):
    """Back-compat read of pre-v1 vaults (Fernet = AES-128-CBC+HMAC, static salt)."""
    from cryptography.fernet import Fernet
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"lumi_tactical_secure_salt_2026", iterations=100000)
    fkey = base64.urlsafe_b64encode(kdf.derive(_machine_secret()))
    return json.loads(Fernet(fkey).decrypt(raw).decode("utf-8"))


def secure_load_keys():
    """Load and decrypt the API keys. Transparently reads legacy vaults and
    migrates them to v1 on the next save."""
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "rb") as f:
            raw = f.read()
        if raw.startswith(MAGIC):
            return _load_v1(raw)
        if raw.startswith(b"gAAAAA"):          # legacy Fernet vault
            data = _load_legacy_fernet(raw)
            secure_save_keys(data)             # auto-migrate to v1
            return data
        return json.loads(raw.decode("utf-8"))  # legacy plaintext
    except Exception as e:
        print(f"[!] Vault decryption error: {e}")
        return {}


def secure_save_keys(keys_dict):
    """Encrypt (AES-256-GCM, random salt + nonce) and atomically save the vault."""
    try:
        salt, nonce = os.urandom(16), os.urandom(12)
        ct = AESGCM(_derive_key(salt)).encrypt(
            nonce, json.dumps(keys_dict, indent=4).encode("utf-8"), MAGIC)
        tmp = KEYS_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(MAGIC + salt + nonce + ct)
        os.replace(tmp, KEYS_FILE)             # atomic; never a half-written vault
        return True
    except Exception as e:
        print(f"[!] Vault encryption error: {e}")
        return False

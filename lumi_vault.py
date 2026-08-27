import os
import json
import base64
import uuid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KEYS_FILE = os.path.expanduser("~/lumi_keys.json")

def _get_encryption_key():
    """
    Derives a consistent encryption key tied to the specific hardware.
    This prevents keys from being stolen and used on another machine.
    """
    salt = b"lumi_tactical_secure_salt_2026"
    
    # Cross-platform fallback (Windows/Mac) using network MAC address
    machine_id_str = str(uuid.getnode())
    machine_id = machine_id_str.encode('utf-8')
    
    # Use Linux machine-id if available (Primary method for Pi/Linux)
    if os.path.exists("/etc/machine-id"):
        try:
            with open("/etc/machine-id", "rb") as f:
                machine_id = f.read().strip()
        except:
            pass
            
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(machine_id))
    return key

def secure_load_keys():
    """Loads and decrypts the API keys from the local vault."""
    if not os.path.exists(KEYS_FILE):
        return {}
        
    try:
        with open(KEYS_FILE, "rb") as f:
            raw_data = f.read()
            
        # Fernet encrypted tokens always start with 'gAAAAA'
        if raw_data.startswith(b"gAAAAA"):
            f_cipher = Fernet(_get_encryption_key())
            decrypted_data = f_cipher.decrypt(raw_data)
            return json.loads(decrypted_data.decode('utf-8'))
        else:
            # Fallback for unencrypted legacy keys
            return json.loads(raw_data.decode('utf-8'))
    except Exception as e:
        print(f"[!] Vault decryption error: {e}")
        return {}

def secure_save_keys(keys_dict):
    """Encrypts and saves the API keys to the local vault."""
    try:
        f_cipher = Fernet(_get_encryption_key())
        json_bytes = json.dumps(keys_dict, indent=4).encode('utf-8')
        encrypted_data = f_cipher.encrypt(json_bytes)
        
        with open(KEYS_FILE, "wb") as f:
            f.write(encrypted_data)
        return True
    except Exception as e:
        print(f"[!] Vault encryption error: {e}")
        return False

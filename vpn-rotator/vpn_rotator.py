#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import time

# --- SUDO ENVIRONMENT FIX ---
HOME_DIR = "/home/dano"
os.environ["HOME"] = HOME_DIR
sys.path.append(HOME_DIR)

try:
    from lumi_vault import secure_load_keys, secure_save_keys
except ImportError:
    print("[!] ERROR: Could not import lumi_vault.py. Ensure it is in /home/dano/")
    sys.exit(1)

CONFIG_DIR = os.path.join(HOME_DIR, "vpn_configs")
STATE_FILE = os.path.join(CONFIG_DIR, "rotator_state.json")
RAM_DISK_PATH = "/dev/shm/wg0.conf"

def get_public_ip():
    try:
        result = subprocess.run(["curl", "-s", "https://ifconfig.me"], 
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        return "Unknown (Offline)"

def main():
    print("\n[⚡] Initializing Tactical VPN Rotator...")
    
    configs = sorted([f for f in os.listdir(CONFIG_DIR) if f.endswith('.conf')])
    if not configs:
        print("[!] ERROR: No .conf files found in ~/vpn_configs/")
        return

    # Check if a manual target was passed from the GUI
    target_override = sys.argv[1] if len(sys.argv) > 1 else None

    last_index = -1
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                last_index = state.get("last_index", -1)
        except:
            pass

    if target_override and target_override in configs:
        target_config = target_override
        print(f"[*] MANUAL OVERRIDE: Forcing connection to {target_config}")
        next_index = configs.index(target_config)
    else:
        next_index = (last_index + 1) % len(configs)
        target_config = configs[next_index]
        print(f"[*] Target Endpoint Selected: {target_config}")

    old_ip = get_public_ip()
    print(f"[*] Current Public IP: {old_ip}")

    print("[*] Tearing down existing tunnels...")
    subprocess.run(["sudo", "ip", "link", "delete", "dev", "wg0"], stderr=subprocess.DEVNULL)
    time.sleep(1.5) 

    print("[*] Decrypting keys into volatile RAM...")
    vault_keys = secure_load_keys()
    key_id = f"VPN_KEY_{target_config.replace('.conf', '')}"
    
    private_key = vault_keys.get(key_id)
    if not private_key:
        print(f"[!] ERROR: No PrivateKey found in encrypted vault under ID: {key_id}")
        return

    with open(os.path.join(CONFIG_DIR, target_config), "r") as f:
        template_data = f.read()

    live_config_data = template_data.replace("VAULT_INJECT", private_key)

    try:
        with open(RAM_DISK_PATH, "w") as f:
            f.write(live_config_data)
        os.chmod(RAM_DISK_PATH, 0o600) 
    except Exception as e:
        print(f"[!] ERROR: Failed to write to RAM disk: {e}")
        return

    print(f"[🛡️] Initiating WireGuard uplink to {target_config}...")
    tunnel_up = subprocess.run(["sudo", "wg-quick", "up", RAM_DISK_PATH], 
                               capture_output=True, text=True)

    if os.path.exists(RAM_DISK_PATH):
        os.remove(RAM_DISK_PATH)
    print("[✓] RAM disk wiped. Keys are safe.")

    if tunnel_up.returncode != 0:
        print(f"[!] Failed to bring up tunnel. Error:\n{tunnel_up.stderr}")
        return

    print("[*] Verifying routing tables and IP address (Waiting 4 seconds)...")
    time.sleep(4)
    new_ip = get_public_ip()

    if new_ip == old_ip or new_ip == "Unknown (Offline)":
        print("[!] WARNING: IP did not change or connection failed.")
    else:
        print(f"\n[✓] SUCCESS! Tunnel established.")
        print(f"    Old IP: {old_ip}")
        print(f"    New IP: {new_ip}")
        
        with open(STATE_FILE, "w") as f:
            json.dump({"last_index": next_index, "last_config": target_config}, f)

if __name__ == "__main__":
    main()

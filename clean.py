import requests
import socket
import time
import re

SOURCE_URL = "https://raw.githubusercontent.com/VSd223/vpn/refs/heads/main/vpn"
MAX_LATENCY = 0.8
OUTPUT_FILE = "clean_vpn.txt"

def check_server(host, port):
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        latency = time.time() - start
        sock.close()
        if result == 0:
            return latency
        return None
    except:
        return None

def extract_host_port(url):
    pattern = r'vless://[^@]+@([^:]+):(\d+)'
    match = re.search(pattern, url)
    if match:
        return match.group(1), int(match.group(2))
    return None, None

def main():
    print(f"Downloading: {SOURCE_URL}")
    response = requests.get(SOURCE_URL)
    lines = response.text.strip().split('\n')
    
    clean_lines = []
    working = 0
    dead = 0
    
    for line in lines:
        if line.startswith('#'):
            clean_lines.append(line)
            continue
        
        if line.startswith('vless://'):
            host, port = extract_host_port(line)
            if host and port:
                latency = check_server(host, port)
                if latency and latency < MAX_LATENCY:
                    clean_lines.append(line)
                    working += 1
                    print(f"OK {host}:{port} - {int(latency*1000)}ms")
                else:
                    dead += 1
                    print(f"DEAD {host}:{port}")
            else:
                clean_lines.append(line)
        else:
            clean_lines.append(line)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(clean_lines))
    
    print(f"Done. Working: {working}, Removed: {dead}")

if __name__ == "__main__":
    main()

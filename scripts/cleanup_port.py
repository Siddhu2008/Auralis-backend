import os
import subprocess
import sys

def cleanup_port(port=5001):
    print(f"[*] Searching for processes on port {port}...")
    try:
        # Get the PID(s) using netstat
        cmd = f"netstat -ano | findstr :{port}"
        output = subprocess.check_output(cmd, shell=True).decode()
        
        pids = set()
        for line in output.strip().split('\n'):
            if 'LISTENING' in line or 'ESTABLISHED' in line:
                parts = line.split()
                if len(parts) >= 5:
                    pids.add(parts[-1])
        
        if not pids:
            print(f"[+] No processes found on port {port}.")
            return

        for pid in pids:
            print(f"[*] Killing process {pid}...")
            try:
                subprocess.check_call(f"taskkill /F /PID {pid}", shell=True)
                print(f"[+] Successfully killed process {pid}.")
            except Exception as e:
                print(f"[-] Failed to kill process {pid}: {e}")
                
    except subprocess.CalledProcessError:
        print(f"[+] Port {port} appears to be free.")
    except Exception as e:
        print(f"[-] Error during cleanup: {e}")

if __name__ == "__main__":
    cleanup_port()

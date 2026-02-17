#!/usr/bin/env python3
import os
import sys
import time
import csv
import subprocess
import re
import argparse
import shutil
from datetime import datetime
from collections import deque

# --- Configuration Constants ---
DEFAULT_LOG_DIR = "logs"
KLIPPER_LOG_PATH = os.path.expanduser("~/printer_data/logs/klippy.log")
CYCLICTEST_CMD = ["cyclictest", "-m", "-Sp90", "-i200", "-h400", "-l1000", "-q"] 
VCGENCMD_PATH = "/usr/bin/vcgencmd"

# Thresholds
THROT_MASK_UNDERVOLTAGE = 0x50005  
TEMP_WARN_THRESHOLD = 75.0       
TEMP_CRIT_THRESHOLD = 80.0       
LATENCY_WARN_US = 3000           
LATENCY_CRIT_US = 5000           
CPU_LOAD_WARN_PERCENT = 85.0
MEM_SWAP_WARN_MB = 100           

# CSV Headers - Pre-defined to ensure column consistency
CSV_HEADERS = [
    'timestamp', 'check_duration_ms',
    'throttled_hex', 'throttled_alarm', 'ue_now', 'freq_cap_now', 'throt_now', 'soft_temp_now',
    'core_voltage', 'cpu_temp', 'temp_warning',
    'cpu_usage', 'cpu_saturation', 'ram_used_pct', 'swap_used_mb', 'mem_pressure', 'load_1min', 'load_5min',
    'max_latency_us', 'latency_high',
    'usb_events', 'log_errors', 'notes'
]

# --- Monitor Classes ---

class MonitorBase:
    def __init__(self):
        self.name = "Base"

    def check(self):
        """Returns dict of metrics or None"""
        raise NotImplementedError

class USBMonitor(MonitorBase):
    def __init__(self):
        self.name = "USB"
        self.last_seen_lines = deque(maxlen=20)
        self.patterns = [
            re.compile(r"usb disconnect", re.IGNORECASE),
            re.compile(r"reset high-speed USB device", re.IGNORECASE),
            re.compile(r"ttyACM\d+ disconnect", re.IGNORECASE),
            re.compile(r"xHCI host controller not responding", re.IGNORECASE)
        ]

    def check(self):
        try:
            # Get last 20 lines of kernel log
            result = subprocess.run(['dmesg', '-k', '|', 'tail', '-n', '20'], 
                                    capture_output=True, text=True, shell=True)
            current_lines = result.stdout.strip().split('\n')
            
            new_events = []
            for line in current_lines:
                line = line.strip()
                if not line: continue
                
                # Deduplication
                if line in self.last_seen_lines:
                    continue
                
                # Check patterns
                for pattern in self.patterns:
                    if pattern.search(line):
                        new_events.append(line)
                        break 

            self.last_seen_lines.clear()
            self.last_seen_lines.extend(current_lines)
            
            if new_events:
                return {'usb_events': "; ".join(new_events)}
            return None
            
        except Exception as e:
            return {'usb_events': f"Error: {str(e)}"}

class PowerMonitor(MonitorBase):
    def __init__(self):
        self.name = "Power"

    def check(self):
        data = {}
        try:
            # Check Throttled
            res = subprocess.run([VCGENCMD_PATH, 'get_throttled'], capture_output=True, text=True)
            if res.returncode == 0:
                val_str = res.stdout.strip().split('=')[1]
                val_int = int(val_str, 16)
                data['throttled_hex'] = val_str
                if val_int != 0x0:
                    data['throttled_alarm'] = True
                    if val_int & 0x1: data['ue_now'] = True
                    if val_int & 0x2: data['freq_cap_now'] = True
                    if val_int & 0x4: data['throt_now'] = True
                    if val_int & 0x8: data['soft_temp_now'] = True

            # Check Voltage
            res = subprocess.run([VCGENCMD_PATH, 'measure_volts'], capture_output=True, text=True)
            if res.returncode == 0:
                volt_str = res.stdout.strip().split('=')[1].replace('V', '')
                data['core_voltage'] = float(volt_str)

            # Check Temp
            res = subprocess.run([VCGENCMD_PATH, 'measure_temp'], capture_output=True, text=True)
            if res.returncode == 0:
                temp_str = res.stdout.strip().split('=')[1].replace("'C", '')
                temp_val = float(temp_str)
                data['cpu_temp'] = temp_val
                if temp_val > TEMP_WARN_THRESHOLD:
                    data['temp_warning'] = True
        
        except Exception:
             pass 
        
        return data

class SystemMonitor(MonitorBase):
    def __init__(self):
        self.name = "System"
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            self.psutil = None

    def check(self):
        data = {}
        if self.psutil:
            cpu_pct = self.psutil.cpu_percent(interval=None)
            data['cpu_usage'] = cpu_pct
            if cpu_pct > CPU_LOAD_WARN_PERCENT:
                data['cpu_saturation'] = True
            
            mem = self.psutil.virtual_memory()
            swap = self.psutil.swap_memory()
            data['ram_used_pct'] = mem.percent
            data['swap_used_mb'] = round(swap.used / (1024 * 1024), 2)
            
            if data['swap_used_mb'] > MEM_SWAP_WARN_MB:
                data['mem_pressure'] = True
                
        else:
            load = os.getloadavg()
            data['load_1min'] = load[0]
            data['load_5min'] = load[1]
            
        return data

class LatencyMonitor(MonitorBase):
    def __init__(self):
        self.name = "Latency"

    def check(self):
        try:
            cmd = list(CYCLICTEST_CMD)
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                match = re.search(r"Max:\s*(\d+)", result.stdout)
                if match:
                    max_lat = int(match.group(1))
                    return {'max_latency_us': max_lat, 
                            'latency_high': max_lat > LATENCY_WARN_US}
            return None
        except Exception:
            return None

class LogMonitor(MonitorBase):
    def __init__(self, log_path):
        self.name = "KlipperLog"
        self.log_path = log_path
        self.file_pos = 0
        self.patterns = {
            'timer_close': re.compile(r"Timer too close"),
            'mcu_shutdown': re.compile(r"MCU '.*' shutdown"),
            'lost_comm': re.compile(r"Timeout on serial communication")
        }
        if os.path.exists(self.log_path):
            self.file_pos = os.path.getsize(self.log_path)

    def check(self):
        if not os.path.exists(self.log_path): return None

        data = {}
        try:
            current_size = os.path.getsize(self.log_path)
            if current_size < self.file_pos:
                self.file_pos = 0 # Log rotated
            
            if current_size > self.file_pos:
                with open(self.log_path, 'r', errors='ignore') as f:
                    f.seek(self.file_pos)
                    new_lines = f.readlines()
                    self.file_pos = f.tell()
                    
                    errors = []
                    for line in new_lines:
                        for key, pattern in self.patterns.items():
                            if pattern.search(line):
                                errors.append(f"{key}: {line.strip()[:60]}")
                    
                    if errors:
                        data['log_errors'] = "; ".join(errors)

        except Exception:
            pass
        return data if data else None

# --- Logger Class ---

class CSVLogger:
    def __init__(self, directory, backup_directory=None):
        self.directory = directory
        self.backup_directory = backup_directory
        self.filename = f"monitor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.filepath = os.path.join(self.directory, self.filename)
        self.headers = CSV_HEADERS
        
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)
        
        if self.backup_directory and not os.path.exists(self.backup_directory):
            os.makedirs(self.backup_directory)

        self.file = open(self.filepath, 'w', newline='', buffering=1)
        self.writer = csv.DictWriter(self.file, fieldnames=self.headers, extrasaction='ignore')
        self.writer.writeheader()
        self.file.flush()

        # Init backup file
        self.backup_file = None
        self.backup_writer = None
        if self.backup_directory:
            backup_path = os.path.join(self.backup_directory, self.filename)
            self.backup_file = open(backup_path, 'w', newline='', buffering=1)
            self.backup_writer = csv.DictWriter(self.backup_file, fieldnames=self.headers, extrasaction='ignore')
            self.backup_writer.writeheader()
            self.backup_file.flush()

    def log(self, data):
        # Flatten data
        row = {'timestamp': datetime.now().isoformat()} # type: ignore
        row.update(data)
        
        try:
            self.writer.writerow(row)
            self.file.flush()
            os.fsync(self.file.fileno())
            
            if self.backup_writer and self.backup_file:
                self.backup_writer.writerow(row)
                self.backup_file.flush()
                # optional: os.fsync(self.backup_file.fileno())
                
        except Exception as e:
            print(f"Logging failed: {e}")

    def close(self):
        if self.file: self.file.close()
        if self.backup_file: self.backup_file.close()

# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Voron Printer Health Monitor")
    parser.add_argument("--interval", type=float, default=1.0, help="Check interval in seconds")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Directory to save logs")
    parser.add_argument("--backup-dir", help="Directory for backup logs")
    parser.add_argument("--verbose", action='store_true', help="Print stats to console")
    args = parser.parse_args()

    # Monitors
    monitors = [
        USBMonitor(),
        PowerMonitor(),
        SystemMonitor(),
        LatencyMonitor(),
        LogMonitor(KLIPPER_LOG_PATH)
    ]

    logger = CSVLogger(args.log_dir, args.backup_dir)
    print(f"Starting Voron Monitor...")
    print(f"Main Log: {logger.filepath}")
    if args.backup_dir:
        print(f"Backup Log: {os.path.join(args.backup_dir, logger.filename)}")

    try:
        while True:
            start_time = time.time()
            current_data = {}
            
            for m in monitors:
                try:
                    res = m.check()
                    if res:
                        current_data.update(res) # type: ignore
                except Exception as e:
                    print(f"Monitor {m.name} error: {e}")
            
            duration = (time.time() - start_time) * 1000
            current_data['check_duration_ms'] = round(duration, 2)
            
            logger.log(current_data)
            
            if args.verbose:
                # Print only interesting data
                interesting = {k:v for k,v in current_data.items() if k not in ['timestamp', 'check_duration_ms'] and v}
                if interesting:
                    print(f"[{datetime.now().time()}] {interesting}")

            elapsed = time.time() - start_time
            sleep_time = max(0, args.interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopping monitor...")
    except Exception as e:
        print(f"\nCritical Error: {e}")
    finally:
        logger.close()

if __name__ == "__main__":
    main()

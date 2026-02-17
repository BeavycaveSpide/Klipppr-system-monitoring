# Voron Printer Monitor

A Python script designed to run alongside Klipper on a Raspberry Pi (or similar Linux host) to monitor system health and detect potential causes of print failures, such as USB disconnects, undervoltage, thermal throttling, and latency spikes.

## Features

- **USB Monitoring**: Scans kernel logs (`dmesg`) for USB disconnects and EMI events.
- **Power Monitoring**: Checks for undervoltage, frequency capping, and overheating using `vcgencmd`.
- **System Load**: Monitors CPU usage, RAM, and Swap usage (requires `psutil`).
- **Real-time Latency**: Runs `cyclictest` to detect scheduling latency spikes (requires `rt-tests`).
- **Klipper Log Watcher**: Tails `klippy.log` for "Timer too close" and MCU shutdown errors.
- **Robust Logging**: Writes to CSV with immediate flush to disk to prevent data loss.
- **Backup**: Optional dual-logging to a secondary location (e.g., USB drive).

## Quick Install (Zip Method)

1.  Download `voron_monitor.zip` and transfer it to your Pi.
2.  Unzip and run the installer:
    ```bash
    unzip voron_monitor.zip
    cd voron_monitor_pack
    chmod +x install.sh
    ./install.sh
    ```

## Manual Installation

1.  **Install Dependencies**:
    The script requires `python3-psutil` for system metrics and `rt-tests` for latency checking. `vcgencmd` is usually pre-installed on Raspberry Pi OS.

    ```bash
    sudo apt-get update
    sudo apt-get install python3-psutil rt-tests
    ```

    *Note: `vcgencmd` is specific to Raspberry Pi. If running on a different generic Linux host, the power monitoring section will be skipped.*

2.  **Download Script**:
    Place `voron_monitor.py` in your home directory or desired location.

    ```bash
    wget <url_to_script> -O voron_monitor.py
    chmod +x voron_monitor.py
    ```

## Usage

Run the script manually to test:

```bash
python3 voron_monitor.py --interval 1 --verbose
```

### Arguments

- `--interval`: Time in seconds between checks (default: 1.0).
- `--log-dir`: Directory to save logs (default: `logs`).
- `--backup-dir`: Optional secondary directory for backup logs (e.g., `/mnt/usb`).
- `--verbose`: Print status to console.

### Example: Run in Background

To run continuously in the background (nohup):

```bash
nohup python3 voron_monitor.py --log-dir ~/printer_data/logs/monitor --backup-dir /mnt/usb/backup &
```

### Example: Run as a Systemd Service (Recommended)

1.  Create a service file: `sudo nano /etc/systemd/system/voron_monitor.service`

    ```ini
    [Unit]
    Description=Voron Health Monitor
    After=network.target

    [Service]
    Type=simple
    User=pi
    ExecStart=/usr/bin/python3 /home/pi/voron_monitor.py --log-dir /home/pi/printer_data/logs/monitor
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
    ```

2.  Enable and start:

    ```bash
    sudo systemctl enable voron_monitor
    sudo systemctl start voron_monitor
    ```

## Output Analysis

The logs are saved as CSV files with timestamps. Look for the following columns:

- `throttled_alarm`: True if undervoltage or throttling is occurring.
- `temp_warning`: True if CPU temp > 75°C.
- `latency_high`: True if real-time latency > 3000µs.
- `usb_events`: Any text found in `dmesg` relating to USB errors.
- `log_errors`: Errors found in `klippy.log` (e.g., Timer too close).

## Troubleshooting

- **`cyclictest not found`**: Install `rt-tests`.
- **`vcgencmd not found`**: Ensure you are running on a Raspberry Pi or compatible OS with `libraspberrypi-bin` installed.

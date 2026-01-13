#!/usr/bin/env python3

import json
import subprocess
import sys
import requests
import time
import signal
import pickle
import os
import argparse
from datetime import datetime, timedelta
from collections import deque

DEFAULT_WU_DATA = {
    'dateutc': 'now',
    'action': 'updateraw'
}

WUNDERGROUND_URL = 'https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php'

# Global delta trackers for stateful conversions
_stateful_delta_trackers = {}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(SCRIPT_DIR, 'config.json')
DEFAULT_PICKLE_FILE = os.path.join(SCRIPT_DIR, 'delta_trackers.pkl')
CONFIG_FILE = DEFAULT_CONFIG_FILE
PICKLE_FILE = DEFAULT_PICKLE_FILE


class DeltaTracker:
    """Stateful tracker that provides delta from first to last."""

    def __init__(self, field_name, period_in_minutes=60):
        self.field_name = field_name
        self.values = deque()  # Store (timestamp, value) tuples
        self.period_in_minutes = period_in_minutes

    def add_value(self, value, timestamp=None):
        if timestamp is None:
            timestamp = datetime.now()

        self.values.append((timestamp, value))

        # Clean up old values
        cutoff_time = timestamp - timedelta(minutes=self.period_in_minutes)
        while len(self.values) and self.values[0][0] < cutoff_time:
            self.values.popleft()

        # Return delta between first and last values in the hour window
        if len(self.values) < 2:
            return 0

        first_value = self.values[0][1]
        last_value = self.values[-1][1]

        # Handle counter resets by returning 0 if negative
        delta = last_value - first_value
        return max(0, delta)


def save_delta_trackers():
    """Save delta trackers to pickle file."""
    try:
        with open(PICKLE_FILE, 'wb') as f:
            pickle.dump(_stateful_delta_trackers, f)
        print(f"Saved delta trackers to {PICKLE_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"Error saving delta trackers: {e}", file=sys.stderr)


def load_delta_trackers():
    """Load delta trackers from pickle file."""
    global _stateful_delta_trackers
    try:
        if os.path.exists(PICKLE_FILE):
            with open(PICKLE_FILE, 'rb') as f:
                _stateful_delta_trackers = pickle.load(f)
            print(f"Loaded delta trackers from {PICKLE_FILE}", file=sys.stderr)
        else:
            print("No saved delta trackers found", file=sys.stderr)
    except Exception as e:
        print(f"Error loading delta trackers: {e}", file=sys.stderr)
        _stateful_delta_trackers = {}


def signal_handler(signum, _frame):
    """Handle signals by saving delta trackers."""
    print(f"\nReceived signal {signum}, saving delta trackers...", file=sys.stderr)
    save_delta_trackers()
    # Set flag to prevent double save in finally block
    global _signal_received
    _signal_received = True
    sys.exit(0)


def get_rtl_command(config):
    rtl_freq = config['rtl_sdr']['frequency']
    decoder_id = config['rtl_sdr']['decoder_id']
    rtl_cmd = [
        'rtl_433',
        '-v',
        '-R', decoder_id,
        '-f', rtl_freq,
        '-F', 'json'
    ]
    return rtl_cmd


def upload_to_wunderground(_station_id, _station_key, params):
    """see: https://support.weather.com/s/article/PWS-Upload-Protocol?language=en_US"""

    try:
        response = requests.get(WUNDERGROUND_URL, params=params, timeout=10)
        if response.status_code == 200 and 'success' in response.text:
            return True
        print(f"Wunderground upload failed: {response.text}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error uploading to Wunderground: {e}", file=sys.stderr)
        return False


def apply_conversion(value, conversion_type, field_name=None):
    def delta_hour_mm_to_in(x):
        if field_name not in _stateful_delta_trackers:
            _stateful_delta_trackers[field_name] = DeltaTracker(field_name, period_in_minutes=60)
        delta_mm = _stateful_delta_trackers[field_name].add_value(x)
        return delta_mm / 25.4  # Convert mm to inches
    
    def delta_day_mm_to_in(x):
        if field_name not in _stateful_delta_trackers:
            _stateful_delta_trackers[field_name] = DeltaTracker(field_name, period_in_minutes=60*24)
        delta_mm = _stateful_delta_trackers[field_name].add_value(x)
        return delta_mm / 25.4  # Convert mm to inches

    conversions = {
        'c_to_f': lambda x: x * 9/5 + 32,
        'ms_to_mph': lambda x: x * 2.237,
        'mm_to_in': lambda x: x / 25.4,
        'hpa_to_inhg': lambda x: x * 0.02953,
        'local_to_utc': lambda x: datetime.fromtimestamp(x).astimezone().utctimetuple() if isinstance(x, (int, float)) else time.mktime(datetime.now().utctimetuple()),
        'delta_hour_mm_to_in': delta_hour_mm_to_in,
        'delta_day_mm_to_in': delta_day_mm_to_in,
    }

    if conversion_type:
        try:
            return conversions[conversion_type](value)
        except Exception as e:
            print(
                f"error converting {value} with conversion {conversion_type}: {e}", file=sys.stderr)
    return value


def populate_wunderground_request_data(json_data, translations, config):
    """Parse rtl_433 JSON and convert to Wunderground format using config
    translations."""
    wu_data = DEFAULT_WU_DATA
    wu_data['PASSWORD'] = config['wunderground']['station_key']
    wu_data['ID'] = config['wunderground']['station_id']

    for trans in translations:
        rtl_field = trans['rtl_field']
        if rtl_field in json_data:
            wu_field = trans['field']
            value = json_data[rtl_field]

            # Apply conversion if specified
            if 'conversion' in trans:
                value = apply_conversion(
                    value, trans['conversion'], rtl_field)
            wu_data[wu_field] = value
    return wu_data


def parse_args():
    parser = argparse.ArgumentParser(
        description='WH24B Weather Station data collector for Weather Underground'
    )
    parser.add_argument(
        '--config', '-c',
        default=DEFAULT_CONFIG_FILE,
        help=f'Path to config file (default: {DEFAULT_CONFIG_FILE})'
    )
    parser.add_argument(
        '--pickle-file', '-p',
        default=DEFAULT_PICKLE_FILE,
        help=f'Path to pickle file for delta trackers (default: {DEFAULT_PICKLE_FILE})'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    global CONFIG_FILE, PICKLE_FILE
    CONFIG_FILE = args.config
    PICKLE_FILE = args.pickle_file
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    load_delta_trackers()
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR: Could not load configuration from {CONFIG_FILE}: {e}", file=sys.stderr)
        sys.exit(1)
    station_id = config.get('wunderground', {}).get('station_id')
    station_key = config.get('wunderground', {}).get('station_key')
    translations = config.get('wunderground', {}).get('translations', {})
    if not station_id or not station_key:
        print('ERROR: Wunderground station_id and station_key required in config.json', file=sys.stderr)
        return
    print(
        f"Starting Wunderground uploads for station {station_id}", file=sys.stderr)

    # Start an external program (rtl_433) that outputs weather data as json objects.
    rtl_cmd = get_rtl_command(config)
    print('rtl command:', ' '.join(rtl_cmd))

    try:
        process = subprocess.Popen(rtl_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True)
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                json_data = json.loads(line)
                print(f"Received data:\t{json_data}", file=sys.stderr)
                wu_data = populate_wunderground_request_data(
                    json_data, translations, config)
                print('update wunderground:\t', wu_data)
                upload_to_wunderground(station_id, station_key, wu_data)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON received: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Error processing data: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print('\nReceived interrupt signal, shutting down...', file=sys.stderr)
    except Exception as e:
        print('\nError starting rtl process', file=sys.stderr)
    finally:
        save_delta_trackers()
        process.terminate()
        process.wait()
        if process.returncode != 0:
            print(f"Error: rtl process exited with code {process.returncode}")
            print(f"Stderr output follows:")
            print("".join(list(process.stderr)))


if __name__ == '__main__':
    main()

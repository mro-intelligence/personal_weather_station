# WH24B Weather Station Data Collector

This tool collects weather data from an weather station using rtl_433 and uploads it to Weather Underground Personal Weather Station (PWS).

## Requirements

- Python 3.6+
- rtl_433 installed and in PATH
- RTL-SDR compatible hardware (radio receiver)
- Weather Underground Personal Weather Station account

## Installation

1. Install required Python packages with `pip` or your favorite installer:
```bash
pip install requests
```

2. Install rtl_433:
```bash
# Ubuntu/Debian
sudo apt-get install rtl-433

# macOS with Homebrew
brew install rtl_433
```

## Configuration

Copy `config-sample.json` to `config.json` and edit with your settings:

- `rtl_sdr.decoder_id`: RTL_433 decoder ID for your weather station
- `rtl_sdr.frequency`: Frequency to listen on (e.g., "915M")
- `wunderground.station_id`: Your Weather Underground station ID
- `wunderground.station_key`: Your Weather Underground station key
- `wunderground.translations`: Field mappings from rtl_433 JSON to Wunderground format

### Field Translations

The `translations` section maps rtl_433 JSON fields to Weather Underground fields with optional unit conversions:

```json
"translations": {
    "temperature_C": {"field": "tempf", "conversion": "c_to_f"},
    "humidity": {"field": "humidity"},
    "wind_avg_m_s": {"field": "windspeedmph", "conversion": "ms_to_mph"}
}
```

Available conversions:
- `c_to_f`: Celsius to Fahrenheit
- `ms_to_mph`: Meters per second to miles per hour
- `mm_to_in`: Millimeters to inches
- `hpa_to_inhg`: Hectopascals to inches of mercury
- `local_to_utc`: Local timestamp to UTC

## Usage

Run the collector:
```bash
python collect_weather.py
```

The program will:
1. Start rtl_433 with the configured parameters
2. Parse JSON weather data from rtl_433 output
3. Convert units as specified in translations
4. Upload data to Weather Underground

Press Ctrl+C to stop.

## Weather Underground Setup

1. Create an account at https://www.wunderground.com
2. Register a Personal Weather Station
3. Note your Station ID and Station Key
4. Add these to your `config.json`

## Troubleshooting

- Ensure rtl_433 works independently: `rtl_433 -R 78 -f 915M -F json`
- Check that your RTL-SDR device is detected: `rtl_test`
- Verify your Weather Underground credentials are correct
- Monitor stderr output for detailed logging
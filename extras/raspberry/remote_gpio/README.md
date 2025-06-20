Remote GPIO Server for Raspberry Pi
===================================

This project provides a simple HTTP server to control GPIO pins on a Raspberry Pi via a REST API. The API supports optional HTTP Basic Authentication.

---

Features
--------

- Control GPIO pins (on/off)
- Query current pin status
- Optional HTTP Basic Auth protection
- Lightweight using the Bottle framework
- Runs as a systemd service

---

Requirements
------------

- Raspberry Pi running Raspbian / Raspberry Pi OS
- Python 3
- GPIO Python library (RPi.GPIO)
- bottle web framework

---

Installation
------------

1. Install Python 3 and pip (if not already installed):

   sudo apt update
   sudo apt install python3 python3-pip

2. Install dependencies:

   pip3 install -r requirements.txt

3. Copy the server script (e.g. remote_gpio_server.py) to your Raspberry Pi.

---

Configuration
-------------

- The username and password for HTTP Basic Auth are set in the script (USERNAME and PASSWORD).
- If both username and password are set to empty strings (""), no authentication is required.

---

Usage
-----

API Endpoints:

- Control GPIO:

  POST /gpio/<pin>/<action>

  - <pin>: GPIO pin number (BCM numbering)
  - <action>: on or off

  Example:

    curl -u admin:secret -X POST http://raspberrypi.local:8000/gpio/17/on

- Get GPIO status:

  GET /gpio/<pin>

  Example:

    curl -u admin:secret http://raspberrypi.local:8000/gpio/17

- Server status:

  GET /

---

systemd Service
---------------

Create the file /etc/systemd/system/remote_gpio.service with the following content:

[Unit]
Description=Remote GPIO Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/remote_gpio_server.py
WorkingDirectory=/path/to
Restart=always
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

Start and enable the service:

sudo systemctl daemon-reload
sudo systemctl start remote_gpio.service
sudo systemctl enable remote_gpio.service

Check service status:

sudo systemctl status remote_gpio.service

---

Security Notes
--------------

- Use a strong password if the API is accessible on your network.
- Consider firewall rules to restrict access.
- If username and password are empty, the server is unprotected.

---

License
-------

MIT License

(c) 2025 Christian Kvasny

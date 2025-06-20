#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2025 Christian Kvasny chris(at)ckvsoft.at
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#  THE SOFTWARE.
#
#  Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#

from bottle import Bottle, request, response, run
import RPi.GPIO as GPIO
import base64

USERNAME = "admin"  # oder "" für keine Auth
PASSWORD = "geheim" # oder "" für keine Auth

def check_auth():
    if not USERNAME or not PASSWORD:
        return True  # Auth deaktiviert, immer erlaubt
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        return False
    encoded = auth.split(" ")[1]
    decoded = base64.b64decode(encoded).decode("utf-8")
    user, pw = decoded.split(":", 1)
    return user == USERNAME and pw == PASSWORD

def require_auth():
    if not check_auth():
        response.headers["WWW-Authenticate"] = 'Basic realm="Remote GPIO"'
        response.status = 401
        return {"error": "Unauthorized"}

# Bottle App
app = Bottle()
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
pin_states = {}

@app.post("/gpio/<pin:int>/<action>")
def gpio_control(pin, action):
    auth = require_auth()
    if auth: return auth

    try:
        GPIO.setup(pin, GPIO.OUT)
        if action == "on":
            GPIO.output(pin, GPIO.HIGH)
            pin_states[pin] = "on"
        elif action == "off":
            GPIO.output(pin, GPIO.LOW)
            pin_states[pin] = "off"
        else:
            response.status = 400
            return {"error": "Invalid action. Use 'on' or 'off'."}
        return {"pin": pin, "action": action, "status": "ok"}

    except Exception as e:
        response.status = 500
        return {"error": str(e)}

@app.get("/gpio/<pin:int>")
def gpio_status(pin):
    auth = require_auth()
    if auth: return auth

    state = pin_states.get(pin, "unknown")
    return {"pin": pin, "state": state}

@app.get("/")
def status():
    auth = require_auth()
    if auth: return auth

    return {"status": "Remote GPIO Server running", "pins": pin_states}

if __name__ == "__main__":
    run(app, host="0.0.0.0", port=8000)

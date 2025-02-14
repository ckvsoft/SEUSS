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

from websockets.sync.server import serve as ws_serv
import websockets
import json
from core.log import CustomLogger

class WebSocketServer:
    def __init__(self):
        self.clients = set()  # Set of connected clients
        self.logger = CustomLogger()
        self.last_message = None
        self.server = None

    def handler(self, websocket):
        """Handles incoming WebSocket connections synchronously."""
        self.clients.add(websocket)
        try:
            remote_address = websocket.socket.getpeername()
            self.logger.log.info(f"Client connected: {remote_address}")
        except Exception as e:
            self.logger.log.error(f"Could not determine client address: {e}")
            remote_address = None

        if self.last_message:
            try:
                websocket.send(json.dumps(self.last_message))
                # self.logger.log.info(f"Sent last message to new client: {self.last_message}")
            except Exception as e:
                self.logger.log.error(f"Error sending last message: {e}")

        try:
            # Waiting for incoming messages from the client
            while True:
                message = websocket.recv()
                self.logger.log.debug(f"Message from client: {message}")
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.log.debug(f"Connection closed: {e}")
        finally:
            # Remove the client from the list of connections
            self.clients.discard(websocket)
            if remote_address:
                self.logger.log.debug(f"Client disconnected: {remote_address}")

    def send_data_to_all_clients(self, message):
        """Sends a message to all connected WebSocket clients synchronously."""
        self.last_message = message
        if not self.clients:
            # self.logger.log.info("No connected clients")
            print("No connected clients")
            return
        for client in list(self.clients):
            try:
                client.send(json.dumps(message))
                # self.logger.log.info(f"Message sent to client: {message}")
            except Exception as e:
                self.logger.log.error(f"Error sending message to client: {e}")
                self.clients.discard(client)  # Remove faulty clients

    def emit_ws(self, message):
        self.send_data_to_all_clients(message)

    def run(self, host="0.0.0.0", port=8765):
        """Starts the WebSocket server synchronously."""
        with ws_serv(self.handler, host, port) as self.server:
            self.logger.log.info(f"start WebSocket server host:{host} port:{port}")
            self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.logger.log.debug(f"WebSocket server has stopped.")


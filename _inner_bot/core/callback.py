"""Callback-Server für n8n (HTTP). Empfängt Ticket-Antworten."""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from core.config import BOT_SECRET
from core.logging import logger

_pending_tickets = {}
_PENDING_MAX = 500


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP Server der Antworten von n8n empfängt. Auth via BOT_SECRET Header."""
    def do_POST(self):
        # Auth-Pflicht: Ohne gesetztes BOT_SECRET werden KEINE Requests akzeptiert.
        if not BOT_SECRET:
            logger.warning('Callback-Server: BOT_SECRET ist nicht gesetzt – Anfrage abgelehnt.')
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Server nicht konfiguriert'}).encode())
            return

        auth_header = self.headers.get('X-Bot-Secret', '')
        if auth_header != BOT_SECRET:
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode())
            return

        if self.path == '/ticket-callback':
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f'Callback: Ungültiger JSON-Body: {e}')
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Ungültiger JSON-Body'}).encode())
                return

            ticket_number = body.get('ticket_number')
            channel_id = body.get('channel_id')
            ai_response = body.get('output', body.get('text', 'Keine Antwort'))

            logger.info(f'Callback empfangen: Ticket #{ticket_number}')

            if ticket_number and channel_id:
                _pending_tickets[ticket_number] = {
                    'channel_id': channel_id,
                    'response': ai_response
                }
                # Begrenztes Wachstum: älteste Einträge verwerfen
                while len(_pending_tickets) > _PENDING_MAX:
                    _pending_tickets.pop(next(iter(_pending_tickets)))

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def start_callback_server(port=5681):
    if not BOT_SECRET:
        logger.warning('Callback-Server: BOT_SECRET fehlt – Server nimmt KEINE Anfragen an.')
    server = HTTPServer(('127.0.0.1', port), CallbackHandler)
    logger.info(f'Callback Server läuft auf Port {port}')
    server.serve_forever()

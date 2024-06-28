# The API Engine

import os
import asyncio
import logging
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
from src.context_manager import ContextManager
from src.system_4 import System4
from src.system_5 import System5
from src.mpu_cluster import MPUCluster
from threading import Lock
import redis

# Flask setup for API Engine
app = Flask(__name__)
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

class APIEngine:
    def __init__(self):
        self.nlp_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
        self.context_manager = ContextManager()
        self.system4 = System4(self.nlp_model, self.context_manager)
        self.system5 = System5()
        self.mpu_cluster = MPUCluster()
        self.rate_limit_lock = Lock()

    async def process_text(self, text):
        return await self.system4.process_text(text)

    async def secure_communication(self, message):
        await self.system5.secure_send(message)
        return await self.system5.secure_receive(message)

    async def parallel_processing(self, tasks):
        return await self.mpu_cluster.implement_parallel_processing(tasks)

    def external_api_request(self, endpoint, params, headers):
        return self.system5.external_api_request(endpoint, params, headers)

    def api_gateway_logic(self, client_id):
        with self.rate_limit_lock:
            rate_limit_key = f"rate_limit:{client_id}"
            current_limit = redis_client.get(rate_limit_key)
            if current_limit and int(current_limit) >= 10:
                return False, "Rate limit exceeded"
            redis_client.incr(rate_limit_key)
            redis_client.expire(rate_limit_key, 60)
        return True, ""

# API Routes
engine = APIEngine()

@app.route('/process_text', methods=['POST'])
async def process_text():
    data = await request.json
    text = data.get('text', '')
    client_id = data.get('client_id', '')

    allowed, message = engine.api_gateway_logic(client_id)
    if not allowed:
        return jsonify({"error": message}), 429

    context = await engine.process_text(text)
    return jsonify({"context": context})

@app.route('/secure_communication', methods=['POST'])
async def secure_communication():
    data = await request.json
    message = data.get('message', '').encode()
    response = await engine.secure_communication(message)
    return jsonify({"response": response.decode()})

@app.route('/external_api', methods=['GET'])
def external_api():
    params = request.args.to_dict()
    headers = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
    endpoint = "https://api.example.com/data"
    api_response = engine.external_api_request(endpoint, params, headers)
    return jsonify(api_response)

if __name__ == '__main__':
    app.run(debug=True)
      

#!/usr/bin/env python3

import os
from flask import Flask, request, jsonify
from dex.apex import ApexDex


app = Flask(__name__)

env_mode = os.environ.get("ENV_MODE", "TESTNET").upper()
if env_mode == "TESTNET":
    EXPECTED_API_KEY = os.environ.get('ENCRYPTED_API_KEY_TEST')

dex = ApexDex(env_mode)

SUPPORTED_DEX_NAMES = ['apex']


@app.before_request
def check_api_key():
    api_key = request.headers.get('Authorization')
    if api_key is None:
        return jsonify({"message": "API key missing"}), 401
    elif api_key != f"{EXPECTED_API_KEY}":
        return jsonify({"message": "Invalid API key"}), 401


@app.before_request
def check_dex():
    # Get the DEX name from the request arguments
    dex_name = request.args.get('dex')
    if not dex_name:
        return jsonify({"message": "DEX missing"}), 400
    elif dex_name not in SUPPORTED_DEX_NAMES:  # Assuming you have a list of supported DEX names
        return jsonify({"message": "Unsupported DEX"}), 400


# GET /ticker
@app.route('/ticker', methods=['GET'])
def get_ticker():
    symbol = request.args.get('symbol')

    if symbol is None:
        return jsonify({
            'message': 'Missing required parameter: symbol.'
        }), 400

    return dex.get_ticker(symbol)


# GET /yesterday-pnl
@app.route('/yesterday-pnl', methods=['GET'])
def get_yesterday_pnl():
    return dex.get_yesterday_pnl()


# POST /create-order
@app.route('/create-order', methods=['POST'])
def create_order():
    data = request.json

    if 'symbol' not in data or 'size' not in data or 'side' not in data:
        return jsonify({
            'message': 'Missing required parameters: symbol, size, and/or side.'
        }), 400

    symbol = data.get('symbol')
    size = data.get('size')
    side = data.get('side')
    price = data.get('price')

    return dex.create_order(symbol, size, side, price)


# POST /close_all_positions
@app.route('/close_all_positions', methods=['POST'])
def close_all_positions():
    data = request.json

    if 'symbol' not in data:
        return jsonify({
            'message': 'Missing required parameters: symbol.'
        }), 400

    symbol = data.get('symbol')

    return dex.close_all_positions(symbol)


if __name__ == '__main__':
    app.run(debug=True)

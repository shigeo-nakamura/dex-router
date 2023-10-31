#!/usr/bin/env python3

import os
from flask import Flask, request, jsonify
from dex.apex import ApexDex

EXPECTED_API_KEY = os.environ.get('ENCRYPTED_API_KEY')
SUPPORTED_DEX_NAMES = ['apex']

app = Flask(__name__)
dex = ApexDex()


@app.before_request
def check_api_key():
	api_key = request.headers.get('Authorization')
	if api_key is None:
		return jsonify({"message": "API key missing"}), 401
	elif api_key != f"{EXPECTED_API_KEY}":
		return jsonify({"message": "Invalid API key"}), 401
	

@app.before_request
def check_dex():
    dex_name = request.args.get('dex') # Get the DEX name from the request arguments
    if not dex_name:
        return jsonify({"message": "DEX missing"}), 400
    elif dex_name not in SUPPORTED_DEX_NAMES: # Assuming you have a list of supported DEX names
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

    return dex.create_order(symbol, size, side)


if __name__ == '__main__':
	app.run(debug=True)
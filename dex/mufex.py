#!/usr/bin/env python3

import hashlib
import hmac
import json
import os

from flask import make_response, jsonify
import urllib.parse
from .abstract_dex import AbstractDex
import time
from .kms_decrypt import get_decrypted_env
import requests
from typing import Optional

MUFEX_HTTP_MAIN = "https://api.mufex.finance"
MUFEX_HTTP_TEST = "https://api.testnet.mufex.finance"


def convert_side(side, reverse=False):
    side = side.upper()
    side_map = {'BUY': 'Sell', 'SELL': 'Buy'}
    if side in side_map:
        return side_map[side] if reverse else side.capitalize()
    else:
        return 'Invalid Side'


class MufexDex(AbstractDex):
    def generate_signature(self, query_string='', json_body_string='', recv_window=5000):
        """
        Generate HMAC SHA256 signature.
        """
        timestamp = int(time.time() * 1000)
        prehash = f"{timestamp}{self.api_key}{recv_window}{query_string}{json_body_string}"
        signature = hmac.new(self.api_secret.encode(),
                             prehash.encode(), hashlib.sha256).hexdigest()
        return signature, timestamp, recv_window

    def __init__(self, env_mode="TESTNET"):
        suffix = "_MAIN" if env_mode == "MAINNET" else "_TEST"
        env_vars = {
            'MUFEX_API_KEY': get_decrypted_env(f'MUFEX_API_KEY{suffix}'),
            'MUFEX_API_SECRET': get_decrypted_env(f'MUFEX_API_SECRET{suffix}'),
        }

        missing_vars = [key for key, value in env_vars.items()
                        if value is None]
        if missing_vars:
            raise EnvironmentError(
                f"Required environment variables are not set: {', '.join(missing_vars)}")

        self.api_key = env_vars['MUFEX_API_KEY']
        self.api_secret = env_vars['MUFEX_API_SECRET']

        if env_mode == "MAINNET":
            self.mufex_http = MUFEX_HTTP_MAIN
        else:
            self.mufex_http = MUFEX_HTTP_TEST

    def get_ticker(self, symbol: str):
        endpoint = "/public/v1/market/tickers"
        symbol_without_hyphen = symbol.replace("-", "")
        params = {'symbol': symbol_without_hyphen}

        request_url = f"{self.mufex_http}{endpoint}"

        try:
            response = requests.get(
                request_url, params=params)
            response.raise_for_status()
            ret = response.json()

            price = last_price = ret["data"]["list"][0]["lastPrice"]

            return jsonify({
                'symbol': symbol,
                'price': price
            })

        except Exception as e:
            print(f"Unexpected error: {e}")
            response_content = e.response.text if e.response else 'No content'
            status_code = e.response.status_code if e.response else 'No status code'
            print(f"HTTP Response Content: {response_content}")
            print(f"HTTP Status Code: {status_code}")

            return make_response(jsonify({
                'message': str(e)
            }), 500)

    def get_balance(self):
        endpoint = "/private/v1/account/balance"
        request_url = f"{self.mufex_http}{endpoint}"
        signature, timestamp, recv_window = self.generate_signature()

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window),
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(
                request_url, headers=headers)
            response.raise_for_status()
            ret = response.json()

            code = ret['code']
            if code != 0:
                message = ret['message'] + f"({code})"
                return make_response(jsonify({
                    'message': message
                }), 500)

            equity = ret["data"]["list"][0]["equity"]
            balance = ret["data"]["list"][0]["walletBalance"]

            return jsonify({
                'equity': equity,
                'balance': balance
            })

        except Exception as e:
            print(f"Unexpected error: {e}")
            response_content = e.response.text if e.response else 'No content'
            status_code = e.response.status_code if e.response else 'No status code'
            print(f"HTTP Response Content: {response_content}")
            print(f"HTTP Status Code: {status_code}")

            return make_response(jsonify({
                'message': str(e)
            }), 500)

    def create_order(self, symbol: str, size: str, side: str, price: Optional[str]):
        ret, message = self.create_order_internal(symbol, size, side, price)
        if ret is True:
            return jsonify({})
        else:
            return make_response(jsonify({
                'message': message
            }), 500)

    def create_order_internal(self, symbol: str, size: str, side: str, price: Optional[str], reverse=False):
        endpoint = "/private/v1/trade/create"
        symbol_without_hyphen = symbol.replace("-", "")

        side = convert_side(side, reverse)
        json_body = {'symbol': symbol_without_hyphen, 'side': side, 'positionIdx': 0,
                     'orderType': 'Market', 'qty': size, 'timeInForce': 'ImmediateOrCancel'}
        json_body_string = json.dumps(json_body)

        request_url = f"{self.mufex_http}{endpoint}"

        signature, timestamp, recv_window = self.generate_signature(
            json_body_string=json_body_string)

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window),
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(
                request_url, json=json_body, headers=headers)
            response.raise_for_status()
            ret = response.json()

            message = ret['message']
            code = ret['code']
            if code != 0:
                message = message + f"error code {code}"

            return code == 0, message

        except Exception as e:
            print(f"Unexpected error: {e}")
            response_content = e.response.text if e.response else 'No content'
            status_code = e.response.status_code if e.response else 'No status code'
            print(f"HTTP Response Content: {response_content}")
            print(f"HTTP Status Code: {status_code}")
            return False, None

    def close_all_positions(self, close_symbol):
        positions = self.get_positions(close_symbol)

        for position in positions:
            size_float = float(position['size'])
            if size_float == 0.0:
                continue
            ret, message = self.create_order_internal(
                position['symbol'], position['size'], position['side'], None, True)
            if ret is False:
                return make_response(jsonify({
                    'message': message
                }), 500)

        return jsonify({})

    def get_positions(self, symbol):
        endpoint = "/private/v1/account/positions"
        params = {}

        if symbol is not None:
            symbol_without_hyphen = symbol.replace("-", "")
            params['symbol'] = symbol_without_hyphen

        request_url = f"{self.mufex_http}{endpoint}"

        signature, timestamp, recv_window = self.generate_signature(
            urllib.parse.urlencode(params))

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window)
        }

        try:
            response = requests.get(
                request_url, params=params, headers=headers)

            response.raise_for_status()
            ret = response.json()

            positions = ret['data']["list"]
            extracted_positions = []

            for position in positions:
                extracted_position = {
                    "symbol": position["symbol"],
                    "size": position["size"],
                    "side": position["side"]
                }
                extracted_positions.append(extracted_position)

            return extracted_positions

        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return []

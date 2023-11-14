#!/usr/bin/env python3

import hashlib
import hmac
import os

from flask import make_response, jsonify
from .abstract_dex import AbstractDex
import time
from .kms_decrypt import get_decrypted_env
import requests
from typing import Optional

MUFEX_HTTP_MAIN = "https://api.mufex.finance"
MUFEX_HTTP_TEST = "https://api.testnet.mufex.finance"

class MufexDex(AbstractDex):
    def generate_signature(self, query_string='', json_body_string='', recv_window=5000):
        """
        Generate HMAC SHA256 signature.
        """
        timestamp = int(time.time() * 1000)
        prehash = f"{timestamp}{self.api_key}{recv_window}{query_string}{json_body_string}"
        signature = hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()
        return signature, timestamp, recv_window

    def __init__(self, env_mode="TESTNET"):
        env_vars = {
            'MUFEX_API_KEY': get_decrypted_env(f'APEX_API_KEY'),
            'MUFEX_API_SECRET': get_decrypted_env(f'APEX_API_SECRET'),
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
        endpoint = "/api/v1/ticker"
        symbol_without_hyphen = symbol.replace("-", "")
        params = {'symbol': symbol_without_hyphen}

        request_url = f"{self.mufex_http}{endpoint}"

        signature, timestamp, recv_window = self.generate_signature(query_string=params)

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window),
            'Content-Type': 'application/json'
        }

        try:
            # Send the GET request with the constructed URL and params
            response = requests.get(request_url, params=params, headers=headers)
            response.raise_for_status()  # This will raise an exception for HTTP error responses
            ret = response.json()

            if 'data' in ret and ret['data']:
                data_first_item = ret['data'][0]

                if 'lastPrice' in data_first_item:
                    return jsonify({
                        'symbol': symbol,
                        'price': data_first_item['lastPrice']
                    })
                else:
                    error_message = 'lastPrice information is missing in the response'
                    print(error_message, ret)
                    return make_response(jsonify({
                        'message': error_message
                    }), 500)

            else:
                error_message = 'Data is missing in the response'
                print(error_message, ret)
                return make_response(jsonify({
                    'message': error_message
                }), 500)

        except requests.exceptions.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            response_content = e.response.text if e.response else 'No content'
            status_code = e.response.status_code if e.response else 'No status code'
            print(f"HTTP Response Content: {response_content}")
            print(f"HTTP Status Code: {status_code}")
            return make_response(jsonify({
                'message': f"Could not decode JSON, HTTP Status Code: {status_code}, Content: {response_content}"
            }), 500)

        except Exception as e:
            print(f"Unexpected error: {e}")
            return make_response(jsonify({
                'message': str(e)
            }), 500)

    def get_balance(self):
        ret = self.client.get_account_balance()

        if 'data' in ret:
            required_keys = ['totalEquityValue', 'availableBalance']
            data = ret['data']

            if all(key in data for key in required_keys):
                return jsonify({
                    'equity': data['totalEquityValue'],
                    'balance': data['availableBalance'],
                })

        return make_response(jsonify({
            'message': 'Some required data is missing in the response'
        }), 500)

    def modify_price_for_instant_fill(self, symbol: str, side: str, price: str):
        symbolData = {}
        for k, v in enumerate(self.configs.get('data').get('perpetualContract')):
            if v.get('symbol') == symbol:
                symbolData = v
                break

        price_float = float(price)
        tick_size_float = float(symbolData.get('tickSize'))
        if side == 'BUY':
            price_float += tick_size_float * TICK_SIZE_MULTIPLIER
        else:
            price_float -= tick_size_float * TICK_SIZE_MULTIPLIER
        return str(price_float)

    def create_order(self, symbol: str, size: str, side: str, price: Optional[str]):
        try:
            if price is None:
                worstPrice = self.client.get_worst_price(
                    symbol=symbol, side=side, size=size)
                price = worstPrice['data']['worstPrice']
            currentTime = time.time()
            limitFeeRate = self.client.account['takerFeeRate']

            symbolData = {}
            for k, v in enumerate(self.configs.get('data').get('perpetualContract')):
                if v.get('symbol') == symbol:
                    symbolData = v
                    break

            rounded_size = round_size(size, symbolData.get('stepSize'))
            rounded_price = round_size(price, symbolData.get('tickSize'))

            adjusted_price = self.modify_price_for_instant_fill(
                symbol, side, rounded_price)

            ret = self.client.create_order(symbol=symbol, side=side,
                                           type="MARKET", size=rounded_size, price=adjusted_price, limitFeeRate=limitFeeRate,
                                           expirationEpochSeconds=currentTime)

            if 'code' in ret:
                return make_response(jsonify({
                    'message': ret.get('msg', '')
                }), 500)

            return jsonify({
                'price': ret['data']['price'],
                'size': ret['data']['size'],
            })

        except Exception as e:
            print(f"An error occurred in create_order: {e}")
            return make_response(jsonify({
                'message': str(e)
            }), 500)

    def close_all_positions(self, close_symbol):
        account_data = self.client.get_account()
        position_sizes = {}

        for position in account_data['data']['openPositions']:
            symbol = position['symbol']
            side = position['side']
            size_str = position['size']
            size_float = float(position['size'])

            if size_float != 0:
                key = f"{symbol}_{side}"
                position_sizes[key] = size_str

        try:
            for key, size in position_sizes.items():
                symbol, side = key.split('_')
                if close_symbol == "" or symbol == close_symbol:
                    opposite_order_side = 'SELL' if side == 'LONG' else 'BUY'

                ticker_response = self.get_ticker(symbol)
                if ticker_response.status_code == 200:
                    price_data = ticker_response.get_json()
                    price = price_data.get('price', None)
                else:
                    price = None

                self.create_order(symbol, size, opposite_order_side, price)

            return jsonify({
            })

        except Exception as e:
            print(f"An error occurred in close_all_positions: {e}")
            return make_response(jsonify({
                'message': str(e)
            }), 500)

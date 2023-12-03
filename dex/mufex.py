#!/usr/bin/env python3

import decimal
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


def round_size(size, ticker_size):
    sizeNumber = decimal.Decimal(size) / decimal.Decimal(ticker_size)
    return decimal.Decimal(int(sizeNumber)) * decimal.Decimal(ticker_size)


def convert_side(side, reverse=False):
    side = side.upper()
    side_map = {'BUY': 'Sell', 'SELL': 'Buy'}
    if side in side_map:
        return side_map[side] if reverse else side.capitalize()
    else:
        return 'Invalid Side'


class ApiResponse:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error

    def is_error(self):
        return self.error


class MufexDex(AbstractDex):
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

    def __send_get_request(self, endpoint, params=None, headers=None):
        request_url = f"{self.mufex_http}{endpoint}"
        try:
            response = requests.get(
                request_url, params=params, headers=headers, timeout=1)
            response.raise_for_status()
            return ApiResponse(data=response.json())
        except requests.exceptions.Timeout:
            return ApiResponse(error=f"Request timed out: url={request_url}")
        except Exception as e:
            self.__handle_request_error(e)
            return ApiResponse(error=str(e))

    def __send_post_request(self, endpoint, json_body, headers):
        request_url = f"{self.mufex_http}{endpoint}"
        try:
            response = requests.post(
                request_url, json=json_body, headers=headers, timeout=1)
            response.raise_for_status()
            return ApiResponse(data=response.json())
        except requests.exceptions.Timeout:
            return ApiResponse(error=f"Request timed out: url={request_url}")
        except Exception as e:
            self.__handle_request_error(e)
            return ApiResponse(error=str(e))

    def __handle_request_error(self, e):
        print(f"Unexpected error: {e}")
        response_content = e.response.text if e.response else 'No content'
        status_code = e.response.status_code if e.response else 'No status code'
        print(f"HTTP Response Content: {response_content}")
        print(f"HTTP Status Code: {status_code}")

    def __generate_signature(self, query_string='', json_body_string='', recv_window=5000):
        timestamp = int(time.time() * 1000)
        prehash = f"{timestamp}{self.api_key}{recv_window}{query_string}{json_body_string}"
        signature = hmac.new(self.api_secret.encode(),
                             prehash.encode(), hashlib.sha256).hexdigest()
        return signature, timestamp, recv_window

    def __create_order_internal(self, symbol: str, size: str, side: str, price: Optional[str], reverse=False):
        symbol_without_hyphen = symbol.replace("-", "")
        endpoint = "/public/v1/instruments"
        params = {'category': 'linear', 'symbol': symbol_without_hyphen}

        response = self.__send_get_request(endpoint, params)
        if response.is_error():
            return response

        data = response.data

        qty_step = data["data"]["list"][0]["lotSizeFilter"]["qtyStep"]
        rounded_size = round_size(size, qty_step)
        side = convert_side(side, reverse)

        json_body = {
            'symbol': symbol_without_hyphen, 'side': side, 'positionIdx': 0,
            'orderType': 'Market', 'qty': str(rounded_size), 'timeInForce': 'ImmediateOrCancel'
        }
        json_body_string = json.dumps(json_body)

        signature, timestamp, recv_window = self.__generate_signature(
            json_body_string=json_body_string)

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window),
            'Content-Type': 'application/json'
        }

        endpoint = "/private/v1/trade/create"
        response = self.__send_post_request(
            endpoint, json_body, headers)
        if response.is_error():
            return response

        data = response.data
        code = data.get('code', 9999)
        if code != 0:
            message = data.get('message', '') + f" ({code})"
            return ApiResponse(error=message)

        id = data['data']['orderId']
        endpoint = "/private/v1/trade/activity-orders"
        params = {'orderId': id, 'symbol': symbol_without_hyphen}
        signature, timestamp, recv_window = self.__generate_signature(
            urllib.parse.urlencode(params))

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window)
        }

        response = self.__send_get_request(
            endpoint, params=params, headers=headers)
        if response.is_error():
            return response

        data = response.data
        code = data.get('code', 9999)
        if code != 0:
            message = data.get('message', '') + f" ({code})"
            return ApiResponse(error=message)

        return response

    def __get_positions(self, symbol):
        endpoint = "/private/v1/account/positions"
        params = {}

        if symbol is not None:
            symbol_without_hyphen = symbol.replace("-", "")
            params['symbol'] = symbol_without_hyphen

        signature, timestamp, recv_window = self.__generate_signature(
            urllib.parse.urlencode(params))

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window)
        }

        response = self.__send_get_request(
            endpoint, params=params, headers=headers)
        if response.is_error():
            return response

        data = response.data

        code = data.get('code', 9999)
        if code != 0:
            message = data.get('message', '') + f"({code})"
            return ApiResponse(error=message)

        positions = data['data']["list"]
        extracted_positions = []

        for position in positions:
            extracted_position = {
                "symbol": position["symbol"],
                "size": position["size"],
                "side": position["side"]
            }
            extracted_positions.append(extracted_position)

        return ApiResponse(data=extracted_positions)

    def get_ticker(self, symbol: str):
        endpoint = "/public/v1/market/tickers"
        symbol_without_hyphen = symbol.replace("-", "")
        params = {'symbol': symbol_without_hyphen}

        response = self.__send_get_request(endpoint, params)
        if response.is_error():
            return make_response(jsonify({
                'message': response.error
            }), 500)

        data = response.data

        price = data["data"]["list"][0]["lastPrice"]

        return jsonify({
            'symbol': symbol,
            'price': price
        })

    def get_balance(self):
        endpoint = "/private/v1/account/balance"
        signature, timestamp, recv_window = self.__generate_signature()

        headers = {
            'MF-ACCESS-SIGN-TYPE': '2',
            'MF-ACCESS-SIGN': signature,
            'MF-ACCESS-API-KEY': self.api_key,
            'MF-ACCESS-TIMESTAMP': str(timestamp),
            'MF-ACCESS-RECV-WINDOW': str(recv_window),
            'Content-Type': 'application/json'
        }

        response = self.__send_get_request(endpoint, headers=headers)
        if response.is_error():
            return make_response(jsonify({'message': response.error}), 500)

        data = response.data

        code = data.get('code', 9999)
        if code != 0:
            message = data.get('message', '') + f" ({code})"
            return make_response(jsonify({'message': message}), 500)

        equity = data["data"]["list"][0]["equity"]
        balance = data["data"]["list"][0]["walletBalance"]

        return jsonify({
            'equity': equity,
            'balance': balance
        })

    def create_order(self, symbol: str, size: str, side: str, price: Optional[str]):
        response = self.__create_order_internal(symbol, size, side, price)
        if response.is_error():
            return make_response(jsonify({
                'message': response.error
            }), 500)
        else:
            data = response.data

            if data["data"]["list"][0]["orderStatus"] == 'Filled':
                size = data["data"]["list"][0]["cumExecQty"]
                val = data["data"]["list"][0]["cumExecValue"]
                fee = data["data"]["list"][0]["cumExecFee"]
                price_float = float(val) / float(size)
                price = str(price_float)

                return jsonify({
                    'price': price,
                    'size': size,
                    'fee': fee,
                })
            else:
                return jsonify({})

    def close_all_positions(self, close_symbol):
        response = self.__get_positions(close_symbol)
        if response.is_error():
            return make_response(jsonify({
                'message': response.error
            }), 500)

        positions = response.data

        for position in positions:
            size_float = float(position['size'])
            if size_float == 0.0:
                continue
            response = self.__create_order_internal(
                position['symbol'], position['size'], position['side'], None, True)
            if response.is_error():
                return make_response(jsonify({
                    'message': response.error
                }), 500)

        return jsonify({})

#!/usr/bin/env python3

import os
import threading

from flask import make_response, jsonify
from .abstract_dex import AbstractDex
from apexpro.http_private_stark_key_sign import HttpPrivateStark
from apexpro.constants import APEX_HTTP_TEST, NETWORKID_TEST, APEX_HTTP_MAIN, NETWORKID_MAIN
from apexpro.constants import APEX_WS_MAIN, APEX_WS_TEST
from apexpro.websocket_api import WebSocket
from apexpro.helpers.util import round_size
import time
from .kms_decrypt import get_decrypted_env
import requests
from typing import Optional
import threading

TICK_SIZE_MULTIPLIER = 10

SUPPORTED_TICKERS = ['BTCUSDC', 'ETHUSDC', 'SOLUSDC', 'AVAXUSDC',
                     'ARBUSDC', 'XRPUSDC', 'MATICUSDC', 'OPUSDC', 'SOLUSDC', 'BNBUSDC']

latest_price_info = {}
processed_orders = {}  # {'symbol': {'order_id': timestamp, ...}, ...}
websocket_lock = threading.Lock()


def on_ticker_changed(message):
    symbol = message.get('data', {}).get('symbol')
    last_price = message.get('data', {}).get('lastPrice')

    if symbol != None and last_price != None:
        global latest_price_info
        with websocket_lock:
            latest_price_info[symbol] = last_price


def on_account_changed(message):
    current_orders = message['contents']['orders']
    current_timestamp = time.time()

    threshold = 60  # secconds

    for order in current_orders:
        order_id = order['orderId']
        current_status = order['status']
        order_symbol = order['symbol']
        order_created_at = order['createdAt'] / 1000.0

        if current_timestamp - order_created_at < threshold:
            with websocket_lock:
                if order_symbol not in processed_orders:
                    processed_orders[order_symbol] = {}
                if order_id not in processed_orders[order_symbol]:
                    processed_orders[order_symbol][order_id] = current_timestamp


def cleanup_processed_orders(expiration_time):
    current_timestamp = time.time()
    with websocket_lock:
        for symbol in list(processed_orders.keys()):
            for order_id in list(processed_orders[symbol].keys()):
                if current_timestamp - processed_orders[symbol][order_id] > expiration_time:
                    del processed_orders[symbol][order_id]
            if not processed_orders[symbol]:
                del processed_orders[symbol]


def schedule_cleanup(expiration_time=300):
    cleanup_processed_orders(expiration_time)
    threading.Timer(expiration_time, schedule_cleanup).start()


def cleanup_processed_orders(expiration_time):
    current_timestamp = time.time()
    with websocket_lock:
        for symbol in list(processed_orders.keys()):
            for order_id in list(processed_orders[symbol].keys()):
                if current_timestamp - processed_orders[symbol][order_id] > expiration_time:
                    del processed_orders[symbol][order_id]
            if not processed_orders[symbol]:
                del processed_orders[symbol]


class ApexDex(AbstractDex):
    def __init__(self, env_mode="TESTNET"):
        suffix = "_MAIN" if env_mode == "MAINNET" else "_TEST"
        env_vars = {
            'APEX_API_KEY': get_decrypted_env(f'APEX_API_KEY{suffix}'),
            'APEX_API_SECRET': get_decrypted_env(f'APEX_API_SECRET{suffix}'),
            'APEX_API_PASSPHRASE': get_decrypted_env(f'APEX_API_PASSPHRASE{suffix}'),
            'HEX_APEX_STARK_PUBLIC_KEY': get_decrypted_env(f'HEX_APEX_STARK_PUBLIC_KEY{suffix}'),
            'HEX_APEX_STARK_PUBLIC_KEY_Y_COORDINATE': get_decrypted_env(f'HEX_APEX_STARK_PUBLIC_KEY_Y_COORDINATE{suffix}'),
            'HEX_APEX_STARK_PRIVATE_KEY': get_decrypted_env(f'HEX_APEX_STARK_PRIVATE_KEY{suffix}'),
        }

        missing_vars = [key for key, value in env_vars.items()
                        if value is None]
        if missing_vars:
            raise EnvironmentError(
                f"Required environment variables are not set: {', '.join(missing_vars)}")

        api_key = env_vars['APEX_API_KEY']
        api_secret = env_vars['APEX_API_SECRET']
        api_passphrase = env_vars['APEX_API_PASSPHRASE']
        stark_public_key = env_vars['HEX_APEX_STARK_PUBLIC_KEY']
        stark_public_key_y_coordinate = env_vars['HEX_APEX_STARK_PUBLIC_KEY_Y_COORDINATE']
        stark_private_key = env_vars['HEX_APEX_STARK_PRIVATE_KEY']

        api_key_credentials = {
            'key': api_key,
            'secret': api_secret,
            'passphrase': api_passphrase
        }

        if env_mode == "MAINNET":
            apex_http = APEX_HTTP_MAIN
            network_id = NETWORKID_MAIN
            endpoint = APEX_WS_MAIN
        else:
            apex_http = APEX_HTTP_TEST
            network_id = NETWORKID_TEST
            endpoint = APEX_WS_TEST

        self.client = HttpPrivateStark(
            apex_http,
            network_id=network_id,
            stark_public_key=stark_public_key,
            stark_private_key=stark_private_key,
            stark_public_key_y_coordinate=stark_public_key_y_coordinate,
            api_key_credentials=api_key_credentials,
        )
        self.configs = self.client.configs()
        self.client.get_user()
        self.client.get_account()
        self.apex_http = apex_http

        # Create WebSocket with authentication
        ws_client = WebSocket(
            endpoint=endpoint,
            api_key_credentials=api_key_credentials,
        )

        # subscriptions
        ws_client.account_info_stream(on_account_changed)
        for ticker in SUPPORTED_TICKERS:
            ws_client.ticker_stream(on_ticker_changed, ticker)

        # schedule a timer
        schedule_cleanup()

    def get_ticker(self, symbol: str):
        symbol_without_hyphen = symbol.replace("-", "")

        with websocket_lock:
            data = latest_price_info.copy()

        if symbol_without_hyphen in data:
            return jsonify({
                'symbol': symbol,
                'price': data[symbol_without_hyphen]
            })
        else:
            error_message = 'lastPrice information is unknown'
            return make_response(jsonify({
                'message': error_message
            }), 503)

    def get_filled_orders(self, symbol: str):
        with websocket_lock:
            orders = processed_orders.get(symbol, {})
        orders_list = list(orders.keys())
        return jsonify({"orders": orders_list})

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
                code = ret['code']
                message = ret.get('msg', '') + f" ({code})"
                return make_response(jsonify({
                    'message': message
                }), 500)

            id = ret['data']['orderId']
            ret = self.client.get_order(id=id)

            if 'code' in ret:
                code = ret['code']
                message = ret.get('msg', '') + f" ({code})"
                return make_response(jsonify({
                    'message': message
                }), 500)

            if ret['data']['status'] == 'FILLED':
                size = ret['data']['size']
                val = ret['data']['cumSuccessFillValue']
                fee = ret['data']['cumSuccessFillFee']
                price_float = float(val) / float(size)
                price = str(price_float)
                return jsonify({
                    'price': price,
                    'size': size,
                    'fee': fee,
                })
            else:
                return jsonify({
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
                if close_symbol is None or symbol == close_symbol:
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

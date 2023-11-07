#!/usr/bin/env python3

import os

from flask.json import jsonify
from .abstract_dex import AbstractDex
from apexpro.http_private_stark_key_sign import HttpPrivateStark
from apexpro.constants import APEX_HTTP_TEST, NETWORKID_TEST, APEX_HTTP_MAIN, NETWORKID_MAIN
from apexpro.helpers.util import round_size
import time
from .kms_decrypt import decrypt_data_with_kms

def get_decrypted_env(name):
    encrypted_key = os.environ.get("ENCRYPTED_DATA_KEY")
    encrypted_data = os.environ.get(f"ENCRYPTED_{name}")

    if encrypted_key and encrypted_data:
        is_hex = 'STARK_' in name
        return decrypt_data_with_kms(encrypted_key, encrypted_data, is_hex)
    else:
        return None

class ApexDex(AbstractDex):
    def __init__(self, env_mode="TESTNET"):
        suffix = "_MAIN" if env_mode == "MAINNET" else "_TEST"

        env_vars = {
            'API_KEY': get_decrypted_env(f'API_KEY{suffix}'),
            'API_SECRET': get_decrypted_env(f'API_SECRET{suffix}'),
            'API_PASSPHRASE': get_decrypted_env(f'API_PASSPHRASE{suffix}'),
            'STARK_PUBLIC_KEY': get_decrypted_env(f'STARK_PUBLIC_KEY{suffix}'),
            'STARK_PUBLIC_KEY_Y_COORDINATE': get_decrypted_env(f'STARK_PUBLIC_KEY_Y_COORDINATE{suffix}'),
            'STARK_PRIVATE_KEY': get_decrypted_env(f'STARK_PRIVATE_KEY{suffix}'),
        }

        missing_vars = [key for key, value in env_vars.items() if value is None]
        if missing_vars:
            raise EnvironmentError(f"Required environment variables are not set: {', '.join(missing_vars)}")

        self.api_key = env_vars['API_KEY']
        self.api_secret = env_vars['API_SECRET']
        self.api_passphrase = env_vars['API_PASSPHRASE']
        self.stark_public_key = env_vars['STARK_PUBLIC_KEY']
        self.stark_public_key_y_coordinate = env_vars['STARK_PUBLIC_KEY_Y_COORDINATE']
        self.stark_private_key = env_vars['STARK_PRIVATE_KEY']

        if env_mode == "MAINNET":
            apex_http = APEX_HTTP_MAIN
            network_id = NETWORKID_MAIN
        else:
            apex_http = APEX_HTTP_TEST
            network_id = NETWORKID_TEST

        self.client = HttpPrivateStark(
            apex_http,
            network_id=network_id,
            stark_public_key=self.stark_public_key,
            stark_private_key=self.stark_private_key,
            stark_public_key_y_coordinate=self.stark_public_key_y_coordinate,
            api_key_credentials={
                'key': self.api_key,
                'secret': self.api_secret,
                'passphrase': self.api_passphrase
            }
        )
        self.configs = self.client.configs()
        self.client.get_user()
        self.client.get_account()

    def get_ticker(self, symbol: str):
        try:
            ret = self.client.ticker(symbol=symbol)

            if 'data' in ret and ret['data']:
                data_first_item = ret['data'][0]

                if 'lastPrice' in data_first_item:
                    return jsonify({
                        'result': 'Ok',
                        'symbol': symbol,
                        'price': data_first_item['lastPrice']
                    })
                else:
                    error_message = 'lastPrice information is missing in the response'
                    print(error_message, ret)
                    return make_response(jsonify({
                        'result': 'Err',
                        'message': error_message
                    }), 400)

            else:
                error_message = 'Data is missing in the response'
                print(error_message, ret)
                return make_response(jsonify({
                    'result': 'Err',
                    'message': error_message
                }), 400)

        except Exception as e:
            print(f"Unexpected error: {e}")
            return make_response(jsonify({
                'result': 'Err',
                'message': str(e)
            }), 500)

    def get_yesterday_pnl(self):
        ret = self.client.yesterday_pnl()

        if 'data' in ret:
            return jsonify({
                'result': 'Ok',
                'data': ret['data']
            })
        else:
            return jsonify({
                'result': 'Err',
                'message': 'Data is missing in the response'
            })

    def create_order(self, symbol: str, size: str, side: str):
        try:
            worstPrice = self.client.get_worst_price(symbol=symbol, side=side, size=size)
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

            ret = self.client.create_order(symbol=symbol, side=side,
                                        type="MARKET", size=rounded_size, price=rounded_price, limitFeeRate=limitFeeRate,
                                        expirationEpochSeconds=currentTime)

            if 'code' in ret:
                return make_response(jsonify({
                    'result': 'Err',
                    'message': ret.get('msg', '')
                }), 400)

            return jsonify({
                'result': 'Ok',
                'price': ret['data']['price'],
                'size': ret['data']['size'],
            })

        except Exception as e:
            print(f"An error occurred in create_order: {e}")
            return make_response(jsonify({
                'result': 'Err',
                'message': str(e)
            }), 500)
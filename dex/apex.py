#!/usr/bin/env python3

import os

from flask.json import jsonify
from .abstract_dex import AbstractDex
from apexpro.http_private_stark_key_sign import HttpPrivateStark
from apexpro.constants import APEX_HTTP_TEST, NETWORKID_TEST
from apexpro.helpers.util import round_size
import time

class ApexDex(AbstractDex):

    def __init__(self):
        self.api_key = os.environ.get('API_KEY')
        self.api_secret = os.environ.get('API_SECRET')
        self.api_passphrase = os.environ.get('API_PASSPHRASE')
        self.stark_public_key = os.environ.get('STARK_PUBLIC_KEY')
        self.stark_public_key_y_coordinate = os.environ.get('STARK_PUBLIC_KEY_Y_COORDINATE')
        self.stark_private_key = os.environ.get('STARK_PRIVATE_KEY')

        if None in [self.api_key, self.api_secret, self.api_passphrase, self.stark_public_key,
                    self.stark_public_key_y_coordinate, self.stark_private_key]:
            raise EnvironmentError("Required environment variables are not set")

        self.client = HttpPrivateStark(
            APEX_HTTP_TEST,
            network_id=NETWORKID_TEST,
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
        ret = self.client.ticker(symbol=symbol)
        return jsonify({
            'symbol': symbol,
            'price': ret['data'][0]['lastPrice']
        })

    def get_yesterday_pnl(self):
        ret = get_yesterday_pnl_res = self.client.yesterday_pnl()
        return jsonify({
		    'data': ret['data']
	    })

    def create_order(self, symbol: str, size: str, side: str):
        worstPrice = self.client.get_worst_price(symbol=symbol, side=side, size=size)
        price = worstPrice['data']['worstPrice']
        currentTime = time.time()
        limitFeeRate = self.client.account['takerFeeRate']

        symbolData = {}
        for k, v in enumerate(self.configs.get('data').get('perpetualContract')):
            if v.get('symbol') == "BTC-USDC":
                symbolData = v

        rounded_size = round_size(size, symbolData.get('stepSize'))
        rounded_price = round_size(price, symbolData.get('tickSize'))

        ret = self.client.create_order(symbol=symbol, side=side,
                                            type="MARKET", size=rounded_size, price=rounded_price, limitFeeRate=limitFeeRate,
                                            expirationEpochSeconds= currentTime )
        print(ret)

        # Check if the response contains the 'code' key which indicates an error
        if 'code' in ret:
            return jsonify({
                'result': 'Err',
                'message': ret.get('msg', '')  # This will return the error message if present, or an empty string if not
            })

        return jsonify({
            'result': 'Ok',
            'price': ret['data']['price']
        })
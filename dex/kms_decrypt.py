#!/usr/bin/env python3

import boto3
import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


def unpad_pkcs7(data):
    """
    Remove the PKCS#7 padding from the provided data.
    """
    if not data:
        return data

    pad_len = data[-1]
    return data[:-pad_len]


def decrypt_data_with_kms(encrypted_data_key_str, encrypted_data_str, is_hex=False):
    # AWS Region
    region_name = os.environ.get("AWS_REGION", "eu-central-1")

    # Create KMS client
    client = boto3.client('kms', region_name=region_name)

    # Decode the provided encrypted data key
    if not encrypted_data_key_str:
        raise ValueError("Specify your encrypted data key")
    encrypted_data_key = base64.b64decode(
        encrypted_data_key_str.replace(" ", ""))

    # Decode the provided encrypted data
    if not encrypted_data_str:
        raise ValueError("Specify your encrypted data")
    encrypted_data = base64.b64decode(encrypted_data_str.replace(" ", ""))

    # Decrypt the data key using KMS
    response = client.decrypt(CiphertextBlob=encrypted_data_key)
    decrypted_data_key = response["Plaintext"]

    # Decrypt the actual data using the decrypted data key
    cipher = Cipher(algorithms.AES(decrypted_data_key), modes.CBC(
        encrypted_data[:16]), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(
        encrypted_data[16:]) + decryptor.finalize()

    # Remove the padding from the decrypted data
    unpadded_data = unpad_pkcs7(decrypted_data)

    # If the data is supposed to be in hex, convert it to a hex string
    if is_hex:
        return unpadded_data.hex()
    else:
        return unpadded_data.decode('utf-8')


if __name__ == '__main__':
    encrypted_key = os.environ.get("ENCRYPTED_DATA_KEY")

    encrypted_data_val = os.environ.get("ENCRYPTED_APEX_API_KEY")
    decrypted = decrypt_data_with_kms(
        encrypted_key, encrypted_data_val, is_hex=False)

    encrypted_data_val = os.environ.get("ENCRYPTED_HEX_STARK_PRIVATE_KEY")
    decrypted = decrypt_data_with_kms(
        encrypted_key, encrypted_data_val, is_hex=True)

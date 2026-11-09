"""Authenticated encryption for saved integration access; never browser storage."""
import base64
import hashlib
import json
from cryptography.fernet import Fernet, InvalidToken

PREFIX = 'integration_credentials.'


class CredentialError(Exception):
    pass


def cipher(secret, integration):
    if not secret:
        raise CredentialError('No hay una clave segura del servidor para guardar el acceso.')
    secret = secret.encode() if isinstance(secret, str) else secret
    key = hashlib.pbkdf2_hmac('sha256', secret, ('fenix-integration-v1:' + integration).encode(), 100000)
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret, integration, values):
    return cipher(secret, integration).encrypt(json.dumps(values, separators=(',', ':')).encode()).decode()


def unseal(secret, integration, value):
    try:
        result = json.loads(cipher(secret, integration).decrypt(value.encode()))
        if not isinstance(result, dict):
            raise ValueError('Not an object')
        return result
    except (InvalidToken, ValueError, TypeError, AttributeError):
        raise CredentialError('No se pudo abrir el acceso guardado. Vuelve a introducirlo; no se modificó el historial.') from None

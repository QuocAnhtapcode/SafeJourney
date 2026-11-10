import hashlib
import hmac
import secrets
from fastapi import HTTPException, Request
from .config import ORIGINS
from .db import connect

COOKIE = 'journey_session'

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()

def verify_password(password, encoded):
    salt, expected = encoded.split(':')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def session_user(token, conn=None):
    if not token:
        return None
    if conn is None:
        with connect() as connection:
            return session_user(token, connection)
    return conn.execute('SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires_at>now()',
                        (token_hash(token),)).fetchone()

def current_user(request: Request):
    user = session_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, 'Vui lòng đăng nhập')
    return user

def same_origin(request: Request):
    origin = request.headers.get('origin')
    if (origin and origin not in ORIGINS) or request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Origin không được phép')

def check_trip(trip, user, write=False):
    allowed = trip and (user['role'] == 'operator' or user['id'] in (trip['driver_id'], trip['passenger_id']))
    if not allowed:
        raise HTTPException(404, 'Không tìm thấy chuyến trong phạm vi được phép')
    if write and (user['role'] != 'driver' or user['id'] != trip['driver_id']):
        raise HTTPException(403, 'Chỉ tài xế được phân công được gửi GPS')

def operator_only(user):
    if user['role'] != 'operator':
        raise HTTPException(403, 'Chỉ nhân viên an toàn được thao tác')

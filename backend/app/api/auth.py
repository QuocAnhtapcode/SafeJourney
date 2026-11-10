import json
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from ..config import COOKIE_SECURE
from ..db import connect
from ..schemas import Login
from ..security import COOKIE, current_user, token_hash, verify_password

router = APIRouter()

@router.post('/api/login')
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else 'unknown'
    with connect() as conn:
        # Serialize count+insert for this username/IP only. Without a shared
        # database lock, concurrent API workers can all pass the same limit.
        key = json.dumps([body.username, ip], separators=(',', ':'))
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (key,))
        attempts = conn.execute("SELECT count(*) AS n FROM login_attempts WHERE username=%s AND ip=%s AND created_at>now()-interval '10 minutes'", (body.username, ip)).fetchone()['n']
        if attempts >= 10:
            raise HTTPException(429, 'Thử lại sau 10 phút')
        conn.execute('INSERT INTO login_attempts(username,ip) VALUES (%s,%s)', (body.username, ip))
        user = conn.execute('SELECT id,username,role,password_hash FROM users WHERE username=%s', (body.username,)).fetchone()
    if not user or not verify_password(body.password, user['password_hash']):
        raise HTTPException(401, 'Tài khoản hoặc mật khẩu chưa đúng')
    token = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at<now()")
        conn.execute("DELETE FROM login_attempts WHERE created_at<now()-interval '1 day'")
        conn.execute("INSERT INTO sessions VALUES (%s,%s,now()+interval '8 hours')", (token_hash(token), user['id']))
    response.set_cookie(COOKIE, token, httponly=True, secure=COOKIE_SECURE, samesite='lax', max_age=28800, path='/')
    return {k: user[k] for k in ('id', 'username', 'role')}


@router.get('/api/me')
def me(user=Depends(current_user)):
    return user


@router.post('/api/logout')
def logout(request: Request, response: Response):
    with connect() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=%s', (token_hash(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}


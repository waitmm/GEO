"""Controlled invitations for the single-API release; no business permissions from LLMs."""
from collections import defaultdict, deque
from hashlib import scrypt, sha256
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

COOKIE = 'geo_release_session'
TTL = 8 * 60 * 60
router = APIRouter(prefix='/api/access', tags=['release-access'])
SHARED_PASSWORD_MODE = 'SHARED_PASSWORD'
INVITATION_MODE = 'INVITATION'
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def _owner_only(file: Path) -> None:
    # Windows ACLs are configured by the deployment script. POSIX permission
    # bits on Windows do not express the effective ACL and must not be used as
    # a false security attestation.
    if os.name != 'nt' and file.stat().st_mode & 0o077:
        raise RuntimeError('Access configuration must be readable only by its owner (0600)')


def _hex(value: object, length: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(c not in '0123456789abcdef' for c in value):
        raise RuntimeError(label)
    return value


def _shared_account(data: dict) -> dict | None:
    return data.get('shared_password') if data.get('mode') == SHARED_PASSWORD_MODE else None


def configuration():
    path = os.environ.get('GEO_RELEASE_ACCESS_CONFIG')
    if not path:
        return None
    file = Path(path)
    _owner_only(file)
    data = json.loads(file.read_text())
    shared = _shared_account(data)
    if shared is not None:
        if not isinstance(shared, dict):
            raise RuntimeError('Shared password configuration is invalid')
        if not isinstance(shared.get('name'), str) or not shared['name']:
            raise RuntimeError('Shared password name must be nonempty')
        _hex(shared.get('salt_hex'), 32, 'Shared password salt must be 16-byte lowercase hex')
        _hex(shared.get('password_scrypt'), 64, 'Shared password verifier must be 32-byte lowercase hex')
        if not isinstance(shared.get('project_ids'), list) or not shared['project_ids'] or any(
                type(i) is not int or i < 1 for i in shared['project_ids']):
            raise RuntimeError('Shared password project IDs must be explicit positive integers')
        if shared.get('admin') is not False or shared.get('enabled', True) is not True:
            raise RuntimeError('Shared password trial must be enabled, scoped and non-admin')
        return data
    if data.get('mode') not in {None, INVITATION_MODE}:
        raise RuntimeError('Unsupported access configuration mode')
    if not isinstance(data.get('accounts'), list) or not data['accounts']:
        raise RuntimeError('Access configuration requires invitation accounts')
    names = set()
    for account in data['accounts']:
        if not isinstance(account.get('name'), str) or not account['name'] or account['name'] in names:
            raise RuntimeError('Invitation account names must be nonempty and unique')
        names.add(account['name'])
        digest = account.get('key_sha256', '')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise RuntimeError('Invitation keys must be stored as SHA-256 hashes')
        if not isinstance(account.get('project_ids', []), list) or any(type(i) is not int or i < 1 for i in account.get('project_ids', [])):
            raise RuntimeError('Invitation project IDs must be explicit positive integers')
        if type(account.get('admin', False)) is not bool:
            raise RuntimeError('Invitation admin must be boolean')
    return data


def _loopback(request):
    try:
        return ipaddress.ip_address(request.client.host).is_loopback and (request.url.hostname in {'localhost', '127.0.0.1', '::1'})
    except (ValueError, AttributeError):
        return False


def _trusted_private_http(request: Request, config: dict | None) -> bool:
    if not config or _shared_account(config) is None or os.environ.get('GEO_ALLOW_TRUSTED_LAN_HTTP') != '1':
        return False
    raw_network = os.environ.get('GEO_TRUSTED_LAN_CIDR', '')
    try:
        network = ipaddress.ip_network(raw_network, strict=False)
        client = ipaddress.ip_address(request.client.host)
        server = ipaddress.ip_address(request.url.hostname or '')
    except (ValueError, AttributeError):
        return False
    return bool(client in network and server in network and client.is_private and server.is_private)


def _account_for_session(config: dict, name: str) -> dict | None:
    shared = _shared_account(config)
    if shared is not None:
        return shared if shared['name'] == name and shared.get('enabled', True) else None
    return next((a for a in config['accounts'] if a['name'] == name and a.get('enabled', True)), None)


def _credential_fingerprint(config: dict, account: dict) -> str:
    verifier = account['password_scrypt'] if _shared_account(config) is not None else account['key_sha256']
    return sha256(f"{config.get('mode', INVITATION_MODE)}:{verifier}".encode()).hexdigest()


def _verify_credential(config: dict, account: dict, credential: str) -> bool:
    if _shared_account(config) is None:
        return hmac.compare_digest(sha256(credential.encode()).hexdigest(), account['key_sha256'])
    candidate = scrypt(
        credential.encode('utf-8'), salt=bytes.fromhex(account['salt_hex']),
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
    ).hex()
    return hmac.compare_digest(candidate, account['password_scrypt'])


def principal(request):
    config = configuration()
    if config is None:
        if _loopback(request):
            return {'name': 'local-owner', 'admin': True, 'project_ids': [], 'mode': 'LOCAL_ONLY'}
        return None
    token = request.cookies.get(COOKIE, '')
    stored = request.app.state.access_sessions.get(sha256(token.encode()).hexdigest())
    if not stored or stored['expires_at'] <= time.time():
        return None
    account = _account_for_session(config, stored['name'])
    if not account or not hmac.compare_digest(
            _credential_fingerprint(config, account), stored['credential_fingerprint']):
        return None
    return {**account, 'mode': config.get('mode', INVITATION_MODE)}


def authenticated_actor(request: Request) -> str:
    user = principal(request)
    if not user:
        raise HTTPException(401, '当前访问身份已失效，请重新登录')
    return user['name']


async def require_project_access(request: Request):
    user = principal(request)
    if not user:
        raise HTTPException(401, '请先使用管理员提供的访问凭证登录')
    request.state.principal = user
    if user.get('admin'):
        return
    if request.url.path in {'/api/projects', '/api/platforms'} and request.method == 'GET':
        return
    if request.url.path == '/api/projects':
        raise HTTPException(403, '只有管理员可以创建项目')
    identifiers = [request.path_params.get('project_id'), request.query_params.get('project_id')]
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and 'application/json' in request.headers.get('content-type', ''):
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(422, '请求不是完整 JSON') from None
        if isinstance(body, dict):
            identifiers.append(body.get('project_id'))
    ids = [str(i) for i in identifiers if i is not None]
    allowed = {str(i) for i in user.get('project_ids', [])}
    if not ids or any(i not in allowed for i in ids):
        raise HTTPException(403, '没有当前项目的访问权限')
    # The domain handlers also resolve each object against the supplied project.


def install_access(app, allowed_origins):
    configuration()  # Invalid deployment configuration fails closed.
    app.state.access_sessions = {}
    app.state.access_attempts = defaultdict(deque)

    @app.middleware('http')
    async def private_response(request, call_next):
        origin = request.headers.get('origin')
        allowed = set(allowed_origins) | {str(request.base_url).rstrip('/')}
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and origin and origin not in allowed:
            return JSONResponse({'detail': '请求来源未获授权'}, status_code=403)
        if configuration() is None and not _loopback(request):
            return JSONResponse({'detail': '未配置访问凭证，仅允许本机访问'}, status_code=403)
        if not _loopback(request) and request.url.scheme != 'https' and not _trusted_private_http(request, configuration()):
            return JSONResponse({'detail': '远程访问必须使用 HTTPS'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, nosnippet'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    app.include_router(router)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str | None = Field(default=None, min_length=12, max_length=512)
    access_key: str | None = Field(default=None, min_length=32, max_length=512)

    def credential(self) -> str:
        values = [value for value in (self.password, self.access_key) if value is not None]
        if len(values) != 1:
            raise HTTPException(422, '必须且只能提交一个登录密码')
        return values[0]


@router.get('/session')
def session(request: Request):
    user = principal(request)
    config = configuration()
    return {'authenticated': bool(user), 'mode': config.get('mode', INVITATION_MODE) if config else 'LOCAL_ONLY',
            'name': user['name'] if user else None, 'admin': bool(user and user.get('admin'))}


@router.post('/session')
def login(payload: LoginInput, request: Request, response: Response):
    config = configuration()
    if not config:
        raise HTTPException(409, '本机模式不需要邀请登录')
    now = time.time()
    attempts = request.app.state.access_attempts[request.client.host]
    while attempts and attempts[0] < now - 60:
        attempts.popleft()
    if len(attempts) >= 5:
        raise HTTPException(429, '尝试过于频繁，请一分钟后再试')
    attempts.append(now)
    credential = payload.credential()
    shared = _shared_account(config)
    candidates = [shared] if shared is not None else config['accounts']
    user = next((a for a in candidates if a.get('enabled', True) and _verify_credential(config, a, credential)), None)
    if not user:
        raise HTTPException(401, '登录密码无效')
    sessions = request.app.state.access_sessions
    for key, value in list(sessions.items()):
        if value['expires_at'] <= now:
            sessions.pop(key)
    if len(sessions) >= 1024:
        raise HTTPException(503, '会话已满，请管理员检查')
    token = secrets.token_urlsafe(32)
    sessions[sha256(token.encode()).hexdigest()] = {
        'name': user['name'],
        'credential_fingerprint': _credential_fingerprint(config, user),
        'expires_at': now + TTL,
    }
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, secure=request.url.scheme == 'https', samesite='strict', path='/api')
    return {'authenticated': True, 'name': user['name']}


@router.delete('/session')
def logout(request: Request, response: Response):
    request.app.state.access_sessions.pop(sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(), None)
    response.delete_cookie(COOKIE, path='/api')
    return {'authenticated': False}

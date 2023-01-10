

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Optional
import hashlib

from getrecords.models import KnownOpenplanetToken

from .http import get_session
from .utils import read_config_file

op_config = read_config_file('.openplanet-auth', ['secret', 'url'])

@dataclass
class TokenResp:
    account_id: str
    display_name: str
    token_time: int

async def check_token(token: str) -> Optional[TokenResp]:
    cached = await get_token_cached_and_recent(token)
    if cached is not None:
        return cached
    pl = dict(token=token, secret=op_config['secret'])
    async with get_session() as session:
        async with session.post(op_config['url'], data=pl) as resp:
            if (resp.status != 200):
                logging.warn(f"Checking token failed, status: {resp.status}, body: {await resp.text()}")
                return None
            resp_j = await resp.json()
            if "error" in resp_j:
                logging.warn(f"Error from server for token check, status: {resp_j['error']}")
                return None
            return await save_token_from_json(token, resp_j)

async def save_token_from_json(token, resp_j):
    tr = TokenResp(**resp_j)
    await KnownOpenplanetToken.objects.aupdate_or_create(account_id=tr.account_id,
        defaults=dict(
            display_name=tr.display_name,
            token_time=tr.token_time,
            expire_at=(tr.token_time + 3600),
            hashed=sha_256(token)
        )
    )
    return tr

async def get_token_cached_and_recent(token):
    hashed = sha_256(token)
    known_token = await KnownOpenplanetToken.objects.filter(hashed=hashed).afirst()
    if known_token is None or known_token.expire_at < time.time():
        return
    return TokenResp(account_id=known_token.account_id, display_name=known_token.display_name, token_time=known_token.token_time)


def sha_256(text: str) -> str:
    return hashlib.sha256(text.encode("UTF8")).hexdigest()

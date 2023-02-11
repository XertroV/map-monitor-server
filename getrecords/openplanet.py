

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Optional
import hashlib

from getrecords.models import KnownOpenplanetToken

from .http import get_session
from .utils import read_config_file, sha_256

op_config = read_config_file('.openplanet-auth', ['secret', 'url'])
op_archivist_config = read_config_file('.op-auth-archivist', ['secret', 'url'])

MAP_MONITOR_PLUGIN_ID = 308
ARCHIVIST_PLUGIN_ID = 328

plugin_site_id_to_op_config = {
    328: op_archivist_config,
    308: op_config,
}

@dataclass
class TokenResp:
    account_id: str
    display_name: str
    token_time: int

async def check_token(token: str, plugin_id: int) -> Optional[TokenResp]:
    _config = plugin_site_id_to_op_config.get(plugin_id, None)
    if _config is None:
        logging.error(f"@Dev: Bad plugin_id: {plugin_id}")
        return None
    cached = await get_token_cached_and_recent(token, plugin_id)
    if cached is not None:
        return cached
    pl = dict(token=token, secret=_config['secret'])
    async with get_session() as session:
        async with session.post(_config['url'], data=pl) as resp:
            if (resp.status != 200):
                logging.warn(f"Checking token failed, status: {resp.status}, body: {await resp.text()}")
                return None
            resp_j = await resp.json()
            if "error" in resp_j:
                logging.warn(f"Error from server for token check, status: {resp_j['error']}")
                return None
            return await save_token_from_json(token, plugin_id, resp_j)

async def save_token_from_json(token, plugin_id: int, resp_j):
    tr = TokenResp(**resp_j)
    logging.info(f"Saving new token for: {tr.display_name}")
    await KnownOpenplanetToken.objects.aupdate_or_create(account_id=tr.account_id, plugin_site_id=plugin_id,
        defaults=dict(
            display_name=tr.display_name,
            token_time=tr.token_time,
            expire_at=(tr.token_time + 3600),
            hashed=sha_256(token)
        )
    )
    return tr

async def get_token_cached_and_recent(token, plugin_id):
    hashed = sha_256(token)
    known_token = await KnownOpenplanetToken.objects.filter(hashed=hashed, plugin_site_id=plugin_id).afirst()
    if known_token is None or known_token.expire_at < time.time():
        return
    return TokenResp(account_id=known_token.account_id, display_name=known_token.display_name, token_time=known_token.token_time)

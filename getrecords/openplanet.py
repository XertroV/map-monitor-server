

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional

from .http import get_session
from .utils import read_config_file

op_secret = None
op_url = None

op_config = read_config_file('.openplanet-auth', ['secret', 'url'])

@dataclass
class TokenResp:
    account_id: str
    display_name: str
    token_time: int

async def check_token(token: str) -> Optional[TokenResp]:
    pl = dict(token=token, secret=op_secret)
    async with get_session() as session:
        async with session.post(op_url, data=pl) as resp:
            if (resp.status != 200):
                logging.warn(f"Checking token failed, status: {resp.status}, body: {await resp.text()}")
                return None
            resp_j = await resp.json()
            if "error" in resp_j:
                logging.warn(f"Error from server for token check, status: {resp_j['error']}")
                return None
            return TokenResp(**resp_j)

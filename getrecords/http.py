import aiohttp

from getrecords.utils import run_async

def get_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(headers={
        'User-Agent': f'app=MapMonitor / contact=@XertroV,mapmonitor@xk.io / supports openplanet plugin'
    })

def http_head_okay(url):
    return run_async(http_head_okay_async(url))

async def http_head_okay_async(url):
    try:
        async with get_session() as s:
            async with await s.head(url, timeout=3, allow_redirects=False) as resp:
                return resp.status == 200
    except Exception as e:
        return False

async def get_req_bytes(url):
    async with get_session() as s:
        async with await s.get(url) as resp:
            return await resp.read()

def get_req_sync(url):
    return run_async(get_req_bytes(url))

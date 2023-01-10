import aiohttp

def get_session():
    return aiohttp.ClientSession(headers={
        'User-Agent': f'app=MapMonitor / contact=@XertroV,mapmonitor@xk.io / supports openplanet plugin'
    })


import datetime
import logging

from getrecords.http import get_session
from getrecords.utils import run_async


"""Length Enums:
0: Anything
1: 15 seconds
2: 30
3: 45
4: 1min
5: 1:15
6: 1:30
7: 1:45
8: 2:00
9: 2:30
10: 3:00
11: 3:30
12: 4:00
13: 4:30
14: 5:00
15: Longer than 5 min
"""


def length_secs_to_enum(length_secs):
    if length_secs <= 120:
        return round(length_secs / 15)
    if length_secs <= 300:
        return 8 + round((length_secs - 120) / 30)
    return 15


def tmx_date_to_ts(date_str: str):
    # "2020-10-26T20:11:55.657"
    # "2022-02-26T00:29:13"
    frac = "000"
    if len(date_str) > 19 and date_str[19] == ".":
        frac = date_str[20:]
        date_str = date_str[:19]
    elif len(date_str) != 19:
        logging.warning(f"Unknown date format: {date_str} ??")
    return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").timestamp() + float(frac)/1000


def difficulty_to_int(d: str) -> int:
    # d = d.lower()
    if d == "Beginner": return 0
    if d == "Intermediate": return 1
    if d == "Advanced": return 2
    if d == "Expert": return 3
    if d == "Lunatic": return 4
    if d == "Impossible": return 5
    raise Exception(f"Unknown difficulty: {d}")

def int_to_difficulty(d: int) -> str:
    if d == 0: return "Beginner"
    if d == 1: return "Intermediate"
    if d == 2: return "Advanced"
    if d == 3: return "Expert"
    if d == 4: return "Lunatic"
    if d == 5: return "Impossible"
    raise Exception(f"Unknown difficulty int: {d}")


tmx_tags_cached = [{"ID":1,"Name":"Race","Color":""},{"ID":2,"Name":"FullSpeed","Color":""},{"ID":3,"Name":"Tech","Color":""},{"ID":4,"Name":"RPG","Color":""},{"ID":5,"Name":"LOL","Color":""},{"ID":6,"Name":"Press Forward","Color":""},{"ID":7,"Name":"SpeedTech","Color":""},{"ID":8,"Name":"MultiLap","Color":""},{"ID":9,"Name":"Offroad","Color":"705100"},{"ID":10,"Name":"Trial","Color":""},{"ID":11,"Name":"ZrT","Color":"1a6300"},{"ID":12,"Name":"SpeedFun","Color":""},{"ID":13,"Name":"Competitive","Color":""},{"ID":14,"Name":"Ice","Color":"05767d"},{"ID":15,"Name":"Dirt","Color":"5e2d09"},{"ID":16,"Name":"Stunt","Color":""},{"ID":17,"Name":"Reactor","Color":"d04500"},{"ID":18,"Name":"Platform","Color":""},{"ID":19,"Name":"Slow Motion","Color":"004388"},{"ID":20,"Name":"Bumper","Color":"aa0000"},{"ID":21,"Name":"Fragile","Color":"993366"},{"ID":22,"Name":"Scenery","Color":""},{"ID":23,"Name":"Kacky","Color":""},{"ID":24,"Name":"Endurance","Color":""},{"ID":25,"Name":"Mini","Color":""},{"ID":26,"Name":"Remake","Color":""},{"ID":27,"Name":"Mixed","Color":""},{"ID":28,"Name":"Nascar","Color":""},{"ID":29,"Name":"SpeedDrift","Color":""},{"ID":30,"Name":"Minigame","Color":"7e0e69"},{"ID":31,"Name":"Obstacle","Color":""},{"ID":32,"Name":"Transitional","Color":""},{"ID":33,"Name":"Grass","Color":"06a805"},{"ID":34,"Name":"Backwards","Color":"83aa00"},{"ID":35,"Name":"Freewheel","Color":"f2384e"},{"ID":36,"Name":"Signature","Color":"f1c438"},{"ID":37,"Name":"Royal","Color":"ff0010"},{"ID":38,"Name":"Water","Color":"69dbff"},{"ID":39,"Name":"Plastic","Color":"fffc00"},{"ID":40,"Name":"Arena","Color":""},{"ID":41,"Name":"Freestyle","Color":""},{"ID":42,"Name":"Educational","Color":""},{"ID":43,"Name":"Sausage","Color":""},{"ID":44,"Name":"Bobsleigh","Color":""},{"ID":45,"Name":"Pathfinding","Color":""},{"ID":46,"Name":"FlagRush","Color":"7a0000"},{"ID":47,"Name":"Puzzle","Color":"459873"},{"ID":48,"Name":"Freeblocking","Color":"ffffff"},{"ID":49,"Name":"Altered Nadeo","Color":"3a3a3a"}]

async def update_tmx_tags_cached():
    global tmx_tags_cached
    try:
        async with get_session() as session:
            async with await session.get("https://trackxmania.exchange/api/tags/gettags") as resp:
                if resp.ok:
                    data = await resp.json()
                    if data[0]["ID"] == 1:
                        tmx_tags_cached = data
                        print(f"Updated tags cache")
    except Exception as e:
        logging.warn(f"Failed to cache TMX tags: {e}")

# run_async_in_bg(update_tmx_tags_cached())

def get_tmx_tags_cached():
    global tmx_tags_cached
    return tmx_tags_cached

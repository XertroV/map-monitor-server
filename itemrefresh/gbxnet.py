
import json
import logging
import math
import os
from pathlib import Path
import random
import subprocess
import time
import zipfile

import requests

BASE_MAP_URL = "https://github.com/XertroV/map-monitor-server/raw/895f8a191f526513aae9d0cb1e9fd25fad592948/base_map/item_refresh_base.Map.Gbx"
BASE_MAP_PATH = "C:/item_refresh_base.Map.Gbx"
BASE_MAP_HASH = "fbd192a872519f1bae92e55761ab7590d15588e29f695f8c18a83df79fed8d3c"
GBX_NET_URL = "https://github.com/skyslide22/blendermania-assets/releases/download/Blendermania_Dotnet_v0.0.5/Blendermania_Dotnet_v0.0.5.zip"
GBX_NET_ZIP = "C:/Blendermania_Dotnet_v0.0.5.zip"
GBX_NET_ZIP_HASH = "c6b91c9df7beeab773863a238ae1bbc4c3e22a78a7b28e1714433b0c44644d9b"
GBX_NET_EXE_NAME = "Blendermania_Dotnet_v0.0.5.exe"
GBX_NET_EXE = "C:/Blendermania_Dotnet_v0.0.5.exe"
GBX_NET_EXE_HASH = "532d5004fce948d6b46303f6e160eebdc11494df84a4ddd8c2c296c1e05d65b6"

def generate_map_bytes(item_paths: list[str]):
    ensure_map_base_downloaded()
    ensure_gbx_net_exe_downloaded()
    return run_map_generation(item_paths)

def ensure_map_base_downloaded():
    bm = Path(BASE_MAP_PATH)
    if not bm.exists():
        save_url_to_file(BASE_MAP_URL, bm)
    if not bm.is_file():
        logging.warn(f"base map doesn't exist")


def ensure_gbx_net_exe_downloaded():
    zip_file = Path(GBX_NET_ZIP)
    save_url_to_file(GBX_NET_URL, zip_file)
    zf = zipfile.ZipFile(GBX_NET_ZIP, 'r')
    zf.extract(GBX_NET_EXE_NAME, '/tmp/')
    exe_file = Path(GBX_NET_EXE)
    if not exe_file.is_file():
        raise Exception(f'extracted gbx exe but it doesn\'t exist!')


def save_url_to_file(url, f: Path):
    retries = 0
    while retries < 10:
        resp = requests.get(url)
        if not resp.ok:
            logging.warn(f"request failed: {url} || {resp.status_code} / {resp.reason} / {resp}")
            time.sleep(1000)
            retries += 1
            continue
        else:
            logging.info(f'saved file: {f.absolute}')
            f.write_bytes(resp.content)
            break
    if (retries >= 10):
        raise Exception(f'failed to download file: {url}')



def run_map_generation(item_paths) -> bytes:
    items = [
        DotnetItem(ip, ip, DotnetVector3(), DotnetVector3(), DotnetVector3())
        for ip in item_paths
    ]
    return run_place_objects_on_map([], items, clean_items=False)



# borrowed from https://github.com/skyslide22/blendermania-addon/blob/fd142b639ac66221dad2fb67656a13aec7cc72fa/utils/Dotnet.py



DOTNET_BLOCKS_DIRECTION = (
    DOTNET_BLOCKS_DIRECTION_NORTH   := 0,
    DOTNET_BLOCKS_DIRECTION_EAST    := 1,
    DOTNET_BLOCKS_DIRECTION_SOUTH   := 2,
    DOTNET_BLOCKS_DIRECTION_WEST    := 3,
)


def get_block_dir_for_angle(angle: int) -> int:
    print(math.copysign(angle%360, angle))
    return DOTNET_BLOCKS_DIRECTION_EAST

class DotnetExecResult:
    success: bool
    message: str
    def __init__(self, message: str, success: bool):
        self.success = success
        self.message = message


# Dotnet types
class DotnetVector3:
    def __init__(self, X: float = 0, Y: float = 0, Z: float = 0) -> None:
        self.X = X
        self.Y = Y
        self.Z = Z

    def jsonable(self):
        return self.__dict__


class DotnetInt3:
    def __init__(self, X: int = 0, Y: int = 0, Z: int = 0) -> None:
        self.X = X
        self.Y = Y
        self.Z = Z

    def jsonable(self):
        return self.__dict__


class DotnetBlock:
    def __init__(self, Name: str, Direction: int, Position: DotnetInt3):
        if Direction > 3:
            Direction = 0

        self.Name = Name
        self.Dir = Direction
        self.Position = Position

    def jsonable(self):
        return self.__dict__


class DotnetItem:
    def __init__(self, Name: str, Path: str, Position: DotnetVector3, Rotation: DotnetVector3 = DotnetVector3(), Pivot: DotnetVector3 = DotnetVector3()):
        self.Name = Name
        self.Path = Path
        self.Position = Position
        self.Rotation = Rotation
        self.Pivot = Pivot

    def jsonable(self):
        return self.__dict__


class DotnetMediatrackerClip:
    def __init__(
        self,
        Name: str,
        Positions: list[DotnetVector3]):
            self.Name = Name
            self.Positions = Positions

    def jsonable(self):
        return self.__dict__


class DotnetPlaceObjectsOnMap:
    def __init__(
        self,
        MapPath: str,
        Blocks: list[DotnetBlock],
        Items: list[DotnetItem],
        ShouldOverwrite: bool = False,
        MapSuffix: str = "_modified",
        CleanBlocks: bool = True,
        CleanItems: bool = True,
        Env: str = "Stadium2020"):
            self.MapPath = MapPath
            self.Blocks = Blocks
            self.Items = Items
            self.ShouldOverwrite = ShouldOverwrite
            self.MapSuffix = MapSuffix
            self.CleanBlocks = CleanBlocks
            self.CleanItems = CleanItems
            self.Env = Env

    def jsonable(self):
        return self.__dict__


class DotnetPlaceMediatrackerClipsOnMap:
    def __init__(
        self,
        MapPath: str,
        Clips: list[DotnetItem]):
            self.MapPath = MapPath
            self.Clips = Clips

    def jsonable(self):
        return self.__dict__


class DotnetConvertItemToObj:
    def __init__(
        self,
        ItemPath: str,
        OutputDir: str,
    ):
        self.ItemPath = ItemPath
        self.OutputDir = OutputDir

    def jsonable(self):
        return self.__dict__

class ComplexEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj,'jsonable'):
            return obj.jsonable()
        else:
            return json.JSONEncoder.default(self, obj)



# Dotnet commands
def run_place_objects_on_map(
    blocks: list[DotnetBlock] = [],
    items: list[DotnetItem] = [],
    # should_overwrite: bool = False,
    map_suffix: str = "_p",
    clean_blocks: bool = True,
    clean_items: bool = True,
    env: str = "Stadium2020",
) -> bytes:
    base_name = f"map-export-{time.time()}-{random.randint(0, 100000)}"
    config_path = f'{base_name}.json'
    _out_map_path = f'{base_name}.Map.Gbx'
    _populated_out_map_path = f"{base_name}_p.Map.Gbx"
    out_map_path = Path(_out_map_path)
    out_map_path.write_bytes(Path(BASE_MAP_PATH).read_bytes())
    overwrite = False

    cfg = DotnetPlaceObjectsOnMap(
            _out_map_path,
            blocks,
            items,
            overwrite,
            map_suffix,
            clean_blocks,
            clean_items,
            env,
        )
    cfg_str = json.dumps(cfg, cls=ComplexEncoder, ensure_ascii=False, indent=4)
    logging.info(f"run_place_objects_on_map {cfg_str}")

    with open(config_path, 'w+', encoding='utf-8') as outfile:
        json.dump(cfg, outfile, cls=ComplexEncoder, ensure_ascii=False, indent=4)
        outfile.close()

    res = _run_dotnet('place-objects-on-map', config_path)
    logging.info(f"Got back from run dotnet: {res.__dict__}")

    if not res.success:
        raise Exception(f"dotnet exe failed: {res.message}")
    print([config_path, _out_map_path, _populated_out_map_path])
    ret_bytes = Path(_out_map_path if overwrite else _populated_out_map_path).read_bytes()

    os.remove(config_path)
    os.remove(_out_map_path)
    os.remove(_populated_out_map_path)
    return ret_bytes




def _run_dotnet(command: str, payload: str) -> DotnetExecResult:
    #print(payload)
    dotnet_exe = GBX_NET_EXE

    process = subprocess.Popen(args=[
        dotnet_exe,
        command,
        payload.strip('"'),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = process.communicate()
    if len(err) != 0:
        return DotnetExecResult(message=err.decode("utf-8") , success=False)

    res = out.decode("utf-8").strip()
    if process.returncode != 0:
        return DotnetExecResult(message="Unknown Error", success=False) if len(res) == 0 else res

    return DotnetExecResult(message=res, success=True)


import binascii
import json
import logging
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass

import requests

import sys

from mapmonitor.settings import DEBUG

IS_WINDOWS = sys.platform.startswith('win32')

BASE_MAP_URL = "https://github.com/XertroV/map-monitor-server/raw/895f8a191f526513aae9d0cb1e9fd25fad592948/base_map/item_refresh_base.Map.Gbx"
BASE_MAP_PATH = "C:/item_refresh_base.Map.Gbx"
BASE_MAP_HASH = "fbd192a872519f1bae92e55761ab7590d15588e29f695f8c18a83df79fed8d3c"
GBX_NET_URL = "https://github.com/skyslide22/blendermania-assets/releases/download/Blendermania_Dotnet_v0.0.5/Blendermania_Dotnet_v0.0.5.zip"
GBX_NET_ZIP = "C:/Blendermania_Dotnet_v0.0.5.zip"
GBX_NET_ZIP_HASH = "c6b91c9df7beeab773863a238ae1bbc4c3e22a78a7b28e1714433b0c44644d9b"
GBX_NET_EXE_URL = "https://github.com/XertroV/tm-embed-items/releases/download/0.1.0/tm-embed-items"
GBX_NET_EXE_NAME = "tm-embed-items"
GBX_NET_EXE = os.getcwd() + "/tm-embed-items"
# print(GBX_NET_EXE)
# GBX_NET_EXE_HASH = "532d5004fce948d6b46303f6e160eebdc11494df84a4ddd8c2c296c1e05d65b6"

LOCAL_DEV_MODE = DEBUG

if LOCAL_DEV_MODE:
    # GBX_NET_EXE = "/home/xertrov/src/tm-embed-items/bin/Debug/net6.0/linux-x64/publish/tm-embed-items"
    GBX_NET_EXE_NAME = "tm-embed-items"


@dataclass
class EmbedRequest:
    item_filenames: list[str]
    items: list[bytes]
    map_bytes: bytes

    def zipped_items(self):
        return zip(self.item_filenames, self.items)

def generate_map_bytes(item_paths: EmbedRequest):
    # ensure_map_base_downloaded()
    # if not LOCAL_DEV_MODE:
    ensure_gbx_net_exe_downloaded()
    return run_map_generation(item_paths)

def ensure_map_base_downloaded():
    bm = Path(BASE_MAP_PATH)
    if not bm.exists():
        save_url_to_file(BASE_MAP_URL, bm)
    if not bm.is_file():
        logging.warn(f"base map doesn't exist")


def ensure_gbx_net_exe_downloaded():
    # zip_file = Path(GBX_NET_ZIP)
    # save_url_to_file(GBX_NET_URL, zip_file)
    # zf = zipfile.ZipFile(GBX_NET_ZIP, 'r')
    # zf.extract(GBX_NET_EXE_NAME, os.getcwd())
    exe_file = Path(GBX_NET_EXE)
    if not exe_file.is_file():
        save_url_to_file(GBX_NET_EXE_URL, exe_file)
        exe_file.chmod(0o744)
    if not exe_file.is_file():
        raise Exception(f'downloaded gbx exe but it doesn\'t exist!')


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



def run_map_generation(item_paths: EmbedRequest) -> bytes:
    tmpdir = Path(f'/tmp/mapgen/{random.randint(0, 10**10)}')
    if not tmpdir.exists():
        tmpdir.mkdir(parents=True, exist_ok=True)
    _curdir = os.curdir
    os.chdir(tmpdir)

    items = []
    for ip, item_bytes in item_paths.zipped_items():
        raw_ip = ip.replace('\\', '/')
        itemNameOnly = Path(raw_ip).name
        pos = DotnetVector3(
            # random.random() * 48. * 32.,
            # 100,
            # random.random() * 48. * 32.
            31,100,31
        )
        item = DotnetItem(f'{raw_ip}', f'Items/{raw_ip}', pos, DotnetVector3(), DotnetVector3())
        item_path = Path(f'Items/{raw_ip}')
        if not ip.lower().endswith('.gbx'):
            raise Exception('bad file name')
        if ('../' in ip or '../' in ip):
            raise Exception('bad path')
        item_folder = item_path.parent
        if not item_folder.exists():
            item_folder.mkdir(parents=True, exist_ok=True)
        # (Path('Items') / item_path).write_bytes(item_bytes)
        (item_path).write_bytes(item_bytes)
        items.append(item)

    resp = run_place_objects_on_map(item_paths.map_bytes, [], items, clean_items=True)

    print(f"list dir: {list(tmpdir.glob('**/*'))}")

    os.chdir(_curdir)
    shutil.rmtree(tmpdir, ignore_errors=True)

    return resp



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
    base_map_bytes: bytes,
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
    _out_map_path = f'Maps/{base_name}.Map.Gbx'
    _populated_out_map_path = f"Maps/{base_name}_p.Map.Gbx"
    Path('Maps').mkdir()
    out_map_path = Path(_out_map_path)
    out_map_path.write_bytes(base_map_bytes)
    overwrite = True

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

    res = _run_dotnet(config_path)
    logging.info(f"Got back from run dotnet: {res.__dict__}")

    if not res.success:
        raise Exception(f"dotnet exe failed: {res.message}")
    print([config_path, _out_map_path, _populated_out_map_path])
    ret_bytes = Path(_out_map_path if overwrite else _populated_out_map_path).read_bytes()

    os.remove(config_path)
    os.remove(_out_map_path)
    if not overwrite:
        os.remove(_populated_out_map_path)
    return ret_bytes




def _run_dotnet(payload: str) -> DotnetExecResult:
    #print(payload)
    dotnet_exe = GBX_NET_EXE

    logging.info(f'running dotnet: {dict(cwd=os.getcwd(), exe=dotnet_exe, path=payload)}')
    process = subprocess.Popen(args=[
        dotnet_exe,
        # command,
        payload.strip('"'),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = process.communicate()
    if len(err) != 0:
        return DotnetExecResult(message=err.decode("utf-8") , success=False)

    res = out.decode("utf-8").strip()
    if process.returncode != 0:
        return DotnetExecResult(message="Unknown Error", success=False) if len(res) == 0 else res

    return DotnetExecResult(message=res, success=True)




minimal_item_hex = "424706584200435500520020852e00000400000003000010512e000006000010082e000000000020042e000001000020042e000003000000ff00ffff1aff000000000000164000004300306977627145517153333279317a475771397978085100000500000049006574736dffffffff000800000001000b0000694d696e616d496c6574036d000000000000000000010000000000000006000000000000062000000355000009340010052e000049006574736d0000000000030000ffffffff100b2e00ffffffff001a00803f00164000004300306977627145517153333279317a4757713979780c5100100b2e00004d006e696d696c6174496d65100d2e00000e00006f4e442073657263706969746e6f10102e0000040000ffffffffdc00020010112e008401a40c06000001000012030010f02ee401020020082e00cc0736130004090200200a2e06c2200c17be201209ac04300500bf80999a3e19201510a0190200200f2e7c2dec01800603140260002e0260108c010e00000200000000000030030900300209ac290e0200030000d000090fd000090f000b0000f0010015001b00001000230000005300617469646d754d5c646561694d5c7461726561695c6c6c5074616f666d72655468630fe4042a0600ffffffffd001090fcc052801006e3f8001ec02010fd0ec090a01de01faca300409004950534b290c02840104000005000030049c1b8419f400a40600064000004c00796172650830000047006f65656d7274017908c425020000040044dd860480068f420021430009b64340ec2a9c060c1f000b0000654461666c7543746275e065bc400105000008000096c00000b8009c01edcd40000000dda840ee0180042d40002c05dc029c2e2ac000c10c060718c004ac049d2800001c02ff0000961802183203000c16000001020300010100060504070000040103070000010004050100000006010105000201000607030209bc1cf828e9c8068746000c550c00a405ac79018555a4aa0000790d795579550055ff000cffff550cfff25500aaf20000aa85000caa85550caa038c7901f255b6aaff03b6ff7903b4550303aa85000055790ccc060002010403060508070a090c0b0e0d100f121114131615071740d014ba3f8000af4000c10602421c310100de01faca77ec16a451b03ae8043c28000aa000a43c3cfc002e26000603e80eac01050260502e4b49d45384470100de01faca11b7ffffca1a1c80ac20b89c01552e02000006bd84323406019c642ee702800001bf07d4d52a04014d31050002cc340a000005000000000018700a09e82d300e0384dc280201de01facad01ef49efc2c0200201f2e00d00cec70940206b6ffffffff20202e00bc030202000020252f00048d3126004d3027004c0002de01faca00110000"
minimal_item = binascii.unhexlify(minimal_item_hex)

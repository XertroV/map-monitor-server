import asyncio
import base64
from dataclasses import dataclass
import io
import json
import logging
from pathlib import Path
import struct
import time
from typing import Coroutine
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse, HttpResponseBadRequest, FileResponse
from django.shortcuts import render
import requests
import zipfile

from itemrefresh.gbxnet import EmbedRequest, generate_map_bytes

# Create your views here.

def create_map(request: HttpRequest):
    if request.method != "POST": return HttpResponseNotAllowed(['POST'], "POST only")
    print(f'body len: {len(request.body)}')
    req_parts = read_request_parts(base64.b64decode(request.body))
    print('got req parts!')
    map_bytes = generate_map_bytes(req_parts)
    # filename=f'map-with-items-{time.time()}.Map.Gbx',
    return HttpResponse(map_bytes, content_type='application/octet-stream')




def read_request_parts(_body: bytes):
    print(f'body len: {len(_body)}')
    body = io.BytesIO(_body)
    # print(f"_body len: {len(_body)}")
    # print(f"body len: {len(body)}")
    full_len = r_read_length(body, len(_body))
    # print(f"body 2 len: {len(body)}")
    item_filenames = r_read_json_array(body)
    items = r_read_item_list(body)
    map_bytes = r_read_map(body)
    return EmbedRequest(item_filenames, items, map_bytes)

def r_read_length(b: io.BytesIO, expected_len: int):
    l = r_read_uint(b)
    if expected_len != l:
        raise Exception('bad length')
    return l

def r_read_uint(b: io.BytesIO):
    _b = b.read(4)
    print(f'bytes ({len(_b)}): {_b}')
    return struct.unpack_from('<I', _b)[0]

def r_read_json_array(b: io.BytesIO) -> list[any]:
    list_part = r_read_bytes(b)
    return json.loads(list_part)

def r_read_item_list(b: io.BytesIO) -> list[bytes]:
    return r_read_list(b)

def r_read_map(b: io.BytesIO) -> bytes:
    return r_read_bytes(b)

def r_read_list(b: io.BytesIO) -> list[bytes]:
    size = r_read_uint(b)
    ret = list()
    for i in range(size):
        ret.append(r_read_bytes(b))
    return ret

def r_read_bytes(b: io.BytesIO) -> bytes:
    size = r_read_uint(b)
    return b.read(size)



def run_async(coro: Coroutine):
    loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()

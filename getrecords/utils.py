
from pathlib import Path
import time
from typing import Iterable
from contextlib import contextmanager
import logging as log
import os


@contextmanager
def timeit_context(name):
    start_time = time.time()
    yield
    elapsed_time = time.time() - start_time
    log.info('[{}] finished in {} ms'.format(name, int(elapsed_time * 1_000)))


def clamp(n, _min, _max):
    return max(_min, min(_max, n))


def chunk(iter: Iterable, n: int):
    for i in range(0, len(iter), n):
        yield iter[i:(i+n)]


def read_config_file(file: str, keys: list[str]):
    no_dot = file[1:] if file.startswith('.') else file
    if check_environ_for_config(no_dot, keys):
        return read_config_environ(no_dot, keys)
    vals = [None] * len(keys)
    lines = Path(file).read_text().strip().split('\n')
    for line in lines:
        key, val = line.strip().split("=", 2)
        key = key.strip()
        val = val.strip()
        try:
            vals[keys.index(key)] = val
        except ValueError as e:
            pass
    ret = dict()
    for k,v in zip(keys, vals):
        if v is None:
            raise Exception(f'missing config entry in {file} for key: {k}')
        ret[k] = v
    return ret

def check_environ_for_config(file: str, keys: list[str]):
    return all(f"{file}_{key}" in os.environ for key in keys)

def read_config_environ(file: str, keys: list[str]):
    ret = dict()
    for key in keys:
        ret[key] = os.environ.get(f"{file}_{key}")
    return ret

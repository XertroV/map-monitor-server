from pathlib import Path
import boto3
import botocore

from getrecords.utils import read_config_file

s3_config = read_config_file('.s3', ['access-key', 'secret-key', 'service-url', 'bucket-name'])
s3_bucket_name = s3_config['bucket-name']

client_config = botocore.config.Config(
    max_pool_connections=100
)

s3 = boto3.resource('s3',
    endpoint_url=f'https://{s3_config["service-url"]}/',
    aws_access_key_id=s3_config['access-key'],
    aws_secret_access_key=s3_config['secret-key'],
    config=client_config
)

s3_client = boto3.client('s3',
    endpoint_url=f'https://{s3_config["service-url"]}/',
    aws_access_key_id=s3_config['access-key'],
    aws_secret_access_key=s3_config['secret-key'],
    config=client_config
)

def upload_ghost_to_s3(ghost_hash: str, ghost_body: bytes) -> str:
    key = f'ghost/{ghost_hash}.Ghost.gbx'
    s3.Object(s3_bucket_name, key).put(
        ACL='public-read', Body=ghost_body
    )
    return f"https://{s3_bucket_name}.{s3_config['service-url']}/" + key

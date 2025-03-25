import configparser
import logging
import os

from obs import ObsClient
from obs import PutObjectHeader
import traceback

config = configparser.ConfigParser()
config.read("/app/config.ini")

AccessKeyID = config.get("obs", "AccessKeyID", fallback="").replace('"', "").strip()
SecretAccessKey = (
    config.get("obs", "SecretAccessKey", fallback="").replace('"', "").strip()
)


def upload(server: str, bucketName: str, objectKey: str, file_path: str):

    ak = AccessKeyID
    sk = SecretAccessKey

    server = f"https://{server}"

    obsClient = ObsClient(access_key_id=ak, secret_access_key=sk, server=server)

    try:
        headers = PutObjectHeader()
        bucketName = bucketName
        objectKey = objectKey
        file_path = file_path

        resp = obsClient.putFile(bucketName, objectKey, file_path, headers)
        if resp.status < 300:
            logging.info(f"{objectKey} successfully uploaded to {bucketName}")
        else:
            logging.error(f"{objectKey} failed to upload to {bucketName}")
    except Exception as e:
        logging.error(f"{objectKey} failed to upload to {bucketName},{e}")

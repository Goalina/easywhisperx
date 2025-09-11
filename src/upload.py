import configparser
import logging
import asyncio
from functools import partial
import os
import traceback

from obs import ObsClient,PutObjectHeader

config = configparser.ConfigParser()
config.read("/app/easywhisperx/config/config.ini")


async def upload(server: str, bucketName: str, objectKey: str, file_path: str, community: int) -> bool:
    """异步上传，返回是否成功"""
    if community == 1:
        ak = config.get("obs", "AccessKeyID", fallback="").replace('"', "").strip()
        sk = (
            config.get("obs", "SecretAccessKey", fallback="").replace('"', "").strip()
        )
    elif community == 2:
        ak = config.get("openubmc", "AccessKeyID", fallback="").replace('"', "").strip()
        sk = (
            config.get("openubmc", "SecretAccessKey", fallback="").replace('"', "").strip()
        )
    else:
        raise ValueError(f"Invalid community value: {community}")

    server = f"https://{server}"

    if not all([ak, sk]):
        logging.error("Missing OBS credentials in configuration")
        return False

    loop = asyncio.get_event_loop()
    obsClient = None
    try:
        # 创建客户端
        obsClient = await loop.run_in_executor(
            None,
            partial(ObsClient,
                    access_key_id=ak,
                    secret_access_key=sk,
                    server=server)
        )

        # 检查文件是否存在
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return False

        # 执行上传
        resp = await loop.run_in_executor(
            None,
            partial(obsClient.putFile,
                    bucketName,
                    objectKey,
                    file_path,
                    headers=PutObjectHeader())
        )

        if resp and resp.status < 300:
            logging.info(f"{objectKey} successfully uploaded to {bucketName}")
            return True
        else:
            logging.error(f"{objectKey} failed to upload to {bucketName}. Response: {resp}")
            return False

    except Exception as e:
        logging.error(f"Failed to upload {objectKey} to {bucketName}. Error: {str(e)}\n{traceback.format_exc()}")
        return False
    finally:
        if obsClient is not None:
            await loop.run_in_executor(None, obsClient.close)

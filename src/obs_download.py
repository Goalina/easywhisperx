import time
import traceback
import configparser
from obs import ObsClient, GetObjectHeader


def init_obs_client():
    config = configparser.ConfigParser()
    config.read("/app/easywhisperx/config/config.ini")

    ak = config.get("obs", "AccessKeyID", fallback="").replace('"', "").strip()
    sk = config.get("obs", "SecretAccessKey", fallback="").replace('"', "").strip()
    server = "https://obs.ap-southeast-1.myhuaweicloud.com"

    return ObsClient(access_key_id=ak, secret_access_key=sk, server=server)


def download_file(bucket_name, object_key, download_path):
    obsClient = init_obs_client()
    try:
        start_time = time.time()
        headers = GetObjectHeader()

        resp = obsClient.getObject(
            bucket_name, object_key, download_path, headers=headers
        )

        if resp.status < 300:
            return {
                "success": True,
                "requestId": resp.requestId,
                "url": resp.body.url,
                "time_cost": time.time() - start_time,
            }
        else:
            return {
                "success": False,
                "errorCode": resp.errorCode,
                "errorMessage": resp.errorMessage,
            }
    except Exception as e:
        print(traceback.format_exc())
        return {"success": False, "errorMessage": str(e)}
    finally:
        obsClient.close()

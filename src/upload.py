import os

from obs import ObsClient
from obs import PutObjectHeader
import traceback


def upload(server: str, bucketName: str, objectKey: str, file_path: str):
    # 从环境变量获取ak
    ak = os.getenv("HUAWEICLOUD_SIS_AK", "")
    assert ak is not None, "Please add ak in your develop environment"
    # 从环境变量获取sk
    sk = os.getenv("HUAWEICLOUD_SIS_SK", "")
    assert sk is not None, "Please add sk in your develop environment"

    server = f"https://{server}"

    obsClient = ObsClient(access_key_id=ak, secret_access_key=sk, server=server)

    try:
        # 上传对象的附加头域
        headers = PutObjectHeader()
        # 【可选】待上传对象的MIME类型
        # headers.contentType = 'text/plain'
        bucketName = bucketName
        # 对象名，即上传后的文件名
        objectKey = objectKey
        # 待上传文件的完整路径，如aa/bb.txt
        file_path = file_path
        # 上传文件的自定义元数据
        # metadata = {'meta1': 'value1', 'meta2': 'value2'}
        # 文件上传
        resp = obsClient.putFile(bucketName, objectKey, file_path, headers)
        # 返回码为2xx时，接口调用成功，否则接口调用失败
        if resp.status < 300:
            print("Put File Succeeded")
            print("requestId:", resp.requestId)
            print("etag:", resp.body.etag)
            print("versionId:", resp.body.versionId)
            print("storageClass:", resp.body.storageClass)
        else:
            print("Put File Failed")
            print("requestId:", resp.requestId)
            print("errorCode:", resp.errorCode)
            print("errorMessage:", resp.errorMessage)
    except Exception as e:
        print("Put File Failed", e)
        print(traceback.format_exc())

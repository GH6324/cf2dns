#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Mail: tongdongdong@outlook.com
# Reference: https://cloud.tencent.com/document/product/1427/56193  (DNSPod API 3.0)
# Signature: https://cloud.tencent.com/document/api/1427/56189    (TC3-HMAC-SHA256)
#
# 原实现依赖 tencentcloud-sdk-python，现改为标准库直连 + 自行签名。
# 公开方法签名与返回结构保持不变，引擎侧无需感知。

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from . import base

HOST = 'dnspod.tencentcloudapi.com'
SERVICE = 'dnspod'
VERSION = '2021-03-23'
ALGORITHM = 'TC3-HMAC-SHA256'
CONTENT_TYPE = 'application/json; charset=utf-8'

#「该子域名下还没有任何记录」——不是错误，按空列表处理
EMPTY_RECORD_CODES = (
    'ResourceNotFound.NoDataOfRecord',
    'ResourceNotFound.NoDataOfSubDomain',
)


def _sha256hex(data):
    if not isinstance(data, bytes):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key, message):
    if not isinstance(key, bytes):
        key = key.encode('utf-8')
    return hmac.new(key, message.encode('utf-8'), hashlib.sha256)


class QcloudApiv3():
    def __init__(self, SECRETID, SECRETKEY):
        self.SecretId = SECRETID
        self.secretKey = SECRETKEY

    #------------------------------------------------------------------ 签名与请求

    def _authorization(self, action, payload, timestamp):
        """按 TC3-HMAC-SHA256 计算 Authorization 头。

        content-type 与 host 是必选签名头，这里额外签 x-tc-action（取小写）。
        SignedHeaders 必须与 CanonicalHeaders 严格一致且按字典序排列。
        """
        canonical_headers = 'content-type:{}\nhost:{}\nx-tc-action:{}\n'.format(
            CONTENT_TYPE, HOST, action.lower())
        signed_headers = 'content-type;host;x-tc-action'
        canonical_request = '\n'.join([
            'POST',
            '/',
            '',                      # CanonicalQueryString：POST 时为空
            canonical_headers,
            signed_headers,
            _sha256hex(payload),
        ])

        #Date 必须取 UTC 标准时间，且与 X-TC-Timestamp 同源
        date = datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d')
        credential_scope = '{}/{}/tc3_request'.format(date, SERVICE)
        string_to_sign = '\n'.join([
            ALGORITHM,
            str(timestamp),
            credential_scope,
            _sha256hex(canonical_request),
        ])

        secret_date = _hmac_sha256('TC3' + self.secretKey, date).digest()
        secret_service = _hmac_sha256(secret_date, SERVICE).digest()
        secret_signing = _hmac_sha256(secret_service, 'tc3_request').digest()
        signature = _hmac_sha256(secret_signing, string_to_sign).hexdigest()

        return '{} Credential={}/{}, SignedHeaders={}, Signature={}'.format(
            ALGORITHM, self.SecretId, credential_scope, signed_headers, signature)

    def _request(self, action, params):
        """调一次 DNSPod 接口。

        成功返回 (Response 内容, None)；接口报错返回 (None, {'Code':..,'Message':..})。
        原 SDK 会把错误抛成 TencentCloudSDKException，这里统一成返回值，
        由各方法翻译成 {code, message} —— 引擎失败分支要读 ret["message"]。
        """
        payload = json.dumps(params)
        timestamp = int(time.time())
        headers = {
            'Authorization': self._authorization(action, payload, timestamp),
            'Content-Type': CONTENT_TYPE,
            'Host': HOST,
            'X-TC-Action': action,
            'X-TC-Version': VERSION,
            'X-TC-Timestamp': str(timestamp),
        }
        _, body = base.http_json('POST', 'https://' + HOST, headers=headers, body=payload)
        if not isinstance(body, dict):
            return None, {'Code': 'InvalidResponse', 'Message': '接口返回无法解析: {}'.format(body)}
        #API 3.0 的返回体统一包一层 Response（原来由 SDK 拆掉）
        response = body.get('Response', body)
        if 'Error' in response:
            return None, response['Error']
        return response, None

    #------------------------------------------------------------------ 对外接口

    def del_record(self, domain: str, record_id: int):
        resp, error = self._request('DeleteRecord', {
            'Domain': domain,
            'RecordId': record_id,
        })
        if error:
            return {'code': -1, 'message': '{}: {}'.format(error.get('Code'), error.get('Message'))}
        resp = dict(resp or {})
        resp['code'] = 0
        resp['message'] = 'None'
        return resp

    def get_record(self, domain: str, length: int, sub_domain: str, record_type: str):
        def format_record(record: dict):
            new_record = {}
            record['id'] = record['RecordId']
            for key in record:
                new_record[key.lower()] = record[key]
            return new_record

        resp, error = self._request('DescribeRecordList', {
            'Domain': domain,
            'Subdomain': sub_domain,
            'RecordType': record_type,
            'Limit': length,
        })

        if error:
            #只有「没有记录」才当成空列表；鉴权失败等错误必须如实上报，
            #否则引擎会以为该子域名是空的，进而重复创建记录
            if error.get('Code') not in EMPTY_RECORD_CODES:
                return {
                    'code': -1,
                    'message': '{}: {}'.format(error.get('Code'), error.get('Message')),
                    'data': {'records': [], 'domain': {'grade': ''}},
                }
            records = []
        else:
            records = [format_record(record) for record in resp.get('RecordList', [])]

        return {
            'code': 0,
            'data': {
                'records': records,
                'domain': {'grade': self._grade(domain)},  # 形如 DP_Free
            },
        }

    def create_record(self, domain: str, sub_domain: str, value: int, record_type: str = "A", line: str = "默认", ttl: int = 600):
        resp, error = self._request('CreateRecord', {
            'Domain': domain,
            'SubDomain': sub_domain,
            'RecordType': record_type,
            'RecordLine': line,
            'Value': value,
            'TTL': ttl,
        })
        if error:
            return {'code': -1, 'message': '{}: {}'.format(error.get('Code'), error.get('Message'))}
        resp = dict(resp or {})
        resp['code'] = 0
        resp['message'] = 'None'
        return resp

    def change_record(self, domain: str, record_id: int, sub_domain: str, value: str, record_type: str = "A", line: str = "默认", ttl: int = 600):
        resp, error = self._request('ModifyRecord', {
            'Domain': domain,
            'SubDomain': sub_domain,
            'RecordType': record_type,
            'RecordLine': line,
            'Value': value,
            'TTL': ttl,
            'RecordId': record_id,
        })
        if error:
            return {'code': -1, 'message': '{}: {}'.format(error.get('Code'), error.get('Message'))}
        resp = dict(resp or {})
        resp['code'] = 0
        resp['message'] = 'None'
        return resp

    def get_domain(self, domain: str):
        resp, error = self._request('DescribeDomain', {'Domain': domain})
        if error:
            return {'code': -1, 'message': '{}: {}'.format(error.get('Code'), error.get('Message'))}
        return resp

    def _grade(self, domain: str):
        """取域名套餐等级，失败时返回空串。

        引擎只用它判断 "Free" in grade（免费版把 affect_num 压到 2）。
        取不到时返回空串即按非免费版处理，不能让整个 get_record 失败。
        """
        try:
            resp = self.get_domain(domain)
            return resp.get('DomainInfo', {}).get('Grade', '') or ''
        except Exception:
            return ''

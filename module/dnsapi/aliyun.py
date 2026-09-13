#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Mail: tongdongdong@outlook.com
# Reference: https://help.aliyun.com/document_detail/29776.html
# Signature: RPC 风格 HMAC-SHA1（SignatureVersion 1.0）
# REGION: https://help.aliyun.com/document_detail/198326.html
#
# 原实现依赖 aliyun-python-sdk-core / aliyun-python-sdk-alidns，现改为标准库直连 + 自行签名。
# 公开方法签名与返回结构保持不变。

import base64
import hashlib
import hmac
import urllib.parse
import uuid
from datetime import datetime, timezone

from . import base

#AliDNS 是中心化服务：region 只作 RegionId 参数传，不拼进域名
ENDPOINT = 'https://alidns.aliyuncs.com'
VERSION = '2015-01-09'

#中文线路名 ↔ 阿里云线路码
LINE_MAP = base.make_line_map({
    '默认': 'default',
    '电信': 'telecom',
    '联通': 'unicom',
    '移动': 'mobile',
    '境外': 'oversea',
})


def _percent_encode(value):
    """RFC3986 百分号编码。

    未保留字符为字母、数字、- _ . ~；其余一律编码。quote 的默认行为与阿里云要求
    只差三处，逐一修正（Python 下多为等价操作，显式写出以示意图）。
    """
    encoded = urllib.parse.quote(str(value), safe='')
    return encoded.replace('+', '%20').replace('*', '%2A').replace('%7E', '~')


def canonical_query_string(params):
    """按 key 字典序拼接已编码的 k=v，供签名与最终 URL 共用"""
    return '&'.join(
        '{}={}'.format(_percent_encode(key), _percent_encode(params[key]))
        for key in sorted(params)
    )


def string_to_sign(method, query_string):
    """StringToSign = METHOD & encode(/) & encode(CanonicalQueryString)"""
    return '{}&{}&{}'.format(method, _percent_encode('/'), _percent_encode(query_string))


def sign(secret, text):
    """Signature = Base64(HMAC-SHA1(AccessKeySecret + '&', StringToSign))

    注意密钥要额外追加一个 & —— 这是阿里云 V1 签名的固定要求。
    """
    digest = hmac.new((secret + '&').encode('utf-8'), text.encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(digest).decode('utf-8')


class AliApi():
    def __init__(self, ACCESSID, SECRETKEY, REGION='cn-hongkong'):
        self.access_key_id = ACCESSID
        self.access_key_secret = SECRETKEY
        self.region = REGION

    #------------------------------------------------------------------ 签名与请求

    def _common_params(self, action):
        return {
            'Action': action,
            'Version': VERSION,
            'Format': 'JSON',
            'AccessKeyId': self.access_key_id,
            'SignatureMethod': 'HMAC-SHA1',
            'SignatureVersion': '1.0',
            'SignatureNonce': uuid.uuid4().hex,
            'Timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'RegionId': self.region,
        }

    def _request(self, action, params):
        """调一次 AliDNS 接口，返回 (解析后的 body, 错误信息或 None)"""
        query = self._common_params(action)
        for key, value in params.items():
            if value is not None:
                query[key] = value

        query_string = canonical_query_string(query)
        signature = sign(self.access_key_secret, string_to_sign('GET', query_string))
        url = '{}/?{}&Signature={}'.format(ENDPOINT, query_string, _percent_encode(signature))

        status, body = base.http_json('GET', url)
        if not isinstance(body, dict):
            return None, '接口返回无法解析: {}'.format(body)
        #阿里云的错误体形如 {"Code":"InvalidAccessKeyId.NotFound","Message":"...","RequestId":"..."}
        if status != 200 or 'Code' in body:
            return None, '{}: {}'.format(body.get('Code', status), body.get('Message', ''))
        return body, None

    #------------------------------------------------------------------ 对外接口

    def del_record(self, domain, record):
        body, error = self._request('DeleteDomainRecord', {'RecordId': record})
        if error:
            return base.err(error)
        return base.ok(body)

    def get_record(self, domain, length, sub_domain, record_type):
        """查记录并翻译成引擎期望的结构。

        原实现是在**原始 JSON 文本**上做 replace 链（'RecordId'→'id' 与 'Record'→'records'
        互相包含、顺序敏感，还会误伤记录值里恰好含 telecom/default 等字样的内容）。
        这里改成先 json 解析、再按结构转换。
        """
        body, error = self._request('DescribeDomainRecords', {
            'DomainName': domain,
            'PageSize': length,
            'RRKeyWord': sub_domain,
            'Type': record_type,
        })
        if error:
            return base.records_error(error)

        records = []
        for record in body.get('DomainRecords', {}).get('Record', []):
            records.append({
                'id': record.get('RecordId'),
                'line': LINE_MAP.get(record.get('Line'), record.get('Line')),
                'value': record.get('Value'),
                'name': record.get('RR'),
                'type': record.get('Type'),
                'ttl': record.get('TTL'),
            })
        return base.records_response(records)

    def create_record(self, domain, sub_domain, value, record_type, line, ttl):
        body, error = self._request('AddDomainRecord', {
            'DomainName': domain,
            'RR': sub_domain,
            'Type': record_type,
            'Value': value,
            'Line': LINE_MAP.get(line, line),
            'TTL': ttl,
        })
        if error:
            return base.err(error)
        return base.ok(body)

    def change_record(self, domain, record_id, sub_domain, value, record_type, line, ttl):
        body, error = self._request('UpdateDomainRecord', {
            'RecordId': record_id,
            'RR': sub_domain,
            'Type': record_type,
            'Value': value,
            'Line': LINE_MAP.get(line, line),
            'TTL': ttl,
        })
        if error:
            return base.err(error)
        return base.ok(body)

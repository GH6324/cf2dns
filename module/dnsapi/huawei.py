#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author/Mail: tongdongdong@outlook.com
# Reference: https://support.huaweicloud.com/api-dns/
# Signature: AK/SK 认证（SDK-HMAC-SHA256）
# REGION: https://developer.huaweicloud.com/endpoint
#
# 原实现依赖 huaweicloudsdkdns，现改为标准库直连 + 自行签名。
#
# 华为云 DNS 模型说明：
# - 每个 IP 一个独立的 recordset
# - 更新策略：先尝试直接更新，失败再删除后创建
#
# REST 路径（均已对照官方文档核对）：
#   list zones     GET    /v2/zones?type=public
#   list recordset GET    /v2.1/recordsets?name=&type=&limit=
#   create         POST   /v2.1/zones/{zone_id}/recordsets
#   update         PUT    /v2.1/zones/{zone_id}/recordsets/{recordset_id}
#   delete         DELETE /v2.1/zones/{zone_id}/recordsets/{recordset_id}

import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone

from . import base

ALGORITHM = 'SDK-HMAC-SHA256'

#中文线路名 ↔ 华为云线路码
LINE_MAP = base.make_line_map({
    '默认': 'default_view',
    '电信': 'Dianxin',
    '联通': 'Liantong',
    '移动': 'Yidong',
    '境外': 'Abroad',
})


class HuaWeiApi():
    def __init__(self, ACCESSID, SECRETKEY, REGION = 'cn-east-3'):
        self.AK = ACCESSID
        self.SK = SECRETKEY
        self.region = REGION
        self.endpoint = 'dns.{}.myhuaweicloud.com'.format(REGION)
        #zone_id 惰性求值：构造函数里发网络请求的话，密钥错误会在入口脚本顶层抛异常、
        #连日志都进不去
        self._zone_id = None
        # 缓存已删除的 recordset ID，避免重复删除
        self._deleted_ids = set()

    #------------------------------------------------------------------ 签名与请求

    def _sign(self, method, path, canonical_query, body, headers):
        """按 SDK-HMAC-SHA256 计算 Authorization 头。

        X-Sdk-Date 必须在 signed_headers 内；canonical uri 要以 / 结尾。
        canonical_query 由 _canonical_query 生成，必须与实际发出的 query 完全一致。
        """
        canonical_uri = path if path.endswith('/') else path + '/'

        lower_headers = {k.lower(): str(v).strip() for k, v in headers.items()}
        signed_headers = ';'.join(sorted(lower_headers))
        canonical_headers = ''.join(
            '{}:{}\n'.format(k, lower_headers[k]) for k in sorted(lower_headers)
        )

        canonical_request = '\n'.join([
            method,
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            hashlib.sha256((body or '').encode('utf-8')).hexdigest(),
        ])

        string_to_sign = '\n'.join([
            ALGORITHM,
            lower_headers['x-sdk-date'],
            hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
        ])
        signature = hmac.new(
            self.SK.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256
        ).hexdigest()

        return '{} Access={}, SignedHeaders={}, Signature={}'.format(
            ALGORITHM, self.AK, signed_headers, signature)

    @staticmethod
    def _canonical_query(query):
        """按 key 字典序拼接已编码的 k=v。

        签名与实际请求 URL 必须共用这一份，否则遇到 name=xxx.域名. 这类含点号、
        或将来出现含特殊字符的参数时，两边编码不一致会直接签名失败。
        """
        return '&'.join(
            '{}={}'.format(
                urllib.parse.quote(str(k), safe='-_.~'),
                urllib.parse.quote(str(query[k]), safe='-_.~'))
            for k in sorted(query)
        )

    def _request(self, method, path, query=None, body=None):
        """调一次华为云 DNS 接口，返回 (解析后的 body, 错误信息或 None)"""
        query = query or {}
        payload = json.dumps(body) if body is not None else ''
        canonical_query = self._canonical_query(query)

        headers = {
            'Host': self.endpoint,
            'X-Sdk-Date': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        }
        if body is not None:
            headers['Content-Type'] = 'application/json'

        headers['Authorization'] = self._sign(method, path, canonical_query, payload, headers)

        url = 'https://{}{}'.format(self.endpoint, path)
        if canonical_query:
            url += '?' + canonical_query

        status, result = base.http_json(
            method, url, headers=headers, body=payload if body is not None else None)

        #成功：2xx。华为云写操作多返回 202
        if 200 <= status < 300:
            return result, None
        if isinstance(result, dict):
            return None, '{}: {}'.format(result.get('code', status), result.get('message', ''))
        return None, 'HTTP {}: {}'.format(status, result)

    #------------------------------------------------------------------ 对外接口

    def del_record(self, domain, record_id):
        """ 删除记录 """
        if record_id in self._deleted_ids:
            return base.ok({'status': 'already_deleted'})
        try:
            zone_id = self.get_zone_id(domain)
            result, error = self._request(
                'DELETE', '/v2.1/zones/{}/recordsets/{}'.format(zone_id, record_id))
            if error:
                return base.err(error)
            self._deleted_ids.add(record_id)
            return base.ok(result)
        except Exception as e:
            return base.err(e)

    def get_record(self, domain, length, sub_domain, record_type):
        """ 获取 DNS 记录，智能清理多IP的recordset """
        self._deleted_ids = set()

        try:
            if sub_domain == '@':
                name = domain + "."
            else:
                name = sub_domain + '.' + domain + "."

            data, error = self._request('GET', '/v2.1/recordsets', query={
                'limit': length,
                'type': record_type,
                'name': name,
            })
            if error:
                return base.records_error(error)

            # 按线路分组 recordset
            line_recordsets = {}
            for record in (data or {}).get('recordsets', []):
                if record.get('name') != name:
                    continue
                line = record.get('line')
                if line not in line_recordsets:
                    line_recordsets[line] = []
                line_recordsets[line].append(record)

            # 智能清理：删除多IP的recordset，只保留单IP的
            records_temp = []
            for line, recordsets in line_recordsets.items():
                line_name = self.line_format(line)
                single_ip_rs = [rs for rs in recordsets if len(rs.get('records', [])) == 1]
                multi_ip_rs = [rs for rs in recordsets if len(rs.get('records', [])) > 1]

                # 删除所有多IP的recordset
                for rs in multi_ip_rs:
                    self.del_record(domain, rs['id'])

                # 只返回单IP的recordset
                for rs in single_ip_rs:
                    records_temp.append({
                        'id': rs['id'],
                        'line': line_name,
                        'value': rs['records'][0]
                    })

            return base.records_response(records_temp)
        except Exception as e:
            return base.records_error(e)

    def create_record(self, domain, sub_domain, value, record_type, line, ttl):
        """ 创建记录 """
        try:
            if sub_domain == '@':
                name = domain + "."
            else:
                name = sub_domain + '.' + domain + "."

            zone_id = self.get_zone_id(domain)
            result, error = self._request(
                'POST', '/v2.1/zones/{}/recordsets'.format(zone_id), body={
                    'type': record_type,
                    'name': name,
                    'ttl': ttl,
                    'weight': 1,
                    'records': [value],
                    'line': self.line_format(line),
                })
            if error:
                return base.err(error)
            return base.ok(result)
        except Exception as e:
            return base.err(e)

    def update_record(self, domain, record_id, sub_domain, value, record_type, ttl):
        """ 直接更新记录 """
        if sub_domain == '@':
            name = domain + "."
        else:
            name = sub_domain + '.' + domain + "."

        try:
            zone_id = self.get_zone_id(domain)
            result, error = self._request(
                'PUT', '/v2.1/zones/{}/recordsets/{}'.format(zone_id, record_id), body={
                    'name': name,
                    'type': record_type,
                    'ttl': ttl,
                    'records': [value],
                })
            if error:
                return {'error': error}, False
            return result, True
        except Exception as e:
            return {'error': str(e)}, False

    def change_record(self, domain, record_id, sub_domain, value, record_type, line, ttl):
        """ 更新记录 - 优先直接更新，失败则删除后创建 """
        try:
            # 如果该 recordset 已被删除，直接创建新的
            if record_id in self._deleted_ids:
                return self.create_record(domain, sub_domain, value, record_type, line, ttl)

            # 尝试直接更新
            result, success = self.update_record(domain, record_id, sub_domain, value, record_type, ttl)
            if success:
                return base.ok(result)

            # 更新失败，回退到删除+创建
            self.del_record(domain, record_id)
            return self.create_record(domain, sub_domain, value, record_type, line, ttl)
        except Exception as e:
            return base.err(e)

    def get_zones(self):
        """查询公网域名列表，返回 {域名(带尾点): zone_id}"""
        data, error = self._request('GET', '/v2/zones', query={'type': 'public'})
        if error:
            raise IOError('查询域名列表失败: {}'.format(error))
        zone_id = {}
        for zone in (data or {}).get('zones', []):
            zone_id[zone['name']] = zone['id']
        return zone_id

    def get_zone_id(self, domain):
        """取域名对应的 zone_id，首次调用时拉取并缓存"""
        if self._zone_id is None:
            self._zone_id = self.get_zones()
        key = domain + '.'
        if key not in self._zone_id:
            raise KeyError('未在该账号下找到域名 {}（区域 {}）'.format(domain, self.region))
        return self._zone_id[key]

    def line_format(self, line):
        return LINE_MAP.get(line, line)

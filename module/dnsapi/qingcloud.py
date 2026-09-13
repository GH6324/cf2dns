#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Reference: https://docsv4.qingcloud.com/user_guide/development_docs/api/api_list/dns/api_intro/
# Signature: QC-HMAC-SHA256（Verb + Date + CanonicalizedResource，HMAC-SHA256 后 Base64）
#
# 青云云解析 DNS。与另三家一样不依赖厂商 SDK，用标准库自行签名。
#
# 服务地址是 api.routewize.com（不是 qingcloud.com），文档给的是 http，这里一律用 https。
#
# REST 路径（均已对照官方文档核对）：
#   zone 列表       GET  /v1/user/zones
#   host 下的记录   GET  /v1/dns/host_info/
#   单条记录        GET  /v1/dr_id/<domain_record_id>
#   建记录          POST /v1/record/
#   改记录          POST /v1/dr_id/<domain_record_id>
#   删记录/改状态   POST /v1/change_record_status/
#   zone 线路       GET  /v1/zone/view/  |  POST /v1/zone/view/
#   线路清单        GET  /v1/view/       （仅诊断用，文档的响应示例是空的）
#
# ---------------------------------------------------------------------------
# 与另三家最大的模型差异：**一条记录装多个 IP**
#
# 青云同一 (domain_name, view_id, type) 只有一条 domain_record_id，多个 IP 是它下面的
# record[].data[]。而引擎要的是「一 record = 一 IP」、靠 recordId 逐条改。
# 对齐办法：把每个 record_value_id 当成引擎眼里的一条记录，id 用复合键
# "<domain_record_id>:<record_value_id>"。
#
# 由此派生出三条必须守住的约束（改动本文件时别退回去）：
#
#   a) create_record 必须是 upsert。首次运行时空记录 + affect_num=2，引擎会连调
#      create_record 两次；同一 (name, view_id, type) 本应只有一条 domain_record_id，
#      第二次盲目 POST /v1/record/ 的行为文档没写。所以先查有没有，有就追加进值列表。
#
#   b) change_record 每次都要重新读，绝不能缓存。同线路的多个值挂在同一个 dr_id 上：
#      第一次 change 写回 [A, old2]，第二次必须读到这个新状态才能写出 [A, B]；
#      复用旧读取会写成 [old1, B]，把刚写进去的 A 冲掉。
#
#   c) record_value_id 更新后是否保号，文档没说。匹配不到时按位置退化，再不行退成
#      删旧建新，并且必须记 error —— 静默失败会表现成「日志成功、控制台没变」。
#
# 稳定态不会累加：change 是替换而非追加，引擎第二次跑时 create_num == 0、只走 change。
# ---------------------------------------------------------------------------

import email.utils
import base64
import hashlib
import hmac
import json
import urllib.parse

from . import base

ENDPOINT = 'https://api.routewize.com'
ALGORITHM = 'QC-HMAC-SHA256'

#中文线路名 ↔ 青云线路名
LINE_MAP = base.make_line_map({
    '默认': 'default',
    '电信': 'cn_tx',
    '联通': 'cn_lt',
    '移动': 'cn_yd',
    '境外': 'hk_tw_mo_overseas',
})

#中文线路名 → view_id。青云用整数 view_id 标识线路。
#⚠️ 这几个数字只在官方文档 zone 章节的**示例代码**里出现过，青云没给正式取值表，
#GET /v1/view/ 的响应示例又是空的 {}。实机第一步应调 describe_views() 核对。
VIEW_IDS = {
    '默认': 0,
    '电信': 2,
    '联通': 3,
    '移动': 4,
    '境外': 8,
}
#view_id → 中文线路名。0 会与 falsy 混淆，取值时一律用 `in` 判断而不是 `or` 兜底
VIEW_LINES = {v: k for k, v in VIEW_IDS.items()}

#记录模式：1 普通 / 2 轮询 / 3 权重 / 4 智能。三网优选要的是多 IP 轮流返回
MODE_ROUND_ROBIN = 2
#1 = 不允许自动合并。允许合并时接口「只返回合并记录的值，不会返回全量记录列表」，
#记录形状就不可预测了
AUTO_MERGE_OFF = 1


def canonical_resource(path, query=None):
    """CanonicalizedResource：请求路径，带 query 时把参数按 key 字母序用 & 连接后拼到末尾。

    与实际请求 URL 必须共用这一份 —— 两边各自编码一次就会签名失败（华为云那边踩过）。
    """
    if not query:
        return path
    pairs = '&'.join(
        '{}={}'.format(urllib.parse.quote(str(k), safe='-_.~'),
                       urllib.parse.quote(str(query[k]), safe='-_.~'))
        for k in sorted(query)
    )
    return '{}?{}'.format(path, pairs)


def string_to_sign(method, date, resource):
    """StringToSign = Verb \n Date \n CanonicalizedResource"""
    return '{}\n{}\n{}'.format(method, date, resource)


def sign(secret, text):
    """Signature = Base64(HMAC-SHA256(secret_access_key, StringToSign))"""
    digest = hmac.new(secret.encode('utf-8'), text.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(digest).decode('utf-8')


def gmt_date():
    """RFC822 GMT 格式的当前时间。

    必须用 email.utils.formatdate 而不是 strftime('%a, %d %b %Y ...')：
    %a/%b 受 locale 影响，中文环境下会签出「周二」「12月」这种东西，直接 401。
    """
    return email.utils.formatdate(usegmt=True)


def _fqdn(name):
    """补尾点。青云的 zone_name / domain_name 一律带尾点（1.com. / 14.1.com.）"""
    name = str(name)
    return name if name.endswith('.') else name + '.'


def _strip_dot(name):
    """去尾点，用于比对"""
    return str(name).rstrip('.')


class QingCloudApi():
    def __init__(self, ACCESSID, SECRETKEY):
        self.access_key_id = ACCESSID
        self.secret_access_key = SECRETKEY
        #zone 列表惰性求值：构造函数里发请求的话，密钥错误会在入口脚本顶层抛异常、
        #连日志都进不去（huawei.py 踩过这个坑）
        self._zones = None
        #zone_name → 已启用的 zone_views 列表，一次运行内不重复查
        self._zone_views = {}
        #已删除的 id，避免重复删
        self._deleted_ids = set()

    #------------------------------------------------------------------ 签名与请求

    def _authorization(self, method, resource, date):
        return '{} {}:{}'.format(
            ALGORITHM, self.access_key_id,
            sign(self.secret_access_key, string_to_sign(method, date, resource)))

    def _request(self, method, path, params=None):
        """调一次青云 DNS 接口，返回 (解析后的 body, 错误信息或 None)。

        文档里 GET 接口也带数据体，但 CanonicalizedResource 只含路径与 query、body 不参与
        签名。为兼容性把参数同时放进 query 与 body，两边是同一份值。
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resource = canonical_resource(path, params)
        date = gmt_date()

        headers = {
            'Date': date,
            'Authorization': self._authorization(method, resource, date),
        }
        body = None
        if params:
            body = json.dumps(params)
            headers['Content-Type'] = 'application/json'

        status, result = base.http_json(
            method, ENDPOINT + resource, headers=headers, body=body)

        #成功状态码不统一：建/改 201、删 200、UpdateZoneView 200、zone 增删 204。
        #一律按 2xx 判断，不写死数字
        if 200 <= status < 300:
            #错误也可能以 2xx + code!=0 的形式回来
            if isinstance(result, dict) and result.get('code') not in (None, 0, '0'):
                return None, self._error_text(result, status)
            return result, None
        if isinstance(result, dict):
            return None, self._error_text(result, status)
        return None, 'HTTP {}: {}'.format(status, result)

    @staticmethod
    def _error_text(result, status):
        """错误信息。响应里 msg 与 message 两种键名都出现过，两个都兜"""
        message = result.get('message') or result.get('msg') or ''
        return '{}: {}'.format(result.get('code', status), message)

    #------------------------------------------------------------------ zone

    def get_zones(self):
        """拉 zone 列表，返回 {去尾点的域名: 带尾点的 zone_name}"""
        data, error = self._request('GET', '/v1/user/zones', {'limit': 100, 'offset': 0})
        if error:
            raise IOError('查询 zone 列表失败: {}'.format(error))
        zones = {}
        for zone in (data or {}).get('zones', []):
            name = zone.get('zone_name')
            if name:
                zones[_strip_dot(name)] = _fqdn(name)
        return zones

    def get_zone_name(self, domain):
        """取域名对应的 zone_name（带尾点），首次调用时拉取并缓存"""
        if self._zones is None:
            self._zones = self.get_zones()
        key = _strip_dot(domain)
        if key not in self._zones:
            raise KeyError('未在该青云账号下找到域名 {}'.format(domain))
        return self._zones[key]

    def _ensure_zone_view(self, zone_name, view_id):
        """确保 zone 启用了该解析线路，否则记录挂不上去。

        ⚠️ POST /v1/zone/view/ 是**整份覆盖** zone_views —— 必须先读现有列表再追加，
        只提交新线路会把用户已配的其它线路抹掉。
        """
        #默认线路（0）始终可用，不需要启用
        if view_id == 0:
            return

        views = self._zone_views.get(zone_name)
        if views is None:
            data, error = self._request('GET', '/v1/zone/view/', {
                'zone_name': zone_name,
                'action': 'GET_USING',
            })
            if error:
                raise IOError('查询 zone 解析线路失败: {}'.format(error))
            views = list((data or {}).get('zone_views', []))
            self._zone_views[zone_name] = views

        if any(int(v.get('id', -1)) == int(view_id) for v in views):
            return

        #在现有列表基础上追加，保留已有线路
        merged = views + [{
            'id': view_id,
            'name': LINE_MAP.get(VIEW_LINES.get(view_id, ''), str(view_id)),
        }]
        _, error = self._request('POST', '/v1/zone/view/', {
            'zone_name': zone_name,
            'zone_views': json.dumps(merged),
        })
        if error:
            raise IOError('启用 zone 解析线路失败: {}'.format(error))
        self._zone_views[zone_name] = merged

    #------------------------------------------------------------------ 记录读写辅助

    @staticmethod
    def _record_name(zone_name, sub_domain):
        """子域名 → 带尾点的完整 domain_name。@ 表示 zone 本身"""
        if sub_domain == '@' or not sub_domain:
            return _fqdn(zone_name)
        return _fqdn('{}.{}'.format(sub_domain, _strip_dot(zone_name)))

    @staticmethod
    def _split_id(record_id):
        """复合 id "<dr_id>:<rv_id>" → (dr_id, rv_id)。不含 : 时 rv_id 为 None"""
        text = str(record_id)
        if ':' not in text:
            return text, None
        dr_id, _, rv_id = text.partition(':')
        return dr_id, rv_id

    def _describe_record(self, dr_id):
        """读回单条记录的完整内容（含全部值）。

        每次 change 都必须重新调这个，不能缓存 —— 同线路的多个值共享一个 dr_id，
        用陈旧数据写回会把同一轮里刚写进去的 IP 冲掉。
        """
        data, error = self._request('GET', '/v1/dr_id/{}'.format(dr_id))
        if error:
            return None, error
        return (data or {}).get('data') or {}, None

    @staticmethod
    def _values_of(record_data):
        """展平记录的值列表 → [{'id': rv_id, 'value': ip, 'weight': w}]"""
        values = []
        for group in record_data.get('record', []):
            weight = group.get('weight', 0)
            for item in group.get('data', []):
                values.append({
                    'id': item.get('record_value_id'),
                    'value': item.get('value'),
                    'weight': weight,
                })
        return values

    @staticmethod
    def _pack_values(values):
        """值列表 → 接口要的 JSON 字符串。

        文档要求「必须按示例中格式传递，不能缺少任何字段」。轮询模式下 weight 无意义，
        统一取 0，避免把读回来的杂值传回去。
        """
        return json.dumps([{
            'weight': 0,
            'values': [{'value': v['value'], 'status': 1} for v in values],
        }])

    def _write_values(self, dr_id, record_data, values, record_type, ttl):
        """把整份值列表写回一条记录。

        注意字段名是 records（复数）—— 建记录时叫 record（单数），文档两处就是不一致，
        别顺手"统一"掉。
        """
        return self._request('POST', '/v1/dr_id/{}'.format(dr_id), {
            'domain_name': record_data.get('domain_name'),
            'view_id': record_data.get('view_id', 0),
            'class': record_data.get('rd_class', 'IN'),
            'type': record_type or record_data.get('rd_type'),
            'ttl': ttl,
            'records': self._pack_values(values),
            'mode': record_data.get('mode', MODE_ROUND_ROBIN),
        })

    def _find_record(self, zone_name, name, view_id, record_type):
        """查 (name, view_id, type) 对应的 domain_record_id，没有则返回 None"""
        data, error = self._request('GET', '/v1/dns/host_info/', {
            'domain_name': name,
            'zone_name': zone_name,
        })
        if error:
            return None, error
        for record in (data or {}).get('records', []):
            if record.get('rd_type') != record_type:
                continue
            if int(record.get('view_id', 0)) != int(view_id):
                continue
            return record, None
        return None, None

    #------------------------------------------------------------------ 对外接口

    def get_record(self, domain, length, sub_domain, record_type):
        """查记录，把青云的嵌套结构展平成引擎期望的「一 record 一 IP」。

        失败必须返回非 0 code 且 records 为空列表：引擎对非 DNSPod 解析商会检查 code，
        把「查询失败」当成「没有记录」会导致重复创建。
        """
        self._deleted_ids = set()
        try:
            zone_name = self.get_zone_name(domain)
            name = self._record_name(zone_name, sub_domain)

            data, error = self._request('GET', '/v1/dns/host_info/', {
                'domain_name': name,
                'zone_name': zone_name,
            })
            if error:
                #host 还不存在（26 = Can't find the resource）是正常空态，不是故障
                if str(error).startswith('26:'):
                    return base.records_response([])
                return base.records_error(error)

            records = []
            for record in (data or {}).get('records', []):
                if record.get('rd_type') != record_type:
                    continue
                dr_id = record.get('domain_record_id')
                view_id = int(record.get('view_id', 0))
                #未知 view_id 保留原始数字，引擎按线路名匹配时自然不会命中，
                #不会误当成三网里的某条
                line = VIEW_LINES.get(view_id, str(view_id))
                for value in self._values_of(record):
                    records.append({
                        'id': '{}:{}'.format(dr_id, value['id']),
                        'line': line,
                        'value': value['value'],
                        'name': _strip_dot(record.get('domain_name', '')),
                        'type': record.get('rd_type'),
                        'ttl': record.get('ttl'),
                    })
            return base.records_response(records)
        except Exception as e:
            return base.records_error(e)

    def create_record(self, domain, sub_domain, value, record_type, line, ttl):
        """新增一个 IP。是 upsert —— 该线路已有记录时追加进值列表，而不是再建一条。

        引擎首次运行会按 affect_num 连调本方法多次，而青云同一 (name, view_id, type)
        只应有一条 domain_record_id。
        """
        try:
            zone_name = self.get_zone_name(domain)
            name = self._record_name(zone_name, sub_domain)
            view_id = VIEW_IDS.get(line)
            if view_id is None:
                return base.err('青云不支持的解析线路: {}'.format(line))

            self._ensure_zone_view(zone_name, view_id)

            existing, error = self._find_record(zone_name, name, view_id, record_type)
            if error:
                return base.err(error)

            if existing is None:
                result, error = self._request('POST', '/v1/record/', {
                    'zone_name': zone_name,
                    'domain_name': name,
                    'view_id': view_id,
                    'type': record_type,
                    'ttl': ttl,
                    'record': self._pack_values([{'value': value}]),
                    'mode': MODE_ROUND_ROBIN,
                    'auto_merge': AUTO_MERGE_OFF,
                })
                if error:
                    return base.err(error)
                return base.ok(result)

            #已有记录：追加这个 IP。重复值直接当成功，避免把同一 IP 塞两遍
            dr_id = existing.get('domain_record_id')
            values = self._values_of(existing)
            if any(v['value'] == value for v in values):
                return base.ok({'status': 'already_exists'})
            values.append({'value': value})
            result, error = self._write_values(dr_id, existing, values, record_type, ttl)
            if error:
                return base.err(error)
            return base.ok(result)
        except Exception as e:
            return base.err(e)

    def change_record(self, domain, record_id, sub_domain, value, record_type, line, ttl):
        """把复合 id 指向的那一个 IP 换成新值，同记录里的其它 IP 原样保留。

        每次都重新读回整条记录 —— 同线路的多个值共享一个 dr_id，用陈旧数据写回会把
        同一轮里刚写进去的 IP 冲掉。
        """
        try:
            dr_id, rv_id = self._split_id(record_id)
            if dr_id in self._deleted_ids:
                return self.create_record(domain, sub_domain, value, record_type, line, ttl)
            if rv_id is None:
                #没有复合 id 可拆（老数据或异常），退成删旧建新
                return self._recreate(domain, dr_id, sub_domain, value, record_type, line, ttl,
                                      '记录 id 不含 record_value_id')

            record_data, error = self._describe_record(dr_id)
            if error:
                return base.err(error)

            values = self._values_of(record_data)
            if not values:
                return self._recreate(domain, dr_id, sub_domain, value, record_type, line, ttl,
                                      '记录 {} 读回后没有任何值'.format(dr_id))

            #按 record_value_id 定位目标值。青云是否在更新后保号，文档没说明；
            #匹配不上就退成删旧建新，绝不能静默跳过
            matched = False
            for item in values:
                if str(item['id']) == str(rv_id):
                    item['value'] = value
                    matched = True
                    break
            if not matched:
                return self._recreate(
                    domain, dr_id, sub_domain, value, record_type, line, ttl,
                    'record_value_id {} 已不存在（青云可能在更新后重新分配了 id）'.format(rv_id))

            result, error = self._write_values(dr_id, record_data, values, record_type, ttl)
            if error:
                return base.err(error)
            return base.ok(result)
        except Exception as e:
            return base.err(e)

    def _recreate(self, domain, dr_id, sub_domain, value, record_type, line, ttl, reason):
        """change 的退化路径：删掉整条记录后重建。

        返回的 message 带上原因，引擎会把它打进日志 —— 静默退化会表现成
        「日志成功、控制台没变」，排查时无从下手。
        """
        deleted = self.del_record(domain, dr_id)
        if deleted.get('code') != 0:
            return base.err('{}；且删除旧记录失败: {}'.format(reason, deleted.get('message')))
        created = self.create_record(domain, sub_domain, value, record_type, line, ttl)
        if created.get('code') != 0:
            return base.err('{}；重建记录失败: {}'.format(reason, created.get('message')))
        return base.ok(created.get('data'), message='已退化为删旧建新（{}）'.format(reason))

    def del_record(self, domain, record_id, target='record'):
        """删记录。target='record' 删整条（含同线路所有 IP），'value' 只删单个 IP。

        record_id 是复合键时按 target 取对应的那一段。
        """
        dr_id, rv_id = self._split_id(record_id)
        target_id = rv_id if target == 'value' and rv_id is not None else dr_id
        if target_id in self._deleted_ids:
            return base.ok({'status': 'already_deleted'})
        try:
            _, error = self._request('POST', '/v1/change_record_status/', {
                'ids': json.dumps([target_id]),
                'action': 'delete',
                'target': target,
            })
            if error:
                return base.err(error)
            self._deleted_ids.add(target_id)
            return base.ok({'status': 'deleted'})
        except Exception as e:
            return base.err(e)

    #------------------------------------------------------------------ 诊断

    def describe_views(self):
        """拉线路清单，仅供实机核对 VIEW_IDS，不进主流程。

        文档里这个接口的响应示例是空的 {}，字段名未知，所以原样返回不做解析。
        """
        data, error = self._request('GET', '/v1/view/')
        if error:
            return base.err(error)
        return base.ok(data)

    def line_format(self, line):
        return LINE_MAP.get(line, line)

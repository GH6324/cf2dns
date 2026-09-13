#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析商适配器公共件：线路名映射、响应构造、HTTP 请求。

三个适配器（qCloud / aliyun / huawei）统一用标准库实现签名与请求，不再依赖各家 SDK。
动机：宝塔 / aaPanel 的插件共用面板的 site-packages，SDK 版本会被其他插件的升级带崩；
两个面板的底层 Python 版本也不一致，SDK 兼容性无法保证。
"""

import json
import socket
import urllib.error
import urllib.request

#线路码 → 中文线路名。引擎内部一律用中文名，各家再翻译成自己的表示
LINES_CN = {
    'CM': '移动',
    'CU': '联通',
    'CT': '电信',
    'AB': '境外',
    'DEF': '默认',
}


def make_line_map(pairs):
    """由「中文名 → 厂商线路名」构造双向映射表。

    改造前华为在 line_format 里手写了正反两份、阿里则散落在 replace 链与 if-elif 里，
    这里统一成一处，避免正反两向改漏一边。
    """
    mapping = {}
    for cn, vendor in pairs.items():
        mapping[cn] = vendor
        mapping[vendor] = cn
    return mapping


def ok(data=None, message='success'):
    """构造成功响应，与引擎期望格式一致"""
    return {'code': 0, 'message': message, 'data': data}


def err(message):
    """构造错误响应，与引擎期望格式一致"""
    return {'code': -1, 'message': str(message)}


def records_response(records):
    """构造 get_record 的成功响应"""
    return {'code': 0, 'message': 'success', 'data': {'records': records}}


def records_error(message):
    """构造 get_record 的失败响应。

    records 必须给空列表：引擎对非 DNSPod 解析商不校验 code，会直接读 data.records。
    """
    return {'code': -1, 'message': str(message), 'data': {'records': []}}


#(连接超时, 读取超时)。urllib 只接受单一超时值，取两者较大的那个。
#改造前各家 SDK 调用都没设超时，面板同步请求里卡住会一直占着工作线程。
DEFAULT_TIMEOUT = (5, 10)


def _timeout_value(timeout):
    if isinstance(timeout, (tuple, list)):
        return max(timeout)
    return timeout


def http_json(method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
    """发一个 JSON 请求，返回 (状态码, 解析后的 body)。

    HTTP 错误（4xx/5xx）也读出 body 一并返回，由各家适配器解析自己的错误结构；
    只有网络层面的失败才抛异常。body 不是合法 JSON 时，第二个返回值是原始文本。
    """
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else body.encode('utf-8')

    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_timeout_value(timeout)) as response:
            return response.getcode(), _decode(response.read())
    except urllib.error.HTTPError as e:
        #4xx/5xx：厂商把错误码写在 body 里，读出来交给调用方判断
        try:
            payload = _decode(e.read())
        except Exception:
            payload = None
        return e.code, payload
    except (urllib.error.URLError, socket.timeout) as e:
        raise IOError('请求失败: {}'.format(e))


def _decode(raw):
    if not raw:
        return None
    text = raw.decode('utf-8', errors='replace')
    try:
        return json.loads(text)
    except Exception:
        return text

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析商适配层。

统一接口：get_record / create_record / change_record / del_record，
各自把厂商响应翻译成 DNSPod 风格 {code, message, data.records[{id, line, value}]}。

三家均不依赖厂商 SDK，只用标准库签名与请求（见 base.py 的说明）。
"""

from .aliyun import AliApi
from .huawei import HuaWeiApi
from .qCloud import QcloudApiv3
from .qingcloud import QingCloudApi

#dns_server 取值 → (适配器类, 存放地区的配置字段)
#新增解析商只需在这里登记一条，入口脚本都不用改
PROVIDERS = {
    1: (QcloudApiv3, None),          # DNSPod（腾讯云），无地区参数
    2: (AliApi, 'region_ali'),       # AliDNS（阿里云）
    3: (HuaWeiApi, 'region_hw'),     # 华为云 DNS
    4: (QingCloudApi, None),         # 青云 DNS，中心化服务、无地区参数
}


def create_client(config):
    """按 config['dns_server'] 构造对应的解析商适配器"""
    dns_server = config.get('dns_server')
    if dns_server not in PROVIDERS:
        raise ValueError('未知的解析商 dns_server={}，可选值：{}'.format(
            dns_server, sorted(PROVIDERS)))

    api_class, region_field = PROVIDERS[dns_server]
    secretid = config.get('secretid')
    secretkey = config.get('secretkey')
    if not secretid or not secretkey:
        raise ValueError('未配置 secretid / secretkey，请先在插件界面填写密钥')

    if region_field is None:
        return api_class(secretid, secretkey)

    region = config.get(region_field)
    if not region:
        #地区留空时交给适配器的默认值，不要传 None 进去
        return api_class(secretid, secretkey)
    return api_class(secretid, secretkey, region)


__all__ = ['AliApi', 'HuaWeiApi', 'QcloudApiv3', 'QingCloudApi', 'PROVIDERS', 'create_client']

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板控制器专用件：登录态校验、响应封装、请求参数解析。

只有 cf2dns_main.py 用得到，入口脚本不导入本模块。
"""

try:
    from flask import session
except Exception:
    #脱离面板环境（例如本地跑诊断脚本）时也要能导入
    session = None

#面板会话的登录标志键名。若实机确认键名不是 login，只改这一处。
#确认办法见 tests/auth_probe.py
SESSION_LOGIN_KEY = 'login'


def auth():
    """插件动态路由不继承面板会话权限，每个 public 方法都要自查登录态。"""
    if session is None:
        return False
    try:
        return bool(session.get(SESSION_LOGIN_KEY, False))
    except Exception:
        #取不到会话一律判为未通过，不能因为异常就放行
        return False


def response_json(data, code=0, msg=''):
    return {"code": code, "msg": msg, "data": data}


def denied():
    return response_json('', 401, '未登录或会话已过期，请重新登录面板')


def broken(name):
    """配置文件损坏时的统一回复"""
    return response_json('', 500, '{} 解析失败，为避免覆盖已保存的配置，请先修复该文件后再保存'.format(name))


def write_failed():
    """写入失败时的统一回复"""
    return response_json('', 500, '写入失败，请检查插件目录权限与磁盘空间')


def arg(args, name, default=None):
    """兼容属性与字典两种取值方式，参数缺失时返回默认值"""
    try:
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                return value
        if isinstance(args, dict) and name in args:
            return args[name]
    except Exception:
        pass
    return default


def int_arg(args, name, default):
    """取整数参数。

    前端清空数字输入框会提交空串，int('') 会抛 ValueError 让接口 500，
    所以空值与非法值一律回退默认值。
    """
    try:
        value = arg(args, name, default)
        if value is None or str(value).strip() == '':
            return int(default)
        return int(value)
    except Exception:
        try:
            return int(default)
        except Exception:
            return 0

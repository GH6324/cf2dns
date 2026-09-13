#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cf2dns 内部模块包。

入口脚本 cf2dns.py（三种部署形态共用）与面板控制器 cf2dns_main.py 共用这里的实现，
避免核心逻辑在各形态之间漂移。

放在 module/ 下而不是插件根目录，是为了不让插件根目录的模块名（如原来的 log.py、
dns/）在插件根目录进入 sys.path 后抢占同名的第三方包或标准库。
"""

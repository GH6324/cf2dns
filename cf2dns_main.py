#!/usr/bin/python
# coding: utf-8
#+--------------------------------------------------------------------
#|   CF2DNS OF BTPANEL
#|   AUTH GACJIE
#+--------------------------------------------------------------------
#
# 面板后端控制器。public 方法名即 API 端点：前端 send_request(api) → /cf2dns/<api>.json
# → 本文件同名方法。新增端点需同时改前端与这里。
#
# 通用件在 module/ 下：
#   module.store  配置文件定位与 JSON 读写（与入口脚本共用同一份实现）
#   module.panel  登录态校验、响应封装、参数解析
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

from module.dnsapi import base
from module.panel import arg, auth, broken, denied, int_arg, response_json, write_failed
from module.store import Store

class cf2dns_main:
    #info.json 由面板读取，必须留在插件根目录
    #以下数据文件统一放 config/
    def  __init__(self):
        self.store = Store(PLUGIN_DIR)
        self.__info_path = os.path.join(PLUGIN_DIR, 'info.json')
        self.__about_path = os.path.join(self.store.config_dir, 'about.json')
        self.__dns_provider_path = os.path.join(self.store.config_dir, 'dns_provider.json')
        self.__lines_path = os.path.join(self.store.config_dir, 'lines.json')
        self.__default_config_path = os.path.join(self.store.config_dir, 'default_config.json')

    #默认线路码取自 lines.json 中 default 为 true 的项，读取失败时回退三网
    def __default_lines(self):
        lines = self.store.read_json(self.__lines_path, [])
        codes = [item["code"] for item in lines if item.get("default")]
        return codes if codes else ["CM","CU","CT"]

    #各解析商声明的地区字段名，取自 dns_provider.json，读取失败时回退已知的两个
    def __region_fields(self):
        providers = self.store.read_json(self.__dns_provider_path, [])
        fields = [item.get("region_field") for item in providers if item.get("region_field")]
        return fields if fields else ["region_hw","region_ali"]

    #获取插件信息（info.json 元信息 + about.json 鸣谢与赞助）
    def get_plugin_info(self, args):
        if not auth(): return denied()
        result = {
            'info': self.store.read_json(self.__info_path, {}),
            'about': self.store.read_json(self.__about_path, {})
        }
        return response_json(result,200,'获取数据成功')

    #从获取解析配置信息，同时下发解析商清单与线路定义
    def get_home_info(self, args):
        if not auth(): return denied()
        data = self.store.read_json(self.store.path('config.json'), {})
        #config.json 缺少的字段用默认配置补齐，避免前端拿到 undefined
        default_data = self.store.read_json(self.__default_config_path, {})
        for key, value in default_data.items():
            if key not in data:
                data[key] = value
        result = {
            'config': data,
            'dns_providers': self.store.read_json(self.__dns_provider_path, []),
            'lines': self.store.read_json(self.__lines_path, [])
        }
        return response_json(result,200,'获取数据成功')
    #从设置解析配置信息
    def set_home_info(self, args):
        if not auth(): return denied()
        config_path = self.store.path('config.json')
        data = self.store.read_for_write(config_path)
        if data is None:
            return broken('config.json')
        data['ipv4'] = arg(args,'ipv4', data.get('ipv4','on'))
        data['ipv6'] = arg(args,'ipv6', data.get('ipv6','on'))
        data['dns_server'] = int_arg(args,'dns_server', data.get('dns_server',1))
        # data['cdn_server'] = int(args.cdn_server)
        data['affect_num'] = int_arg(args,'affect_num', data.get('affect_num',2))
        data['ttl'] = int_arg(args,'ttl', data.get('ttl',600))
        data['secretid'] = (arg(args,'secretid','') or '').strip()
        data['secretkey'] = (arg(args,'secretkey','') or '').strip()
        # data['key'] = args.key
        # data['data_server'] = int(args.data_server)
        #地区字段取自 dns_provider.json 的 region_field，不写死字段名，新增解析商无需改这里。
        #仅在该解析商被选中时由前端下发，未下发或为空时保留原有值，避免切换解析商清空地区配置
        for field in self.__region_fields():
            value = arg(args, field, '')
            if value:
                data[field] = value
        if not self.store.write_json(config_path, data):
            return write_failed()
        return response_json('',200,'数据保存成功')
    #从获取域名列表
    def get_domian_list(self, args):
        if not auth(): return denied()
        domains =  self.store.read_json(self.store.path('domains.json'), {})
        data=[]
        for keys, values in domains.items():
            for key, value in values.items():
                data.append({'domain': keys, 'host': key , 'line': value})
        return response_json(data,200,'获取数据成功')
    #设置域名信息
    def set_domian_info(self, args):
        if not auth(): return denied()
        host = (arg(args,'host','') or '').strip()
        if not host:
            return response_json('',500,'主机名不能为空，请使用@创建空主机名。')
        domain = (arg(args,'domain','') or '').strip()
        if not domain:
            return response_json('',500,'域名不能为空。')
        domians_path = self.store.path('domains.json')
        domains = self.store.read_for_write(domians_path)
        if domains is None:
            return broken('domains.json')
        #线路可由前端下发，未下发时使用 lines.json 中的默认线路
        line = arg(args,'line','')
        if line:
            new_lines = [item.strip().upper() for item in str(line).split(',') if item.strip()]
        else:
            new_lines = self.__default_lines()
        if not new_lines:
            new_lines = self.__default_lines()
        if domain not in domains:
            domains[domain] = {}
        domains[domain][host] = new_lines
        if not self.store.write_json(domians_path, domains):
            return write_failed()
        return response_json('',200,'域名添加成功')
    #删除域名信息
    def del_domian_info(self, args):
        if not auth(): return denied()
        domain = arg(args,'domain','')
        host = arg(args,'host','')
        if not domain or not host:
            return response_json('',500,'域名与主机名不能为空。')
        domians_path = self.store.path('domains.json')
        domains = self.store.read_for_write(domians_path)
        if domains is None:
            return broken('domains.json')
        #未命中时直接返回，不做无谓的写入
        if domain not in domains or host not in domains[domain]:
            return response_json('',500,'未找到该域名记录，可能已被删除。')
        del domains[domain][host]
        if not domains[domain]:
            del domains[domain]
        if not self.store.write_json(domians_path, domains):
            return write_failed()
        return response_json('',200,'域名删除成功')

    #获取数据服务信息，同时下发可选优选接口清单
    def get_data_server(self, args):
        if not auth(): return denied()
        data =  self.store.read_json(self.store.path('config.json'), {})
        providers = [
            {'id': item['id'], 'name': item['name']}
            for item in self.store.read_json(self.store.path('data_provider.json','provider.json'), [])
            if not item.get('disabled')
        ]
        result = {'config': data, 'providers': providers}
        return response_json(result,200,'获取数据成功')

    #设置数据服务信息
    def set_data_server(self, args):
        if not auth(): return denied()
        config_path = self.store.path('config.json')
        data = self.store.read_for_write(config_path)
        if data is None:
            return broken('config.json')
        data['key'] = (arg(args,'key','') or '').strip()
        data['data_server'] = int_arg(args,'data_server', data.get('data_server',1))
        if not self.store.write_json(config_path, data):
            return write_failed()
        return response_json('',200,'数据保存成功')

    #更新授权积分
    def update_integral(self, args):
        if not auth(): return denied()
        config_path = self.store.path('config.json')
        data = self.store.read_for_write(config_path)
        if data is None:
            return broken('config.json')
        #查询页面上当前填写的 KEY 与接口，未下发时才回落到已保存的值 ——
        #否则用户粘贴新 KEY 点"更新积分"，查的其实是旧 KEY，会误判新 KEY 有效
        key = (arg(args,'key','') or '').strip() or data.get("key","")
        data_server = int_arg(args,'data_server', data.get('data_server',1))
        provider_data = self.store.read_json(self.store.path('data_provider.json','provider.json'), [])
        matched = [item for item in provider_data if item['id'] == data_server]
        if not matched:
            return response_json('',500,'未找到对应的数据接口配置')
        provider = matched[0]
        if not provider.get('get_license_url'):
            return response_json('',500,'该数据接口不支持查询积分')
        try:
            headers = {'Content-Type': 'application/json'}
            #必须带超时：面板同步请求里卡住会一直占着工作线程
            status, res = base.http_json(
                'GET', provider['get_license_url']+key, headers=headers, timeout=(5,10))
            if status != 200:
                return response_json('',500,'获取积分失败，接口返回状态码 ' + str(status))
            integral = int(res['count'])
        except Exception as e:
            return response_json('',500,'获取积分失败：' + str(e))
        data['integral'] = integral
        if not self.store.write_json(config_path, data):
            return write_failed()
        #把积分回传给前端，页面直接更新数字，不必重新加载整页（重载会抹掉用户未保存的输入）
        return response_json({'integral': integral},200,'积分更新成功')

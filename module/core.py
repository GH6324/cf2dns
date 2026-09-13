#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cf2dns 引擎核心 —— 全项目唯一一份。

改造前 get_optimization_ip / changeDNS / main 在三个入口脚本里逐行重复，已经产生实际漂移
（cfips 空指针只在 actions 版修对）。现在只剩 cf2dns.py 一个入口，负责「取配置 + 选日志出口
+ 调 run()」，部署形态的差异全在它那边。

日志对象只需实现 info(message) / error(message)：
  - 文件形态传 module.log.Logger(...).logger
  - Actions 形态传 module.log.RedactingLogger(PrintLogger(), 敏感串)
core 不判断部署形态，也不该绕过 logger 直接 print —— 那样会绕过 Actions 的日志脱敏。
"""

import json
import random
import time
import traceback

from .dnsapi import base, create_client

#线路码 → 中文线路名。CM:移动 CU:联通 CT:电信 AB:境外 DEF:默认
LINES = {"CM": "移动", "CU": "联通", "CT": "电信", "AB": "境外", "DEF": "默认"}


def _now():
    return str(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))


class Engine:
    def __init__(self, config, domains, provider_data, logger):
        self.config = config
        self.domains = domains or {}
        self.provider_data = provider_data or []
        self.logger = logger

    #------------------------------------------------------------------ 入口

    def run(self, startup_delay=False):
        """按配置跑一遍：ipv4 与 ipv6 各一轮（都开会请求两次接口、消耗双倍积分）。

        startup_delay 为 True 时先随机等待，避免所有用户的计划任务在同一分钟打到优选接口。
        """
        if startup_delay:
            # 生成随机时间，范围在 10 到 100 秒之间
            random_time = random.uniform(10, 100)
            print("本次将等待{}秒执行".format(random_time))
            # 延迟执行随机时间
            time.sleep(random_time)

        #配置缺字段 / 密钥没填时，原来会在模块顶层抛异常且进不了日志
        try:
            cloud = create_client(self.config)
        except Exception as e:
            self.logger.error("INIT DNS CLIENT ERROR: ----Time: " + _now() + "----MESSAGE: " + str(e))
            return

        if self.config.get("ipv4") == "on":
            self._sync(cloud, "v4")
        if self.config.get("ipv6") == "on":
            self._sync(cloud, "v6")

    #------------------------------------------------------------------ 优选 IP

    def _get_optimization_ip(self, iptype):
        try:
            data_server = self.config.get("data_server")
            provider = [item for item in self.provider_data if item['id'] == data_server]
            if not provider:
                self.logger.error("CHANGE OPTIMIZATION IP ERROR: ----Time: " + _now()
                                  + "----MESSAGE: 未找到 id=" + str(data_server) + " 的优选接口配置")
                return None

            headers = {'Content-Type': 'application/json'}
            data = {"key": self.config.get("key", ""), "type": iptype}
            #必须带超时：接口卡住会让计划任务一直挂着
            status, body = base.http_json(
                'POST', provider[0]['get_ip_url'], headers=headers, body=json.dumps(data))
            if status == 200:
                return body
            self.logger.error("CHANGE OPTIMIZATION IP ERROR: ----Time: " + _now()
                              + "----MESSAGE: REQUEST STATUS CODE IS NOT 200")
            return None
        except Exception as e:
            self.logger.error("CHANGE OPTIMIZATION IP ERROR: ----Time: " + _now() + "----MESSAGE: " + str(e))
            return None

    #------------------------------------------------------------------ 主流程

    def _sync(self, cloud, iptype):
        if iptype == 'v6':
            record_type = "AAAA"
        else:
            record_type = "A"

        if len(self.domains) == 0:
            return

        dns_server = self.config.get("dns_server")
        try:
            cfips = self._get_optimization_ip(iptype)
            #cfips 为 None 时不能再去取 cfips["info"]，否则抛 TypeError 被外层吞掉，
            #日志只剩含糊的 "CHANGE DNS ERROR"
            if cfips is None or cfips.get("code") != 200:
                detail = cfips.get("info") if isinstance(cfips, dict) else "接口无响应或返回格式异常"
                self.logger.error("GET CLOUDFLARE IP ERROR: ----Time: " + _now() + "----MESSAGE: " + str(detail))
                return

            cf_cmips = cfips["info"]["CM"]
            cf_cuips = cfips["info"]["CU"]
            cf_ctips = cfips["info"]["CT"]

            for domain, sub_domains in self.domains.items():
                for sub_domain, lines in sub_domains.items():
                    temp_cf_cmips = cf_cmips.copy()
                    temp_cf_cuips = cf_cuips.copy()
                    temp_cf_ctips = cf_ctips.copy()
                    #优选接口只返回三网，AB/DEF 复用电信数据
                    temp_cf_abips = cf_ctips.copy()
                    temp_cf_defips = cf_ctips.copy()

                    if dns_server == 1:
                        self._clean_cname(cloud, domain, sub_domain)

                    ret = cloud.get_record(domain, 100, sub_domain, record_type)
                    if dns_server != 1 and ret.get("code") != 0:
                        #非 DNSPod 解析商原来不校验返回码，失败时会拿着空列表继续跑，
                        #把「查询失败」误当成「一条记录都没有」进而重复创建
                        self.logger.error("GET DNS RECORD ERROR: ----Time: " + _now()
                                          + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain
                                          + "----MESSAGE: " + str(ret.get("message", "")))
                        continue
                    if dns_server != 1 or ret["code"] == 0:
                        #免费版最多两条记录。affect_num 取本域名的局部副本 ——
                        #原来直接改 config["affect_num"]，会连累同次运行的后续所有域名
                        affect_num = int(self.config.get("affect_num", 2))
                        if dns_server == 1 and "Free" in ret["data"]["domain"]["grade"] and affect_num > 2:
                            affect_num = 2

                        cm_info = []
                        cu_info = []
                        ct_info = []
                        ab_info = []
                        def_info = []
                        for record in ret["data"]["records"]:
                            info = {}
                            info["recordId"] = record["id"]
                            info["value"] = record["value"]
                            if record["line"] == "移动":
                                cm_info.append(info)
                            elif record["line"] == "联通":
                                cu_info.append(info)
                            elif record["line"] == "电信":
                                ct_info.append(info)
                            elif record["line"] == "境外":
                                ab_info.append(info)
                            elif record["line"] == "默认":
                                def_info.append(info)

                        buckets = {
                            "CM": (cm_info, temp_cf_cmips),
                            "CU": (cu_info, temp_cf_cuips),
                            "CT": (ct_info, temp_cf_ctips),
                            "AB": (ab_info, temp_cf_abips),
                            "DEF": (def_info, temp_cf_defips),
                        }
                        for line in lines:
                            if line in buckets:
                                s_info, c_info = buckets[line]
                                self._change_dns(line, s_info, c_info, domain, sub_domain,
                                                 cloud, iptype, affect_num)
        except Exception as e:
            #traceback 走 logger 而不是 print_exc：后者直接打 stderr，既进不了 cf2dns.log，
            #也绕过 Actions 形态的日志脱敏
            self.logger.error("CHANGE DNS ERROR: ----Time: " + _now() + "----MESSAGE: " + str(e)
                              + "\n" + traceback.format_exc())

    def _clean_cname(self, cloud, domain, sub_domain):
        """DNSPod：同名的三网 CNAME 记录会与 A/AAAA 冲突，先清掉"""
        ret = cloud.get_record(domain, 20, sub_domain, "CNAME")
        if ret["code"] != 0:
            return
        for record in ret["data"]["records"]:
            if record["line"] == "移动" or record["line"] == "联通" or record["line"] == "电信":
                retMsg = cloud.del_record(domain, record["id"])
                if(retMsg["code"] == 0):
                    self.logger.info("DELETE DNS SUCCESS: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+record["line"] )
                else:
                    self.logger.error("DELETE DNS ERROR: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+record["line"] + "----MESSAGE: " + retMsg["message"] )

    #------------------------------------------------------------------ 单条线路的增改

    def _change_dns(self, line, s_info, c_info, domain, sub_domain, cloud, iptype, affect_num):
        if iptype == 'v6':
            recordType = "AAAA"
        else:
            recordType = "A"

        line = LINES[line]
        dns_server = self.config.get("dns_server")
        ttl = self.config.get("ttl", 600)

        try:
            create_num = affect_num - len(s_info)
            if create_num == 0:
                for info in s_info:
                    if len(c_info) == 0:
                        break
                    cf_ip = c_info.pop(random.randint(0,len(c_info)-1))["ip"]
                    if cf_ip in str(s_info):
                        continue
                    ret = cloud.change_record(domain, info["recordId"], sub_domain, cf_ip, recordType, line, ttl)
                    if(dns_server != 1 or ret["code"] == 0):
                        self.logger.info("CHANGE DNS SUCCESS: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----RECORDID: " + str(info["recordId"]) + "----VALUE: " + cf_ip )
                    else:
                        self.logger.error("CHANGE DNS ERROR: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----RECORDID: " + str(info["recordId"]) + "----VALUE: " + cf_ip + "----MESSAGE: " + ret["message"] )
            elif create_num > 0:
                for i in range(create_num):
                    if len(c_info) == 0:
                        break
                    cf_ip = c_info.pop(random.randint(0,len(c_info)-1))["ip"]
                    if cf_ip in str(s_info):
                        continue
                    ret = cloud.create_record(domain, sub_domain, cf_ip, recordType, line, ttl)
                    if(dns_server != 1 or ret["code"] == 0):
                        self.logger.info("CREATE DNS SUCCESS: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----VALUE: " + cf_ip )
                    else:
                        #原来这里写的是 info["recordId"]，但本分支是新建、循环变量是 i，
                        #没有 info 可言 —— 触发时会抛 NameError
                        self.logger.error("CREATE DNS ERROR: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----VALUE: " + cf_ip + "----MESSAGE: " + ret["message"] )
            else:
                for info in s_info:
                    if create_num == 0 or len(c_info) == 0:
                        break
                    cf_ip = c_info.pop(random.randint(0,len(c_info)-1))["ip"]
                    if cf_ip in str(s_info):
                        create_num += 1
                        continue
                    ret = cloud.change_record(domain, info["recordId"], sub_domain, cf_ip, recordType, line, ttl)
                    if(dns_server != 1 or ret["code"] == 0):
                        self.logger.info("CHANGE DNS SUCCESS: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----RECORDID: " + str(info["recordId"]) + "----VALUE: " + cf_ip )
                    else:
                        self.logger.error("CHANGE DNS ERROR: ----Time: " + _now() + "----DOMAIN: " + domain + "----SUBDOMAIN: " + sub_domain + "----RECORDLINE: "+line+"----RECORDID: " + str(info["recordId"]) + "----VALUE: " + cf_ip + "----MESSAGE: " + ret["message"] )
                    create_num += 1
        except Exception as e:
            self.logger.error("CHANGE DNS ERROR: ----Time: " + _now() + "----MESSAGE: " + str(e))

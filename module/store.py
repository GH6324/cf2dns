#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置文件定位与 JSON 读写 —— 全项目唯一一份。

改造前 config_file() 在 cf2dns.py / cf2dns_global.py / cf2dns_main.py 各有一份实现（共三处），
路径规则一旦改动容易漏改，出现「界面写 config/config.json、执行脚本仍读根目录 config.json」的分裂。

本模块不依赖宝塔的 public 模块：文件 IO 全走标准库，宝塔 / aaPanel / 独立部署行为一致。
"""

import json
import os


class Store:
    """按插件根目录定位配置文件并读写 JSON。"""

    def __init__(self, base_dir):
        #插件根目录（绝对路径）
        self.base_dir = base_dir
        self.config_dir = os.path.join(base_dir, 'config')

    def path(self, name, legacy_name=None):
        """配置文件路径解析。

        config/ 下有就用它 → 否则回退插件根目录（V1.15 之前的位置，legacy_name 用于改过名的
        文件）→ 都没有时返回 config/ 路径作为新建落点。

        读和写都必须走这里，否则会出现界面写 config/config.json、执行脚本仍读根目录
        config.json 的分裂情况。
        """
        new_path = os.path.join(self.config_dir, name)
        if os.path.exists(new_path):
            return new_path
        old_path = os.path.join(self.base_dir, legacy_name or name)
        if os.path.exists(old_path):
            return old_path
        return new_path

    def read_text(self, path):
        """读文本，UTF-8 优先、失败回退 GBK。

        复刻原 public.readFile / 独立版 readFile 的编码兜底：老配置可能是 GBK 存的。
        读不到（不存在或无权限）返回 None。
        """
        if not os.path.exists(path):
            return None
        for encoding in ('utf-8', 'gbk'):
            try:
                with open(path, 'r', encoding=encoding) as fp:
                    return fp.read()
            except UnicodeDecodeError:
                continue
            except Exception:
                return None
        return None

    def read_json(self, path, default=None):
        """读 JSON 数据文件，文件缺失或内容损坏时返回 default，避免接口直接 500。"""
        try:
            content = self.read_text(path)
            if not content or not content.strip():
                return default
            return json.loads(content)
        except Exception:
            return default

    def read_for_write(self, path):
        """写入前读取：文件存在但解析失败时返回 None，调用方据此拒绝写入。

        不能复用 read_json —— 它把损坏文件也当成空字典返回，写回去等于把用户配置删成
        只剩本次提交的几个字段。
        """
        if not os.path.exists(path):
            return {}
        content = self.read_text(path)
        if content is None:
            return None
        if not content.strip():
            return {}
        try:
            return json.loads(content)
        except Exception:
            return None

    def write_json(self, path, data):
        """写 JSON 数据文件，成功返回 True。

        config/ 可能不存在（升级时 install.sh 未执行），先建目录。
        写失败返回 False，调用方必须检查返回值，否则会给用户误报"保存成功"。
        """
        try:
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            with open(path, 'w', encoding='utf-8') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

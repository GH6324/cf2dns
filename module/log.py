import logging
import os
from logging import handlers

class Logger(object):
    level_relations = {
        'debug':logging.DEBUG,
        'info':logging.INFO,
        'warning':logging.WARNING,
        'error':logging.ERROR,
        'crit':logging.CRITICAL
    }#日志级别关系映射

    def __init__(self,filename,level='info',when='D',backCount=3,fmt='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s'):
        self.logger = logging.getLogger(filename)
        format_str = logging.Formatter(fmt)#设置日志格式
        self.logger.setLevel(self.level_relations.get(level))#设置日志级别
        sh = logging.StreamHandler()#往屏幕上输出
        sh.setFormatter(format_str) #设置屏幕上显示的格式
        th = handlers.TimedRotatingFileHandler(filename=filename,when=when,backupCount=backCount,encoding='utf-8')#往文件里写入#指定间隔时间自动生成文件的处理器
        #实例化TimedRotatingFileHandler
        #interval是时间间隔，backupCount是备份文件的个数，如果超过这个个数，就会自动删除，when是间隔的时间单位，单位有以下几种：
        # S 秒
        # M 分
        # H 小时、
        # D 天、
        # W 每星期（interval==0时代表星期一）
        # midnight 每天凌晨
        th.setFormatter(format_str)#设置文件里写入的格式
        self.logger.addHandler(sh) #把对象加到logger里
        self.logger.addHandler(th)


class PrintLogger(object):
    """把日志直接打到标准输出，供 GitHub Actions 形态使用。

    只实现 core.Engine 用到的 info / error，方法名与 logging.Logger 一致，
    这样 core.py 面对的始终是同一个日志接口，不必判断部署形态。
    """

    def info(self, message):
        print(message)

    def error(self, message):
        print(message)


class RedactingLogger(object):
    """把敏感串换成 *** 再转发给目标日志。

    给 GitHub Actions 形态用：公开仓库的 workflow 日志人人可读，而 Actions 只屏蔽 Secret
    的完整值 —— 从 DOMAINS 那份 JSON 里拆出来的单个域名不在屏蔽范围内，引擎每处理一条记录
    就打一行「DOMAIN: xxx----SUBDOMAIN: yyy」，等于把域名清单贴到公网。

    只实现 core.Engine 用到的 info / error，与 PrintLogger 保持同一套接口。
    只替换值、不吞行：出错时仍要看得见是哪类错误。
    """

    MASK = '***'

    def __init__(self, target, values):
        self.target = target
        #长串先替换：先换短的会把 a.example.com 削成 a.***，子域名反而漏了
        self.values = sorted({str(v) for v in values if v}, key=len, reverse=True)

    def scrub(self, message):
        text = str(message)
        for value in self.values:
            text = text.replace(value, self.MASK)
        return text

    def info(self, message):
        self.target.info(self.scrub(message))

    def error(self, message):
        self.target.error(self.scrub(message))


def github_add_mask(values):
    """把敏感值注册给 GitHub Actions 屏蔽（::add-mask::）。

    比 RedactingLogger 更彻底：注册之后 GitHub 会屏蔽此后**任何**输出里的该串，包括
    core 里 traceback 的内容和厂商报错原文 —— 这些不一定经过我们的 logger。

    只在真跑在 Actions 里时才发：否则本地终端会白打一堆 ::add-mask:: 噪音，
    反倒把值本身显示出来。
    """
    if not os.environ.get('GITHUB_ACTIONS'):
        return
    for value in values:
        #workflow 命令的数据段必须转义这三个字符，否则会被当成命令分隔符
        safe = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        if safe:
            print('::add-mask::' + safe)


if __name__ == '__main__':
    log = Logger('monitor.log',level='debug')
    log.logger.debug('debug')
    log.logger.info('info')
    log.logger.warning('警告')
    log.logger.error('报错')
    log.logger.critical('严重')
    Logger('error.log', level='error').logger.error('error')

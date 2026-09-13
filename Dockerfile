# cf2dns 容器镜像 —— 第四种部署形态，不引入新的运行形态。
#
# 容器里跑的还是那个 cf2dns.py：挂载 ./config 就是「文件形态」，设 CONFIG+DOMAINS
# 环境变量就被 use_env() 判成「环境变量形态」（日志自动脱敏）。定时由
# docker/entrypoint.sh 的循环负责，见那里的注释。
#
# alpine 够用：插件对第三方包零依赖（requirements.txt 是空的），不需要 slim 的编译链。

FROM python:3.12-alpine

# 日志时间戳走 time.localtime()（module/core.py 的 _now），alpine 默认没有时区库，
# 不装 tzdata 的话 TZ 设了也没用、时间会显示成 UTC
RUN apk add --no-cache tzdata

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 逐个 COPY 而不是 COPY . /app：
#   - 面板专属文件（index.html、static/、cf2dns_main.py、install.sh、info.json）在容器里
#     没有意义，cf2dns_main.py 还依赖面板会话鉴权
#   - 更重要的是别把 config/config.json、config/domains.json 烧进镜像层 —— 那是用户数据，
#     本地工作副本里就有真密钥。.dockerignore 是第二道防线，两道都要有
COPY cf2dns.py ./
COPY module/ ./module/

# 随镜像分发的 JSON 放 defaults/ 而不是 config/：用户挂载 ./config:/app/config 会把
# config/ 整个遮住，data_provider.json 一读不到，cf2dns.py 就以「读取优选接口配置失败」
# 提前退出。entrypoint 启动时从 defaults/ 往 config/ 补齐缺失项（已存在的不动）。
# 新增随包 JSON 时这里与 entrypoint 的 PACKAGED_FILES 必须同步加
COPY config/data_provider.json config/dns_provider.json config/lines.json \
     config/about.json config/default_config.json config/default_domains.json \
     ./defaults/

COPY docker/entrypoint.sh ./docker/entrypoint.sh

# 默认以 root 跑，不建非 root 用户。理由是挂载：宿主机的 ./config 若由 docker 代建、
# 或用户本来就是 root，目录属主就是 root —— 换成 uid 1000 的话第一次启动就写不进配置模板，
# 而这是 compose 里默认的那条路径。想收紧权限的在 compose 里加 user: "1000:1000"，
# 并把宿主机的 config 目录 chown 成同一个 uid。
# （另外文件形态的 Logger 在构造时就要打开 cf2dns.log，/app 不可写会直接抛 PermissionError）
RUN chmod +x ./docker/entrypoint.sh

VOLUME ["/app/config"]

# 心跳判活：entrypoint 每轮结束 touch 一次，超过两个间隔没动静就说明轮转已经停了，
# 让「容器还活着但实际不干活」在 docker ps 的 STATUS 里看得见。
# 一次性模式（RUN_INTERVAL=0）跑完就退出，健康检查无从谈起，直接算健康。
#
# 用 python 而不是 find -newermt：后者是 GNU 扩展，alpine 的 busybox find 不认，
# 会让健康检查恒为 unhealthy。python 本来就在镜像里，还省了单位换算
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import os,sys,time;i=int(os.environ.get('RUN_INTERVAL',900));sys.exit(0 if i==0 else (0 if time.time()-os.path.getmtime('/app/.heartbeat')<i*2+120 else 1))"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]

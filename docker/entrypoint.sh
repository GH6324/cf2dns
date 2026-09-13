#!/bin/sh
# cf2dns 容器入口（PID 1）—— 负责两件事：补齐配置目录、按间隔反复调 cf2dns.py。
#
# 为什么不用 cron：
#   引擎单轮耗时已有硬上限（module/dnsapi/base.py 的 DEFAULT_TIMEOUT，所有云端请求都带
#   超时），异常也被 core 里的 try/except 兜住，所以「卡死」不是这里要解决的问题。cron
#   唯一的额外好处是进程隔离，而每轮 fork 一个全新 python 同样能拿到。反过来 busybox
#   crond 不继承容器环境变量 —— 用 CONFIG/DOMAINS 喂配置时得把含密钥的 JSON dump 成
#   文件再 source，日志还要额外转发到 stdout。
#
# 环境变量：
#   RUN_INTERVAL   两轮之间等待的秒数，默认 900（项目建议频率 ≥15 分钟）
#                  设 0 表示跑一次就退出，给 k8s CronJob / 宿主机 cron 复用同一个镜像
#   RUN_TIMEOUT    单轮的兜底超时秒数，默认 600。仅防御用，正常远达不到
#   CF2DNS_ARGS    透传给 cf2dns.py 的参数，默认空（让 use_env() 自动判定形态）
#                  填 --env 可强制环境变量形态，日志会脱敏
#   CONFIG_DIR     配置目录，默认 /app/config
#   DEFAULTS_DIR   随镜像分发的 JSON 所在目录，默认 /app/defaults
#   APP_DIR        cf2dns.py 所在目录，默认 /app
#
# 变量都留了覆盖入口是为了能在宿主机上离线自测（tests/docker_selftest.py），
# 不必真的 build 镜像。

set -u

APP_DIR="${APP_DIR:-/app}"
CONFIG_DIR="${CONFIG_DIR:-$APP_DIR/config}"
DEFAULTS_DIR="${DEFAULTS_DIR:-$APP_DIR/defaults}"
HEARTBEAT="${HEARTBEAT:-$APP_DIR/.heartbeat}"
RUN_INTERVAL="${RUN_INTERVAL:-900}"
RUN_TIMEOUT="${RUN_TIMEOUT:-600}"
CF2DNS_ARGS="${CF2DNS_ARGS:-}"
PYTHON_BIN="${PYTHON_BIN:-python}"

log() {
    echo "[entrypoint] $*"
}

# ---------------------------------------------------------------- 配置目录补齐

# 随镜像分发的 JSON（非用户数据）。挂载 ./config:/app/config 会把镜像里的 config/
# 整个遮住，data_provider.json 一旦读不到，cf2dns.py 就以「读取优选接口配置失败」提前
# 退出 —— 所以镜像把它们放在 defaults/，启动时往 CONFIG_DIR 里补。
#
# 新增随包分发的 config/*.json 时必须同步加进这个列表与 Dockerfile 的 COPY，
# 否则挂载了目录的容器读不到它。
PACKAGED_FILES='data_provider.json dns_provider.json lines.json about.json default_config.json default_domains.json'

seed_config() {
    # 补齐失败不算致命：全用环境变量（CONFIG + DOMAINS + PROVIDER）时根本不需要配置目录。
    # 真缺配置的话 cf2dns.py 自己会打出更准确的原因，这里不抢着退出
    if ! mkdir -p "$CONFIG_DIR" 2>/dev/null; then
        log "无法创建配置目录 $CONFIG_DIR（挂载目录权限？），跳过补齐"
        return 0
    fi

    # 已存在的一律不动：这些文件用户可能改过（比如往 data_provider.json 里加自定义优选源）
    for name in $PACKAGED_FILES; do
        if [ ! -f "$CONFIG_DIR/$name" ] && [ -f "$DEFAULTS_DIR/$name" ]; then
            cp "$DEFAULTS_DIR/$name" "$CONFIG_DIR/$name" && log "已补齐 config/$name"
        fi
    done

    seeded=''
    if [ ! -f "$CONFIG_DIR/config.json" ] && [ -f "$DEFAULTS_DIR/default_config.json" ]; then
        cp "$DEFAULTS_DIR/default_config.json" "$CONFIG_DIR/config.json"
        seeded='yes'
    fi
    if [ ! -f "$CONFIG_DIR/domains.json" ]; then
        # 不能拿 default_domains.json 当模板：那里预置的是上游作者的域名
        # （gacjie.cn / baota.me），容器用户不该莫名去动别人的解析记录
        echo '{}' > "$CONFIG_DIR/domains.json"
        seeded='yes'
    fi

    if [ -n "$seeded" ]; then
        log "首次启动已生成配置模板，请编辑 config/config.json 与 config/domains.json 后重启容器"
    fi
    return 0
}

# ---------------------------------------------------------------- 主循环

stop=''
# 收到信号只置标记，不立刻 exit：正在跑的那一轮让它自己收尾，避免解析改到一半被打断
on_signal() {
    stop='yes'
    log "收到停止信号，本轮结束后退出"
}
trap on_signal TERM INT

run_once() {
    # 每轮都是全新进程：上一轮无论卡死还是崩溃都影响不到下一轮（cron 的隔离性）。
    # timeout 是兜底而非主要防线，请求本身已经带超时了。
    # $CF2DNS_ARGS 故意不加引号 —— 需要按空格拆成多个参数
    if command -v timeout >/dev/null 2>&1; then
        # shellcheck disable=SC2086
        timeout "$RUN_TIMEOUT" "$PYTHON_BIN" "$APP_DIR/cf2dns.py" $CF2DNS_ARGS
    else
        # shellcheck disable=SC2086
        "$PYTHON_BIN" "$APP_DIR/cf2dns.py" $CF2DNS_ARGS
    fi
}

main() {
    seed_config

    while : ; do
        # 单轮失败（配置缺失时 cf2dns.py 会 exit 1）不该让容器整体退出 ——
        # 用户改完挂载目录里的配置，下一轮就能自己好起来。退出码只记进日志
        run_once || log "本轮执行返回非 0（退出码 $?），等下一轮重试"

        # HEALTHCHECK 靠这个文件的 mtime 判断容器是否还在正常轮转
        touch "$HEARTBEAT" 2>/dev/null || true

        if [ -n "$stop" ]; then
            exit 0
        fi
        if [ "$RUN_INTERVAL" = 0 ]; then
            log "RUN_INTERVAL=0，单次执行完成，退出"
            exit 0
        fi

        # 必须写成 sleep & wait：裸 sleep 期间 PID 1 收不到信号，docker stop 会白等满
        # 10 秒宽限期再被 SIGKILL。wait 被信号打断后返回非 0，用 || true 吞掉
        sleep "$RUN_INTERVAL" &
        wait $! || true

        # 等待期间收到的信号必须在这里就退出。少了这一判，循环会先起新的一轮再检查，
        # 等于 docker stop 时反而开始一次全新的解析更新，然后在 10 秒宽限期结束时
        # 被 SIGKILL 打断在半路
        if [ -n "$stop" ]; then
            exit 0
        fi
    done
}

main

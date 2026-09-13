#!/bin/bash
PATH=/www/server/panel/pyenv/bin:/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#配置插件安装目录
install_path=/www/server/panel/plugin/cf2dns

#安装
Install()
{

	echo '正在安装...'
	#==================================================================
	#依赖安装开始
    btpip install -r $install_path/requirements.txt

    mkdir -p $install_path/config

    #⓪ 删除 V1.15 之前遗留在根目录的模块文件
    #  升级是覆盖式解压、不删旧文件，V1.15 起 dns/ 与 log.py 已移入 module/。
    #  残留的根目录 log.py 会在插件根目录进入 sys.path 后抢占任何 import log；
    #  dns/ 则与 dnspython 重名。两者都是随插件分发的文件（非用户数据），直接删。
    rm -rf $install_path/dns
    rm -f $install_path/log.py

    #  V1.15 的三个入口脚本已合并进 cf2dns.py（--env 切环境变量形态）。
    #  残留副本仍能跑（module/ 下的依赖都还在），只会跟新入口悄悄漂移；
    #  同属随插件分发的文件（非用户数据），直接删
    rm -f $install_path/cf2dns_global.py
    rm -f $install_path/cf2dns_actions.py

    #① 根目录有 config.json / domains.json 则移动到 config/
    #  必须排在③之前：顺序反了 config/config.json 就已存在，迁移条件永远不成立，
    #  老用户的密钥和域名列表会被一份空白默认配置顶掉
    for f in config.json domains.json
    do
        if [ -f "$install_path/$f" ] && [ ! -f "$install_path/config/$f" ]
        then
            mv "$install_path/$f" "$install_path/config/$f"
            echo "已迁移 $f -> config/$f"
        fi
    done

    #② 根目录残留的旧版随插件分发文件挪进备份目录
    #  升级是覆盖式解压不删旧文件，根目录会留下一堆过期 JSON；其中 provider.json 尤其容易
    #  误导（看着像现行配置，代码其实已读 config/data_provider.json）。但用户可能往里加过
    #  自定义优选源，所以挪走不删。备份目录只在真有残留时才创建
    for f in provider.json dns_provider.json lines.json about.json default_config.json default_domains.json
    do
        if [ -f "$install_path/$f" ]
        then
            mkdir -p "$install_path/config/old_root_backup"
            mv "$install_path/$f" "$install_path/config/old_root_backup/$f"
            echo "已备份旧文件 $f -> config/old_root_backup/$f"
        fi
    done

    #③ 首次安装时生成用户数据
    if [ ! -f "$install_path/config/config.json" ]
    then
        cp $install_path/config/default_config.json $install_path/config/config.json
    fi
    if [ ! -f "$install_path/config/domains.json" ]
    then
        cp $install_path/config/default_domains.json $install_path/config/domains.json
    fi
	#依赖安装结束
	#==================================================================
	echo '================================================'
	#bt restart
}

#卸载
Uninstall()
{
	rm -rf $install_path
}

#操作判断
if [ "${1}" == 'install' ];then
	Install
elif [ "${1}" == 'uninstall' ];then
	Uninstall
else
	echo 'Error!';
fi

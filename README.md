#### 简单介绍     
本项目已经全面重构，不在基于任何项目。    
功能上主要用于自动化将优选IP地址解析到您的域名记录中。    
支持CloudFlare、CloudFront、EdgeOne优选IPv4&IPv6地址    
支持宝塔面板、Docker、python3、GitHub-Actions四种方式部署。    
    
#### 演示图片    
 ![cf2dns.jpg](https://raw.githubusercontent.com/gacjie/cf2dns/main/cf2dns.jpg)   
        
#### 公告通知    
出于运维成本、长久稳定性等情况考虑。    
目前平台域名更换为WeTest.vip。    
请各位用户及时将插件更新到1.9版本以上。     
    
#### 接口支持    
CloudFlare官方优选(WeTest.vip)   更新频率15IP/15分钟   
CloudFlare官方优选(HostMonit.com)更新频率15IP/15分钟   
CloudFlare官方优选(Smognode1.top)更新频率15IP/15分钟   
CloudFront官方优选(WeTest.vip)   更新频率15IP/15分钟   
EdgeOne官方优选   (WeTest.vip)   更新频率15IP/15分钟   
        
#### 解析支持    
[华为云解析](https://support.huaweicloud.com/devg-apisign/api-sign-provide-aksk.html)   
[阿里云解析](https://help.aliyun.com/document_detail/53045.html?spm=a2c4g.11186623.2.11.2c6a2fbdh13O53)   
[腾讯云解析(DNSPOD)](https://console.cloud.tencent.com/cam/capi)   
[青云解析(QingCloud)](https://console.qingcloud.com/access_keys/)   
         
#### 小广告
   
[【弘速云hosuyun.com】香港、美国高性能优质线路服务器，新用户首购五折特惠。](https://www.hosuyun.com/)  
         
#### 价格计费    
插件免费提供授权码o1zrmHAF，可永久免费使用。    
[WeTest.vip付费服务说明](https://github.com/gacjie/cf2dns/wiki/WeTest付费服务说明)   
[WeTest.vip付费授权码购买](https://www.wetest.vip/dash/Account/register)   
[HostMonit.com付费授权码](https://shop.hostmonit.com/)   
          
### 注意事项     
宝塔安装时请关闭宝塔系统加固插件，会终止安装脚本的执行。     
脚本只会更新电信、移动、联通三网线路的IP，因此还需要将回退源设置到默认线路上。      
使用插件前请确保您的网站域名使用cname或saas方式接入，并且域名解析在dnspod、华为云、阿里云、青云。       
青云解析为V1.15新增，签名与接口逻辑已离线验证，但尚未实机跑过，使用后请到青云控制台核对记录。       
     
#### 使用说明   
[宝塔安装cf2dns插件](https://github.com/gacjie/cf2dns/wiki/宝塔安装cf2dns插件)   
[Docker部署运行cf2dns](https://github.com/gacjie/cf2dns/wiki/Docker部署运行cf2dns)   
[python3部署运行cf2dns_global](https://github.com/gacjie/cf2dns/wiki/python3部署运行cf2dns_global)  
[GitHub Actions 运行cf2dns_actions](https://github.com/gacjie/cf2dns/wiki/GitHub-Actions-运行cf2dns_actions)  

> 入口已合并为`cf2dns.py`一个（两种运行形态：文件 / 环境变量）：    
> 宝塔计划任务：`btpython /www/server/panel/plugin/cf2dns/cf2dns.py`    
> Docker：`docker compose up -d --build`（详见 wiki；挂载`./config`或用`CONFIG`/`DOMAINS`环境变量）    
> python3独立部署：`python3 cf2dns.py`（原`cf2dns_global.py`）    
> GitHub Actions：`python cf2dns.py --env`（原`cf2dns_actions.py`）    
> Actions只需配置`CONFIG`、`DOMAINS`两个Secret，`PROVIDER`仅在使用自定义优选源时才需要，不配则自动读取仓库内的`config/data_provider.json`。    
> Actions / Docker环境变量形态的运行日志会对域名与密钥脱敏（显示为`***`）。    
        
#### Docker部署（V1.15新增）    
镜像里跑的还是`cf2dns.py`，定时由`docker/entrypoint.sh`的循环负责：每轮起一个全新python进程，上一轮无论超时还是崩溃都影响不到下一轮。    
```bash
docker compose up -d --build     # 启动（后台常驻）
docker compose logs -f           # 看运行日志
docker compose down              # 停止
```
配置有两种喂法，任选其一：    
**方式A（默认）挂载配置目录**：首次`up`会在`./config`下生成`config.json`模板与空的`domains.json`，编辑后重启容器即可。目录结构与宝塔插件版一致，老备份可以直接拷进来用。    
**方式B 用环境变量**：把`docker-compose.yml`里的`CONFIG`、`DOMAINS`取消注释填好JSON，并注释掉`volumes`整段。适合Portainer、k8s secret这类不方便管文件的场景，日志会自动脱敏。    
可调环境变量：    
`RUN_INTERVAL`两轮间隔秒数，默认900（优选接口15分钟才更新一批IP，设更短只是白耗积分）；设`0`表示跑一次就退出，可配合宿主机cron或k8s CronJob使用    
`RUN_TIMEOUT`单轮兜底超时秒数，默认600    
`TZ`时区，默认`Asia/Shanghai`（影响日志时间戳）    
`CF2DNS_ARGS`透传给`cf2dns.py`的参数；填`--env`可让方式A的日志也脱敏    
`CF2DNS_LOG_FILE`日志落点；不设则只写容器内`/app/cf2dns.log`（重建即丢），填`/app/config/cf2dns.log`可持久化到挂载目录。`docker logs`始终能看到完整日志    
容器一轮之后`docker ps`的STATUS应变成`healthy`（靠心跳文件判断轮转是否还在继续）。    
        
#### 数据备份     
config/config.json是配置数据    
config/domains.json是域名数据    
宝塔插件、Docker、python3独立部署、GitHub Actions均可使用同一套备份。    
配置完后可以直接备份这俩数据文件，后续需要迁移可直接上传。     
V1.15起这两个文件由插件根目录移入config/目录，升级时会自动迁移，旧版备份文件仍可直接上传到config/目录使用。    
           
#### 2026年09月13日更新记录（V1.15）
**配置与目录**    
配置文件统一移入config/目录，provider.json更名为data_provider.json，升级自动迁移    
dns/与log.py移入module/目录，升级时自动清理根目录残留    

**去SDK化**    
四个云解析适配器改为标准库直连并自行签名，不再依赖腾讯云/阿里云/华为云/青云SDK    
（面板插件共用site-packages，SDK版本易被其他插件的安装升级带崩，且宝塔与aaPanel底层python版本不一致）    
requirements.txt随之清空，插件现在对第三方包零依赖    
所有云端请求增加超时，此前SDK调用无超时、接口卡住会一直占着计划任务或面板线程    

**新增青云（QingCloud）云解析**    
NS服务商下拉可直接选择，无需填写地区    
青云一条记录可挂多个IP（与另三家的"一记录一IP"模型不同），适配器做了三处对齐：    
创建走upsert（同线路第二次追加进值列表而非重复建记录）、修改每次重新读回整条记录（避免同轮两次修改互相覆盖）、    
记录值ID失效时退化为删旧建新并在日志说明原因（不静默失败）    
适配器会自动为zone启用所需解析线路，且在现有线路基础上追加，不会覆盖已配置的其它线路    

**新增Docker部署方式**    
`Dockerfile`+`docker-compose.yml`+`docker/entrypoint.sh`，`docker compose up -d --build`即可    
不新增运行形态：挂载`./config`就是文件形态，设`CONFIG`/`DOMAINS`环境变量会被自动判成环境变量形态（日志脱敏）    
定时用shell循环而非cron，每轮起全新python进程拿到与cron同等的进程隔离，同时避免cron不继承容器环境变量的问题    
`docker stop`会在当前一轮结束后立即退出，不会白等满10秒宽限期、也不会在停止时反而起新的一轮    
首次启动自动补齐随包JSON并生成配置模板，其中`domains.json`是空对象，不再预置上游作者的域名    
新增`CF2DNS_LOG_FILE`环境变量，可把文件形态的日志落到挂载目录里持久化    

**界面与入口**    
插件界面拆分为框架入口与独立子页面，修复首次进入解析配置时地区下拉不显示的问题    
三个入口脚本的重复引擎核心合并为module/core.py，入口只保留取配置与选日志出口    
更新积分改为校验界面上当前填写的KEY，失败时给出明确提示，不再误报成功    

**安全与稳定性**    
插件接口全部增加面板登录态校验，移除临时探针接口get_auth_probe，改为命令行诊断脚本tests/auth_probe.py    
GitHub Actions与Docker环境变量形态的运行日志对域名与密钥脱敏（显示为`***`）    
修复优选接口无响应时报错含糊、DNSPod免费版降级影响后续域名、新建记录失败日志崩溃等问题    
修复阿里云记录解析靠字符串替换导致的取值错乱    
修复清空数量/TTL输入框后保存报错、保存失败仍提示成功、配置文件损坏时被写入覆盖等问题    
新增离线自测脚本（签名、引擎、入口、青云、Docker），不发网络请求、不需要真密钥    

#### V1.13更新记录
版本号、解析商、地区列表、优选接口源、线路定义改为JSON数据驱动，新增接口源或解析商不再需要改动界面代码    
解析商切换时不再清空已保存的地区配置    

#### 2025年07月11日更新记录（V1.12）
新增CloudFlare官方优选(Smognode1.top)接口
   
#### 常见问题        
   
Q：为啥别人使用优选很快，我使用优选访问慢？      
A: 通常优选系统只会测用户端 - CDN节点的速度，但是节点也是要访问源站获取数据，源站与节点链接不稳定也会导致整体访问慢。   
A：建议增加缓存或有条件更换国际线路较好的源站服务器来优化链接速度。   
      
Q：为什么不支持反代优选？      
A：本项目是为了建站而开发，反代优选IP为扫描的第三方的服务器，存在不可控的安全隐患。   
A：目前已有因使用反代优选导致域名被注册机构禁用的先例。      
A：因此本项目未来也不会提供反代优选，除非您自行添加相关接口。       
         
Q：为什么不支持海外dns解析运营商？        
A：由于cf等cdn属于泛播，移动联通电信需要单独解析，才能实现三网优选。海外dns均不支持国内三网线路解析。      
A：如不方便使用国内云解析 可以访问 https://www.WeTest.vip 获取公共cname地址使用。       
     
Q：该插件安全吗？      
A：插件是基于cf2dns增加了宝塔可视化操作界面。并且代码全部公开在github上面，可先自行审查代码再决定是否安装。      
      
Q：为什么不做成其他面板的插件？      
A：由于cf2dns源代码是基于python3编写的，而宝塔面板的运行环境也是python3，所以可以很方便的写成插件，不需要考虑python3环境问题。       

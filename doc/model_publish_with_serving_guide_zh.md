# FATE模型发布及在线联邦推理指南

# 1. 概述

1.1 高可用的在线联邦推理服务由FederatedAI子项目FATE-Serving提供，代码仓库：https://github.com/FederatedAI/FATE-Serving

1.2 使用FATE-Flow命令行发布模型到在线推理服务

1.3 联邦在线推理服务支持HTTP/GRPC在线推理接口

# 2. 集群部署

离线训练集群(FATE)，请参考：https://github.com/FederatedAI/FATE/tree/master/cluster-deploy/doc

在线推理集群(FATE-Serving)，请参考：https://github.com/FederatedAI/FATE-Serving/wiki

# 3. 离线集群与在线集群链路配置(两种不同模式)

配置文件: conf/service_conf.yaml

3.1 在线集群不使用zookeeper模式

**1) 修改服务配置**

- 填入实际serving-server服务的ip:port，如：

```yaml
servings:
  hosts:
    - 192.168.0.1:8000
    - 192.168.0.2:8000
```

**2) 服务生效**

- 参考上述离线训练集群部署文档，重启FATE-Flow服务

3.2 在线集群使用zookeeper的模式

**1) 修改服务配置**

其中``zookeeper:hosts``填入在线推理集群实际部署Zookeeper的ip:port

- 若zookeeper开启了ACL，则需要修改``use_acl`` ``user`` ``password``，否则略过

```yaml
use_registry: true
zookeeper:
  hosts:
    - 192.168.0.1:2181
    - 192.168.0.2:2181
  use_acl: true
  user: fate_dev
  password: fate_dev
```

**2) 服务生效**

- 参考上述离线训练集群部署文档，重启FATE-Flow服务

# 4. 推送模型

复制修改FATE源码目录或者部署目录下fate_flow/examples/publish_load_model.json，生成对应模型的*推送模型配置*
改配置如下：

```json
{
    "initiator": {
        "party_id": "10000",
        "role": "guest"
    },
    "role": {
        "guest": ["10000"],
        "host": ["10000"],
        "arbiter": ["10000"]
    },
    "job_parameters": {
        "work_mode": 1,
        "model_id": "arbiter-10000#guest-9999#host-10000#model",
        "model_version": "202006122116502527621"
    }
}
```

所有参数均要根据实际情况填入，特别注意work_mode，分布式集群为1，单机为0。serving服务将从FATE Flow下载模型。默认情况下，serving服务下载模型的地址如下："http：// {FATE_FLOW_IP}：{FATE_FLOW_HTTP_PORT} {FATE_FLOW_MODEL_TRANSFER_ENDPOINT}"。用户也可以把job_parameters['use_transfer_url_on_serving']设置成"true"，serving服务将通过serving-server.properties中的`model.transfer.url`中定义的地址来下载模型。
执行命令：

```bash
python fate_flow_client.py -f load -c examples/publish_load_model.json
```

# 5. 发布模型

复制修改FATE源码目录或者部署目录下fate_flow/examples/bind_model_service.json，生成对应模型的*发布模型配置*
改配置如下：

```json
{
    "service_id": "",
    "initiator": {
        "party_id": "10000",
        "role": "guest"
    },
    "role": {
        "guest": ["10000"],
        "host": ["10000"],
        "arbiter": ["10000"]
    },
    "job_parameters": {
        "work_mode": 1,
        "model_id": "arbiter-10000#guest-10000#host-10000#model",
        "model_version": "2019081217340125761469"
    },
    "servings": [
    ]
}
```

除了``servings``参数非必填，所有参数均要根据实际情况填入，特别注意work_mode，分布式集群为1，单机为0

当``servings``参数为空，则发布到所有serving-server实例

若``servings``参数不为空，则发布到所配置的serving-server实例

执行命令：

```bash
python fate_flow_client.py -f bind -c examples/bind_model_service.json
```

# 6. 在线推理测试

参考[FATE在线推理接口文档](https://github.com/FederatedAI/FATE-Serving/wiki/%E5%9C%A8%E7%BA%BF%E6%8E%A8%E7%90%86%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E)
需要填入上述第5步，发布模型时使用的``service_id``

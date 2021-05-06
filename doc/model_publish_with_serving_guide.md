# Guide to FATE Model Publishing & Federated Online Inference

# 1. Overview

1.1 Highly usable Federated Online Inference service is provided by FATE-Serving, a sub-project of FederatedAI, repository: https://github.com/FederatedAI/FATE-Serving

1.2 Use FATE-Flow command line to publish model to online inference service

1.3 Federated Online Inference service support HTTP/GRPC online inference API

# 2. Cluster Deploy

Offline Cluster for Training(FATE), please refer to: https://github.com/FederatedAI/FATE/tree/master/cluster-deploy/doc

Online Cluster for Inference(FATE-Serving)，please refer to: https://github.com/FederatedAI/FATE-Serving/wiki

# 3. Configuration of Offline Cluster & Online Cluster with/without ZooKeeper (two different modes)

configuration: conf/service_conf.yaml

3.1 Online cluster without ZooKeeper mode

**1) Modify Service Configuration**

- Fill in ``servings:hosts`` with actual ip:port of serving-server service, for example:

```yaml
servings:
  hosts:
    - 192.168.0.1:8000
    - 192.168.0.2:8000
```

**2) Running Service**

- Refer to the deploy document on offline cluster for training to restart FATE-Flow service

3.2 Online cluster with ZooKeeper mode:

**1) Modify Service Configuration**

Fill in ``zookeeper:hosts`` with actual ip:port of ZooKeeper of online inference cluster

- If ZooKeeper uses ACL, modify ``use_acl`` ``user`` ``password``; otherwise, skip the following step:

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

**2) Running Service**

- Refer to the deploy document on offline cluster for training to restart FATE-Flow service

# 4. Load Model

Copy and modify configuration file fate_flow/examples/publish_load_model.json under deploy directory, which is used to generate *load configuration* for corresponding model
Example of modified configuration:

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

All parameters should be filled in according to actual setting. 
User should pay special attention to work_mode, for which 1 indicates cluster mode, and 0 indicates standalone mode. The serving server will load model from the fate flow service. By default, the address for serving server to load model is formatted as follows: 'http://{FATE_FLOW_IP}:{FATE_FLOW_HTTP_PORT}{FATE_FLOW_MODEL_TRANSFER_ENDPOINT}'. To load model with `model.transfer.url` defined in serving-server.properties, a user can set job_parameters['use_transfer_url_on_serving'] to `true`.

Run command:

```bash
python fate_flow_client.py -f load -c examples/publish_load_model.json
```

# 5. Publish Model

Copy and modify configuration file fate_flow/examples/bind_model_service.json under deploy directory, which is used to generate *bind configuration* for corresponding model
Example of modified configuration:

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

Except for optional parameter ``servings``, all parameters should be filled in according to actual setting. 
User should pay special attention to work_mode, for which 1 indicates cluster mode, and 0 indicates standalone mode. 

If parameter ``servings`` is unfilled, model will be published to all serving-server instances

If ``servings`` is filled, model will only be published to specified serving-server instance(s)

Run command:

```bash
python fate_flow_client.py -f bind -c examples/bind_model_service.json
```

# 6. Testing Online Inference

Please refer to [FATE-Serving document](https://github.com/FederatedAI/FATE-Serving/wiki/%E5%9C%A8%E7%BA%BF%E6%8E%A8%E7%90%86%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E)
Fill in parameter ``service_id`` according to step 5 above. 
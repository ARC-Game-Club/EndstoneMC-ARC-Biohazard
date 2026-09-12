# 生化危机（endstone-biohazard）

[Endstone](https://endstone.dev) Python 插件：**丧尸（`zombie:zombie_*`）杀死生物后，在死者位置生成一只新的丧尸**，即"感染扩散"。

## 转化规则（默认配置）

1. 只处理击杀者实体 ID 命中 `zombie:zombie_*` 的死亡事件（`killer_patterns`）。
2. 按死者的类型选择随机池：
   - **人形生物**（村民、猪灵、灾厄村民、原版人形亡灵等，见 `humanoid_victims`）→ 从 `pools.humanoid` 抽取，按强度给权重：基础 4 种 × 权重 10，强化人形 11 种 × 权重 5，精英（猎手系）× 权重 3，BOSS × 权重 1；
   - **其余所有生物**（包括玩家）→ 从 `pools.default` 抽取：狼尸 10、精英狼尸 5、蜘蛛尸 10、巨型蜘蛛尸 1。
3. 生成新丧尸后移除原尸体（玩家除外，玩家照常重生、不清除）。
4. 模组自己的丧尸被杀死时**不会**再转化（`excluded_victims` 默认排除 `zombie:zombie_*`），防止丧尸互杀导致无限增殖；如需开启，清空该项即可。

## 事件

- `endstone.event.ActorDeathEvent` —— 生物死亡；通过 `event.damage_source`（`DamageSource.actor` / `damaging_actor`）取得击杀者。
- `endstone.event.PlayerDeathEvent` —— 玩家死亡。Endstone 中玩家与生物的事件是平行体系（玩家死亡不触发 `ActorDeathEvent`），故单独订阅，与生物共用同一套转化逻辑。

## 安装

构建 wheel 并放入服务器的 `plugins` 目录：

```bash
cd endstone-biohazard
python -m pip wheel . --no-deps -w dist
# 把 dist/endstone_biohazard-1.0.0-py3-none-any.whl 复制到 bedrock_server/plugins/
```

重启服务器即可。开发调试可在服务器 venv 里 `pip install -e .`，改代码后游戏内执行 `/reload` 立即生效。

## 配置

首次启用时，随插件内置的 `config.toml`（`src/endstone_biohazard/config.toml`）会被复制到插件数据目录（`plugins/biohazard/config.toml`）。所有池、权重、人形判定列表、击杀者/排除模式都可在其中修改，改完 `/reload` 或重启生效；插件对缺失/无效的键会自动回退到内置默认值。

## 兼容性

- 按 [endstone.dev/latest](https://endstone.dev/latest/) 文档编写，`api_version = "0.11"`；若服务器较旧提示 API 版本不支持，改 `plugin.py` 中的 `api_version` 为服务器支持的版本即可。
- 实体类型读取同时兼容新版（`Actor.type` → `ActorType.id`）与旧版（字符串类型）API。

## 项目结构

```
endstone-biohazard/
├── pyproject.toml                     # 包元数据 + Endstone 插件入口点
└── src/endstone_biohazard/
    ├── __init__.py                    # 导出 BiohazardPlugin
    ├── config.toml                    # 默认配置（首次运行复制到数据目录）
    └── plugin.py                      # 事件监听 + 转化逻辑
```

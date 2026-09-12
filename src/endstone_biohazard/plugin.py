"""生化危机（Biohazard）—— 丧尸感染转化插件。

丧尸（zombie:zombie_*）杀死生物后，在死者位置生成一只新的丧尸：

- 普通生物：从默认池抽取（狼尸 / 蜘蛛尸系）；
- 人形生物（村民、猪灵等）：按强度权重从人形池抽取；
- 玩家被咬死：同样从默认池抽取（可在配置中关闭）。

订阅两个事件：ActorDeathEvent（生物死亡）与 PlayerDeathEvent（玩家死亡——
Endstone 中玩家与生物的事件是平行体系，玩家死亡不会触发 ActorDeathEvent）。
"""

import fnmatch
import random
import time

from endstone.event import ActorDeathEvent, PlayerDeathEvent, event_handler
from endstone.plugin import Plugin

# 代码内兜底默认值，与随插件分发的 config.toml 保持一致；
# 仅当配置文件缺失或个别键无效时启用。
DEFAULTS = {
    "killer_patterns": ["zombie:zombie_*"],
    "include_players": True,
    "excluded_victims": ["zombie:zombie_*"],
    "humanoid_victims": [
        "minecraft:villager",
        "minecraft:villager_v2",
        "minecraft:wandering_trader",
        "minecraft:piglin",
        "minecraft:piglin_brute",
        "minecraft:zombie_pigman",
        "minecraft:pillager",
        "minecraft:vindicator",
        "minecraft:evoker",
        "minecraft:illusioner",
        "minecraft:witch",
        "minecraft:zombie",
        "minecraft:husk",
        "minecraft:drowned",
        "minecraft:zombie_villager",
        "minecraft:zombie_villager_v2",
        "minecraft:skeleton",
        "minecraft:stray",
        "minecraft:wither_skeleton",
        "minecraft:bogged",
    ],
    "pools": {
        "default": {
            "zombie:zombie_wolf": 10,
            "zombie:zombie_wolf_elita": 5,
            "zombie:zombie_spider": 10,
            "zombie:zombie_spider_giant": 1,
        },
        "humanoid": {
            "zombie:zombie": 10,
            "zombie:zombie_withered": 10,
            "zombie:zombie_spit": 10,
            "zombie:zombie_mutant": 10,
            "zombie:zombie_conscript": 5,
            "zombie:zombie_butcher": 5,
            "zombie:zombie_marauder": 5,
            "zombie:zombie_adapted": 5,
            "zombie:zombie_executioner": 5,
            "zombie:zombie_defiler": 5,
            "zombie:zombie_longarms": 5,
            "zombie:zombie_jumper": 5,
            "zombie:zombie_runner": 5,
            "zombie:zombie_screamer": 5,
            "zombie:zombie_fat": 5,
            "zombie:zombie_hunter": 3,
            "zombie:zombie_hunter_elita": 3,
            "zombie:zombie_giant": 1,
            "zombie:zombie_nemesis_1": 1,
            "zombie:zombie_nemesis_2": 1,
            "zombie:zombie_tyrant": 1,
            "zombie:zombie_death_lord": 1,
        },
    },
}


def _as_patterns(value, fallback):
    """把配置值清洗成小写模式列表（支持 * 通配符），无效时回退默认值。"""
    if isinstance(value, (list, tuple)):
        patterns = [str(item).strip().lower() for item in value if str(item).strip()]
        if patterns:
            return patterns
    return [str(item).lower() for item in fallback]


def _as_weights(value, fallback, pool_name, logger):
    """把池配置清洗成 {实体ID: 权重}，丢弃无效条目；未配置时回退默认值。"""
    if value is None:
        return dict(fallback)
    if not isinstance(value, dict):
        logger.warning(f"[生化危机] 随机池 {pool_name} 的配置应为表（实体ID = 权重），已回退到默认值")
        return dict(fallback)
    weights = {}
    for entity_id, weight in value.items():
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            weight = 0.0
        entity_id = str(entity_id).strip().lower()
        if entity_id and weight > 0:
            weights[entity_id] = weight
        else:
            logger.warning(f"[生化危机] 随机池 {pool_name} 忽略无效条目：{entity_id!r} = {weight!r}")
    return weights


class BiohazardPlugin(Plugin):
    api_version = "0.11"

    def on_enable(self) -> None:
        self._recent_victims = {}
        self.save_default_config()
        self.reload_config()
        self._load_settings()
        self.register_events(self)
        summary = ", ".join(
            f"{name}({len(weights)} 种/权重和 {sum(weights.values()):g})"
            for name, weights in self._pools.items()
        )
        self.logger.info(f"生化危机已启用，随机池：{summary}")

    def on_disable(self) -> None:
        self.logger.info("生化危机已禁用。")

    # ------------------------------------------------------------------
    # 事件监听
    # ------------------------------------------------------------------

    @event_handler
    def on_actor_death(self, event: ActorDeathEvent) -> None:
        """生物被杀死：击杀者属于丧尸类时，把死者转化为新丧尸。"""
        victim = getattr(event, "actor", None)
        if victim is None:
            return
        killer = self._find_killer(getattr(event, "damage_source", None))
        if killer is None or self._is_same_actor(killer, victim):
            return
        self._try_convert(victim, killer)

    @event_handler
    def on_player_death(self, event: PlayerDeathEvent) -> None:
        """玩家被杀死：Endstone 中玩家死亡不触发 ActorDeathEvent，需单独订阅。"""
        victim = getattr(event, "player", None)
        if victim is None:
            return
        killer = self._find_killer(getattr(event, "damage_source", None))
        if killer is None or self._is_same_actor(killer, victim):
            return
        self._try_convert(victim, killer)

    # ------------------------------------------------------------------
    # 转化逻辑
    # ------------------------------------------------------------------

    def _try_convert(self, victim, killer) -> None:
        victim_type = self._type_id(victim)
        killer_type = self._type_id(killer)
        if not victim_type or not killer_type:
            return
        if not self._matches_any(killer_type, self._killer_patterns):
            return
        if victim_type == "minecraft:player" and not self._include_players:
            return
        if self._matches_any(victim_type, self._excluded_victims):
            return
        if not self._claim_victim(victim):
            return

        pool_name = "humanoid" if self._matches_any(victim_type, self._humanoid_victims) else "default"
        new_type = self._pick(pool_name)
        if new_type is None:
            self.logger.warning(f"[生化危机] 随机池 {pool_name} 为空，无法转化 {victim_type}")
            return

        location = victim.location
        dimension = victim.dimension
        try:
            spawned = dimension.spawn_actor(location, new_type)
        except Exception as error:
            self.logger.error(f"[生化危机] 生成 {new_type} 失败：{error}")
            return
        if spawned is None:
            self.logger.warning(f"[生化危机] 生成 {new_type} 未成功（spawn_actor 返回 None）")
            return

        # 玩家不能 remove（玩家会照常重生），其余受害者移除尸体完成“转化”
        if victim_type != "minecraft:player":
            try:
                victim.remove()
            except Exception as error:
                self.logger.warning(f"[生化危机] 清理尸体 {victim_type} 失败：{error}")

        self.logger.info(
            f"[生化危机] {killer_type} 击杀了 {victim_type}，转化为 {new_type}（池：{pool_name}）"
        )

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _find_killer(damage_source):
        """从伤害来源取击杀者：优先最终责任者（如弓箭手），其次直接伤害者（如箭矢）。"""
        if damage_source is None:
            return None
        for name in ("actor", "damaging_actor"):
            candidate = getattr(damage_source, name, None)
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _type_id(actor) -> str:
        """取实体类型字符串（如 'zombie:zombie_wolf'），兼容新旧版 Endstone。"""
        # 新版 Actor.type 返回 ActorType 对象（.id 为类型字符串），旧版直接是字符串
        for attr in ("type", "type_id"):
            value = getattr(actor, attr, None)
            if value is None:
                continue
            if isinstance(value, str):
                text = value.lower()
                if ":" in text:
                    return text
                continue
            value = getattr(value, "id", value)
            if value is None:
                continue
            text = str(value).lower()
            if ":" in text:
                return text
        return ""

    @staticmethod
    def _matches_any(type_id: str, patterns) -> bool:
        return any(fnmatch.fnmatch(type_id, pattern) for pattern in patterns)

    @staticmethod
    def _is_same_actor(left, right) -> bool:
        if left is right:
            return True
        left_id = getattr(left, "runtime_id", None)
        right_id = getattr(right, "runtime_id", None)
        return left_id is not None and left_id == right_id

    def _claim_victim(self, victim) -> bool:
        """登记死者；同一实体 1 秒内只转化一次，防止事件重复分发导致刷怪。"""
        runtime_id = getattr(victim, "runtime_id", None)
        if runtime_id is None:
            return True
        now = time.monotonic()
        last = self._recent_victims.get(runtime_id)
        if last is not None and now - last < 1.0:
            return False
        if len(self._recent_victims) > 256:
            self._recent_victims = {
                key: stamp for key, stamp in self._recent_victims.items() if now - stamp < 1.0
            }
        self._recent_victims[runtime_id] = now
        return True

    def _pick(self, pool_name: str):
        weights = self._pools.get(pool_name)
        if not weights:
            return None
        entity_ids = list(weights.keys())
        return random.choices(
            entity_ids, weights=[weights[entity_id] for entity_id in entity_ids], k=1
        )[0]

    def _load_settings(self) -> None:
        config = self.config or {}
        self._killer_patterns = _as_patterns(config.get("killer_patterns"), DEFAULTS["killer_patterns"])
        self._include_players = bool(config.get("include_players", DEFAULTS["include_players"]))
        self._excluded_victims = _as_patterns(config.get("excluded_victims"), DEFAULTS["excluded_victims"])
        self._humanoid_victims = _as_patterns(config.get("humanoid_victims"), DEFAULTS["humanoid_victims"])

        pools_config = config.get("pools")
        if not isinstance(pools_config, dict):
            pools_config = {}
        self._pools = {}
        for pool_name, fallback in DEFAULTS["pools"].items():
            self._pools[pool_name] = _as_weights(
                pools_config.get(pool_name), fallback, pool_name, self.logger
            )
        for pool_name, value in pools_config.items():
            if pool_name not in self._pools:
                self._pools[str(pool_name)] = _as_weights(value, {}, str(pool_name), self.logger)

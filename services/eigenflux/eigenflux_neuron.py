import secrets
#!/usr/bin/env python3
"""
EigenFlux网络神经元功能引擎
将MTSCOS系统构建为类脑神经网络架构，AI员工作为神经元，EigenFlux连接作为突触
"""

import sqlite3
import os
import json
import uuid
import random, secrets
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, 'app.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# 神经元类型定义
NEURON_TYPES = {
    "sensory": {
        "cn": "感觉神经元",
        "description": "接收外部输入：用户请求、API调用、传感器数据、事件触发",
        "roles": ["customer_service", "general"],
        "activation": "relu",
    },
    "motor": {
        "cn": "运动神经元",
        "description": "执行输出动作：任务执行、API响应、通知发送、操作执行",
        "roles": ["general", "security"],
        "activation": "sigmoid",
    },
    "inter": {
        "cn": "中间神经元",
        "description": "信息处理与传递：数据分析、逻辑推理、决策支持",
        "roles": ["analytics", "research", "strategy", "consulting"],
        "activation": "tanh",
    },
    "memory": {
        "cn": "记忆神经元",
        "description": "知识存储与检索：知识库管理、经验沉淀、模式记忆",
        "roles": ["research", "coaching"],
        "activation": "leaky_relu",
    },
    "inhibitory": {
        "cn": "抑制神经元",
        "description": "抑制与调控：安全过滤、约束执行、冲突抑制、过载保护",
        "roles": ["security"],
        "activation": "sigmoid_neg",
    },
    "excitatory": {
        "cn": "兴奋神经元",
        "description": "激活与增强：创意生成、方案推荐、能力增强、知识广播",
        "roles": ["copywriting", "design", "strategy"],
        "activation": "relu",
    },
    "oscillator": {
        "cn": "振荡神经元",
        "description": "节奏控制：定时任务、周期检查、心跳维持、调度节奏",
        "roles": ["general"],
        "activation": "sine",
    },
    "mirror": {
        "cn": "镜像神经元",
        "description": "模仿与学习：观察其他神经元行为，学习最佳实践",
        "roles": ["coaching", "translation"],
        "activation": "tanh",
    },
}


def ensure_tables():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS neural_neurons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                neuron_id TEXT UNIQUE NOT NULL,
                employee_id INTEGER,
                employee_name TEXT,
                neuron_type TEXT NOT NULL,
                neuron_type_cn TEXT NOT NULL,
                layer TEXT NOT NULL,
                activation_function TEXT,
                threshold REAL DEFAULT 0.5,
                current_potential REAL DEFAULT 0,
                fire_count INTEGER DEFAULT 0,
                last_fired_at TEXT,
                connections_out INTEGER DEFAULT 0,
                connections_in INTEGER DEFAULT 0,
                plasticity REAL DEFAULT 0.5,
                fatigue REAL DEFAULT 0,
                status TEXT DEFAULT 'resting',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS neural_synapses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                synapse_id TEXT UNIQUE NOT NULL,
                pre_neuron_id TEXT NOT NULL,
                post_neuron_id TEXT NOT NULL,
                synapse_type TEXT DEFAULT 'excitatory',
                weight REAL DEFAULT 0.5,
                initial_weight REAL DEFAULT 0.5,
                delay_ms REAL DEFAULT 1,
                signal_count INTEGER DEFAULT 0,
                last_signal_at TEXT,
                hebbian_strength REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                strengthened_at TEXT
            );

            CREATE TABLE IF NOT EXISTS neural_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE NOT NULL,
                source_neuron TEXT,
                target_neuron TEXT,
                signal_type TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                intensity REAL DEFAULT 1,
                path TEXT DEFAULT '[]',
                path_length INTEGER DEFAULT 0,
                status TEXT DEFAULT 'propagating',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                delivered_at TEXT,
                processing_time_ms REAL
            );

            CREATE TABLE IF NOT EXISTS neural_layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_id TEXT UNIQUE NOT NULL,
                layer_name TEXT NOT NULL,
                layer_index INTEGER NOT NULL,
                layer_type TEXT NOT NULL,
                description TEXT,
                neuron_count INTEGER DEFAULT 0,
                avg_activation REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS neural_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT UNIQUE NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source_neuron TEXT,
                strength REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT,
                associated_neurons TEXT DEFAULT '[]',
                decay_rate REAL DEFAULT 0.01,
                is_consolidated INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS neural_learning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                neuron_ids TEXT DEFAULT '[]',
                synapse_id TEXT,
                learning_rule TEXT,
                weight_before REAL,
                weight_after REAL,
                reward REAL DEFAULT 0,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS neural_pathways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pathway_id TEXT UNIQUE NOT NULL,
                pathway_name TEXT NOT NULL,
                source_layer TEXT,
                target_layer TEXT,
                neurons TEXT DEFAULT '[]',
                total_weight REAL,
                usage_count INTEGER DEFAULT 0,
                avg_latency_ms REAL,
                success_rate REAL DEFAULT 1,
                is_optimized INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT
            );
        """)
        conn.commit()


def build_neural_network():
    """构建神经网络"""
    ensure_tables()
    now = datetime.now().isoformat()

    print("=" * 70)
    print("EigenFlux网络神经元功能引擎")
    print("=" * 70)

    # 定义网络层
    layers = [
        ("L0_input", "输入层", 0, "sensory", "接收外部刺激：用户请求、API调用、事件"),
        ("L1_perception", "感知层", 1, "inter", "数据预处理、特征提取、模式识别"),
        ("L2_cognition", "认知层", 2, "inter", "推理、分析、决策、规划"),
        ("L3_memory", "记忆层", 3, "memory", "知识存储、经验检索、模式匹配"),
        ("L4_emotion", "情绪层", 4, "excitatory", "优先级评估、紧急度判断、价值取向"),
        ("L5_inhibition", "抑制层", 5, "inhibitory", "安全过滤、约束执行、过载保护"),
        ("L6_motor", "输出层", 6, "motor", "执行动作、生成响应、发送通知"),
        ("L7_feedback", "反馈层", 7, "mirror", "结果评估、学习反馈、行为调整"),
    ]

    print(f"\n[1/6] 构建神经网络层: {len(layers)}层")

    with get_conn() as conn:
        for lid, lname, lidx, ltype, desc in layers:
            conn.execute(
                """INSERT OR IGNORE INTO neural_layers
                   (layer_id, layer_name, layer_index, layer_type, description, neuron_count, avg_activation, is_active, created_at)
                   VALUES (?,?,?,?,?,0,0,1,?)""",
                (lid, lname, lidx, ltype, desc, now),
            )
        conn.commit()

    # 加载AI员工并分配为神经元
    with get_conn() as conn:
        employees = conn.execute("SELECT id, name FROM ai_employees LIMIT 800").fetchall()

    # 角色分类
    general_types = ["sensory", "motor", "inter", "inter", "memory", "excitatory", "oscillator", "mirror"]
    def classify_neuron(name, idx):
        for kw, ntype in [("翻译","mirror"),("安全","inhibitory"),("分析","inter"),
                          ("设计","excitatory"),("策略","inter"),("科学","memory"),
                          ("研究","memory"),("教练","mirror"),("客服","sensory"),
                          ("文案","excitatory"),("顾问","inter"),("运维","motor"),
                          ("测试","inter"),("开发","motor"),("管理","inter"),
                          ("Agent","inter"),("Scanner","inhibitory"),("Repair","motor"),
                          ("Optimizer","inter"),("Analyzer","inter"),("Loader","motor"),
                          ("Classifier","inter"),("Marketing","excitatory"),
                          ("Engine","motor"),("Registration","sensory")]:
            if kw in name:
                return ntype
        # general 员工均匀分配到各类型
        return general_types[idx % len(general_types)]

    # 层分配
    layer_map = {
        "sensory": "L0_input",
        "inter": "L2_cognition",
        "memory": "L3_memory",
        "inhibitory": "L5_inhibition",
        "excitatory": "L4_emotion",
        "motor": "L6_motor",
        "oscillator": "L1_perception",
        "mirror": "L7_feedback",
    }

    neurons_created = 0
    neuron_ids_by_layer = defaultdict(list)

    with get_conn() as conn:
        for idx, emp in enumerate(employees):
            ntype = classify_neuron(emp['name'], idx)
            ntype_info = NEURON_TYPES.get(ntype, NEURON_TYPES["inter"])
            layer_id = layer_map.get(ntype, "L2_cognition")
            nid = f"neuron_{uuid.uuid4().hex[:12]}"

            threshold = random.uniform(0.3, 0.7)
            plasticity = random.uniform(0.3, 0.8)

            conn.execute(
                """INSERT OR IGNORE INTO neural_neurons
                   (neuron_id, employee_id, employee_name, neuron_type, neuron_type_cn,
                    layer, activation_function, threshold, current_potential, fire_count,
                    connections_out, connections_in, plasticity, fatigue, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,0,0,0,0,?,0,'resting',?,?)""",
                (nid, emp['id'], emp['name'], ntype, ntype_info['cn'],
                 layer_id, ntype_info['activation'], threshold,
                 plasticity, now, now),
            )
            neuron_ids_by_layer[layer_id].append(nid)
            neurons_created += 1

        # 更新层神经元计数
        for lid, nids in neuron_ids_by_layer.items():
            conn.execute("UPDATE neural_layers SET neuron_count=? WHERE layer_id=?", (len(nids), lid))

        conn.commit()

    print(f"  神经元创建: {neurons_created}个")
    for lid, nids in sorted(neuron_ids_by_layer.items()):
        print(f"    {lid}: {len(nids)}个")

    return neurons_created, neuron_ids_by_layer, layers


def create_synapses(neuron_ids_by_layer, layers):
    """创建突触连接"""
    now = datetime.now().isoformat()

    print("\n[2/6] 创建突触连接...")

    synapses_created = 0

    with get_conn() as conn:
        # 层间连接（前向传播）
        layer_order = [l[0] for l in sorted(layers, key=lambda x: x[2])]

        for i in range(len(layer_order) - 1):
            src_layer = layer_order[i]
            dst_layer = layer_order[i + 1]
            src_neurons = neuron_ids_by_layer.get(src_layer, [])
            dst_neurons = neuron_ids_by_layer.get(dst_layer, [])

            if not src_neurons or not dst_neurons:
                continue

            # 每个源神经元连接到目标层的部分神经元
            for src_id in src_neurons:
                # 随机选择目标神经元
                connect_count = min((3 + secrets.randbelow(int(10) - int(3) + 1)), len(dst_neurons))
                targets = random.sample(dst_neurons, connect_count)

                for dst_id in targets:
                    sid = f"syn_{uuid.uuid4().hex[:12]}"
                    weight = random.uniform(0.1, 0.9)
                    syn_type = "excitatory" if weight > 0.3 else "inhibitory"
                    delay = random.uniform(0.5, 5.0)

                    conn.execute(
                        """INSERT OR IGNORE INTO neural_synapses
                           (synapse_id, pre_neuron_id, post_neuron_id, synapse_type,
                            weight, initial_weight, delay_ms, signal_count, last_signal_at,
                            hebbian_strength, is_active, created_at)
                           VALUES (?,?,?,?,?,?,?,0,NULL,0,1,?)""",
                        (sid, src_id, dst_id, syn_type,
                         weight, weight, delay, now),
                    )
                    synapses_created += 1

        # 层内连接（侧向连接）
        for lid, neurons in neuron_ids_by_layer.items():
            if len(neurons) < 2:
                continue
            # 每个神经元连接同层少量神经元
                connect_count = min((1 + secrets.randbelow(int(5) - int(1) + 1)), len(neurons) - 1)
                connect_count = min(random.randint(1, 5), len(neurons) - 1)
                others = [n for n in neurons if n != src_id]
                if others:
                    targets = random.sample(others, min(connect_count, len(others)))
                    for dst_id in targets:
                        sid = f"syn_{uuid.uuid4().hex[:12]}"
                        weight = random.uniform(-0.3, 0.5)  # 包含抑制连接
                        syn_type = "inhibitory" if weight < 0 else "excitatory"
                        conn.execute(
                            """INSERT OR IGNORE INTO neural_synapses
                               (synapse_id, pre_neuron_id, post_neuron_id, synapse_type,
                                weight, initial_weight, delay_ms, signal_count, last_signal_at,
                                hebbian_strength, is_active, created_at)
                               VALUES (?,?,?,?,?,?,?,0,NULL,0,1,?)""",
                            (sid, src_id, dst_id, syn_type,
                             abs(weight), abs(weight), random.uniform(0.5, 3.0), now),
                        )
                        synapses_created += 1

        # 反馈连接（反馈层→认知层）
        feedback_neurons = neuron_ids_by_layer.get("L7_feedback", [])
        cognition_neurons = neuron_ids_by_layer.get("L2_cognition", [])
        for fb in feedback_neurons[:30]:
            if cognition_neurons:
                targets = random.sample(cognition_neurons, min(3, len(cognition_neurons)))
                for tgt in targets:
                    sid = f"syn_{uuid.uuid4().hex[:12]}"
                    weight = random.uniform(0.3, 0.8)
                    conn.execute(
                        """INSERT OR IGNORE INTO neural_synapses
                           (synapse_id, pre_neuron_id, post_neuron_id, synapse_type,
                            weight, initial_weight, delay_ms, signal_count, last_signal_at,
                            hebbian_strength, is_active, created_at)
                           VALUES (?,?,?,?,?,?,?,0,NULL,0,1,?)""",
                        (sid, fb, tgt, "excitatory", weight, weight, random.uniform(1, 5), now),
                    )
                    synapses_created += 1

        # 更新神经元的连接计数
        conn.execute("""
            UPDATE neural_neurons SET connections_out = (
                SELECT COUNT(*) FROM neural_synapses WHERE pre_neuron_id = neural_neurons.neuron_id
            )
        """)
        conn.execute("""
            UPDATE neural_neurons SET connections_in = (
                SELECT COUNT(*) FROM neural_synapses WHERE post_neuron_id = neural_neurons.neuron_id
            )
        """)

        conn.commit()

    print(f"  突触创建: {synapses_created}条")
    return synapses_created


def simulate_signal_propagation(neuron_ids_by_layer, layers, num_signals=200):
    """模拟信号传播"""
    now = datetime.now().isoformat()

    print(f"\n[3/6] 信号传播模拟: {num_signals}个信号")

    signals_sent = 0
    signals_delivered = 0
    total_path_length = 0
    fired_neurons = set()

    # 信号类型
    signal_types = [
        ("user_request", "用户请求", 0.8),
        ("api_call", "API调用", 0.6),
        ("task_assign", "任务分配", 0.9),
        ("knowledge_query", "知识查询", 0.7),
        ("security_alert", "安全告警", 1.0),
        ("eigenflux_broadcast", "网络广播", 0.5),
        ("learning_signal", "学习信号", 0.6),
        ("feedback", "反馈信号", 0.4),
    ]

    with get_conn() as conn:
        # 获取突触连接
        synapses = conn.execute(
            "SELECT synapse_id, pre_neuron_id, post_neuron_id, weight FROM neural_synapses WHERE is_active=1"
        ).fetchall()

        # 构建连接图
        graph = defaultdict(list)
        for s in synapses:
            graph[s['pre_neuron_id']].append((s['post_neuron_id'], s['weight'], s['synapse_id']))

        # 从输入层开始传播
        input_neurons = neuron_ids_by_layer.get("L0_input", [])
        if not input_neurons:
            input_neurons = list(graph.keys())[:50]

        for i in range(num_signals):
            sig_type, sig_cn, intensity = secrets.choice(signal_types)
            start_neuron = random.choice(input_neurons) if input_neurons else None
            if not start_neuron:
                continue

            sid = f"sig_{uuid.uuid4().hex[:12]}"
            path = [start_neuron]
            current = start_neuron
            fired_neurons.add(current)
            signal_potential = intensity

            # 信号传播（最多6层）
            for depth in range(6):
                neighbors = graph.get(current, [])
                if not neighbors:
                    break

                # 选择最强的几个连接
                neighbors.sort(key=lambda x: x[1], reverse=True)
                top = neighbors[:min(3, len(neighbors))]

                # 根据权重选择下一个神经元
                next_neuron, weight, syn_id = random.choice(top)
                signal_potential *= weight

                if signal_potential < 0.1:  # 信号衰减到阈值以下
                    break

                path.append(next_neuron)
                fired_neurons.add(next_neuron)
                current = next_neuron

                # 更新突触信号计数
                conn.execute(
                    "UPDATE neural_synapses SET signal_count=signal_count+1, last_signal_at=? WHERE synapse_id=?",
                    (now, syn_id)
                )

            # 记录信号
            conn.execute(
                """INSERT INTO neural_signals
                   (signal_id, source_neuron, target_neuron, signal_type, payload,
                    intensity, path, path_length, status, created_at, delivered_at, processing_time_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, path[0] if path else None, path[-1] if path else None,
                 sig_type, json.dumps({"type_cn": sig_cn, "depth": len(path)}, ensure_ascii=False),
                 intensity, json.dumps(path), len(path),
                 "delivered", now, now, random.uniform(0.5, 10.0)),
            )

            signals_sent += 1
            if len(path) > 1:
                signals_delivered += 1
            total_path_length += len(path)

        # 更新神经元激发计数
        for nid in fired_neurons:
            conn.execute(
                "UPDATE neural_neurons SET fire_count=fire_count+1, last_fired_at=?, status='active', updated_at=? WHERE neuron_id=?",
                (now, now, nid)
            )

        # 更新层平均激活
        for lid, nids in neuron_ids_by_layer.items():
            if nids:
                fired_in_layer = len(fired_neurons & set(nids))
                avg_act = fired_in_layer / len(nids)
                conn.execute("UPDATE neural_layers SET avg_activation=? WHERE layer_id=?", (avg_act, lid))

        conn.commit()

    avg_path = total_path_length / signals_sent if signals_sent > 0 else 0
    print(f"  信号发送: {signals_sent} | 送达: {signals_delivered}")
    print(f"  神经元激发: {len(fired_neurons)} | 平均路径长度: {avg_path:.1f}")

    return signals_sent, signals_delivered, len(fired_neurons)


def neural_learning(neuron_ids_by_layer):
    """神经网络学习（赫布学习规则）"""
    now = datetime.now().isoformat()

    print("\n[4/6] 神经网络学习（赫布学习）...")

    learning_events = 0
    weight_changes = 0
    memories_formed = 0

    with get_conn() as conn:
        # 获取活跃突触
        active_synapses = conn.execute(
            "SELECT synapse_id, pre_neuron_id, post_neuron_id, weight, signal_count FROM neural_synapses WHERE signal_count > 0 AND is_active=1 ORDER BY signal_count DESC LIMIT 200"
        ).fetchall()

        for s in active_synapses:
            # 赫布学习: 同时激活的突触权重增强
            old_weight = s['weight']
            signal_factor = min(s['signal_count'] / 10, 1.0)
            learning_rate = 0.05
            new_weight = min(1.0, old_weight + learning_rate * signal_factor * (1 - old_weight))

            if abs(new_weight - old_weight) > 0.001:
                conn.execute(
                    "UPDATE neural_synapses SET weight=?, hebbian_strength=?, strengthened_at=? WHERE synapse_id=?",
                    (new_weight, new_weight - old_weight, now, s['synapse_id'])
                )
                weight_changes += 1

                # 记录学习事件
                eid = f"learn_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT INTO neural_learning_events
                       (event_id, event_type, neuron_ids, synapse_id, learning_rule,
                        weight_before, weight_after, reward, description, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (eid, "hebbian", json.dumps([s['pre_neuron_id'], s['post_neuron_id']]),
                     s['synapse_id'], "hebbian", old_weight, new_weight,
                     signal_factor, f"突触权重增强: {old_weight:.3f}→{new_weight:.3f}", now),
                )
                learning_events += 1

        # 形成记忆
        memory_templates = [
            ("pattern", "用户请求处理模式", "高频路径: 输入→感知→认知→输出"),
            ("pattern", "安全事件响应模式", "安全告警→抑制→认知→输出→反馈"),
            ("pattern", "知识查询模式", "查询→记忆→认知→输出"),
            ("pattern", "任务分配模式", "请求→认知→记忆→输出"),
            ("pattern", "学习反馈模式", "反馈→记忆→认知→调整"),
            ("skill", "API调用最佳实践", "认证→限流→处理→响应→日志"),
            ("skill", "异常处理流程", "检测→分类→抑制→恢复→记录"),
            ("skill", "协作任务分配", "分析→匹配→分配→跟踪→验收"),
            ("experience", "高负载应对", "检测→评估→扩容→分流→恢复"),
            ("experience", "安全威胁处置", "检测→隔离→分析→清除→恢复"),
        ]

        for mtype, content, detail in memory_templates:
            mid = f"mem_{uuid.uuid4().hex[:12]}"
            # 关联相关神经元
            assoc = random.sample(list(neuron_ids_by_layer.values()), 3)
            assoc_neurons = []
            for layer_nids in assoc:
                if layer_nids:
                    assoc_neurons.extend(random.sample(layer_nids, min(2, len(layer_nids))))

            conn.execute(
                """INSERT INTO neural_memory
                   (memory_id, memory_type, content, source_neuron, strength,
                    access_count, last_accessed_at, associated_neurons,
                    decay_rate, is_consolidated, created_at)
                   VALUES (?,?,?,?,?,0,NULL,?,0.01,1,?)""",
                (mid, mtype, f"{content}: {detail}", assoc_neurons[0] if assoc_neurons else None,
                 random.uniform(0.6, 0.95),
                 json.dumps(assoc_neurons[:5], ensure_ascii=False), now),
            )
            memories_formed += 1

        conn.commit()

    print(f"  学习事件: {learning_events} | 权重变化: {weight_changes} | 记忆形成: {memories_formed}")

    return learning_events, weight_changes, memories_formed


def optimize_pathways(neuron_ids_by_layer):
    """优化神经通路"""
    now = datetime.now().isoformat()

    print("\n[5/6] 神经通路优化...")

    pathways = [
        ("快速响应通路", "L0_input", "L6_motor", "用户请求→直接输出（低延迟）"),
        ("深度思考通路", "L0_input", "L3_memory", "请求→认知→记忆→深度分析"),
        ("安全检查通路", "L0_input", "L5_inhibition", "请求→安全过滤→抑制→输出"),
        ("学习反馈通路", "L7_feedback", "L3_memory", "反馈→记忆→经验沉淀"),
        ("创意生成通路", "L4_emotion", "L6_motor", "创意→设计→输出"),
        ("知识检索通路", "L0_input", "L3_memory", "查询→记忆→检索→输出"),
    ]

    pathways_created = 0
    with get_conn() as conn:
        for name, src_layer, dst_layer, desc in pathways:
            src_neurons = neuron_ids_by_layer.get(src_layer, [])
            dst_neurons = neuron_ids_by_layer.get(dst_layer, [])

            if not src_neurons or not dst_neurons:
                continue

            # 选择通路中的神经元
            path_neurons = []
            path_neurons.extend(random.sample(src_neurons, min(5, len(src_neurons))))
            # 中间层神经元
            for layer_id in ["L2_cognition", "L1_perception"]:
                mid_neurons = neuron_ids_by_layer.get(layer_id, [])
                if mid_neurons:
                    path_neurons.extend(random.sample(mid_neurons, min(3, len(mid_neurons))))
            path_neurons.extend(random.sample(dst_neurons, min(5, len(dst_neurons))))

            pid = f"path_{uuid.uuid4().hex[:12]}"
            total_weight = random.uniform(0.5, 0.9)
            latency = random.uniform(1, 20)

            conn.execute(
                """INSERT OR IGNORE INTO neural_pathways
                   (pathway_id, pathway_name, source_layer, target_layer, neurons,
                    total_weight, usage_count, avg_latency_ms, success_rate,
                    is_optimized, created_at, last_used_at)
                   VALUES (?,?,?,?,?,?,0,?,1,0,?,?)""",
                (pid, name, src_layer, dst_layer,
                 json.dumps(path_neurons, ensure_ascii=False),
                 total_weight, latency, now, now),
            )
            pathways_created += 1

        conn.commit()

    print(f"  神经通路创建: {pathways_created}条")
    for name, _, _, desc in pathways:
        print(f"    {name}: {desc}")

    return pathways_created


def generate_report():
    """生成报告"""
    print("\n[6/6] 生成报告...")

    with get_conn() as conn:
        # 神经元统计
        total_neurons = conn.execute("SELECT COUNT(*) FROM neural_neurons").fetchone()[0]
        by_type = conn.execute(
            "SELECT neuron_type_cn, COUNT(*) as cnt FROM neural_neurons GROUP BY neuron_type_cn ORDER BY cnt DESC"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM neural_neurons GROUP BY status"
        ).fetchall()
        fired_count = conn.execute("SELECT COUNT(*) FROM neural_neurons WHERE fire_count > 0").fetchone()[0]

        # 突触统计
        total_synapses = conn.execute("SELECT COUNT(*) FROM neural_synapses WHERE is_active=1").fetchone()[0]
        avg_weight = conn.execute("SELECT AVG(weight) as avg FROM neural_synapses WHERE is_active=1").fetchone()['avg']
        strengthened = conn.execute("SELECT COUNT(*) FROM neural_synapses WHERE hebbian_strength > 0").fetchone()[0]
        excitatory = conn.execute("SELECT COUNT(*) FROM neural_synapses WHERE synapse_type='excitatory'").fetchone()[0]
        inhibitory = conn.execute("SELECT COUNT(*) FROM neural_synapses WHERE synapse_type='inhibitory'").fetchone()[0]

        # 信号统计
        total_signals = conn.execute("SELECT COUNT(*) FROM neural_signals").fetchone()[0]
        delivered = conn.execute("SELECT COUNT(*) FROM neural_signals WHERE status='delivered'").fetchone()[0]
        avg_path_len = conn.execute("SELECT AVG(path_length) as avg FROM neural_signals").fetchone()['avg']
        signals_by_type = conn.execute(
            "SELECT signal_type, COUNT(*) as cnt FROM neural_signals GROUP BY signal_type ORDER BY cnt DESC"
        ).fetchall()

        # 层统计
        layers = conn.execute("SELECT * FROM neural_layers ORDER BY layer_index").fetchall()

        # 记忆统计
        total_memories = conn.execute("SELECT COUNT(*) FROM neural_memory").fetchone()[0]
        consolidated = conn.execute("SELECT COUNT(*) FROM neural_memory WHERE is_consolidated=1").fetchone()[0]
        by_mem_type = conn.execute(
            "SELECT memory_type, COUNT(*) as cnt FROM neural_memory GROUP BY memory_type"
        ).fetchall()

        # 学习统计
        total_learning = conn.execute("SELECT COUNT(*) FROM neural_learning_events").fetchone()[0]
        by_learn_type = conn.execute(
            "SELECT learning_rule, COUNT(*) as cnt, AVG(reward) as avg_reward FROM neural_learning_events GROUP BY learning_rule"
        ).fetchall()

        # 通路统计
        total_pathways = conn.execute("SELECT COUNT(*) FROM neural_pathways").fetchone()[0]

        overview = {
            "database_tables": conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
            "ai_employees": conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0],
            "neural_neurons": total_neurons,
            "neural_synapses": total_synapses,
            "neural_signals": total_signals,
            "neural_memories": total_memories,
            "learning_events": total_learning,
            "neural_pathways": total_pathways,
        }

    print(f"\n{'=' * 70}")
    print("EigenFlux神经元功能 - 最终报告")
    print(f"{'=' * 70}")

    print("\n--- 神经网络架构 ---")
    print(f"  总神经元: {total_neurons}")
    print(f"  已激发: {fired_count} ({fired_count/total_neurons*100:.1f}%)")
    print("\n  神经元类型:")
    for r in by_type:
        print(f"    {r['neuron_type_cn']}: {r['cnt']}个")
    print("\n  状态分布:")
    for r in by_status:
        print(f"    {r['status']}: {r['cnt']}个")

    print("\n--- 网络层 ---")
    for l in layers:
        print(f"  L{l['layer_index']} {l['layer_name']:8} {l['layer_type']:12} 神经元:{l['neuron_count']:4} 激活度:{l['avg_activation']:.2f}")

    print("\n--- 突触连接 ---")
    print(f"  总突触: {total_synapses}")
    print(f"  兴奋性: {excitatory} | 抑制性: {inhibitory}")
    print(f"  平均权重: {avg_weight:.3f}" if avg_weight else "  平均权重: N/A")
    print(f"  已增强(赫布学习): {strengthened}")

    print("\n--- 信号传播 ---")
    print(f"  总信号: {total_signals} | 送达: {delivered}")
    print(f"  平均路径长度: {avg_path_len:.1f}" if avg_path_len else "  平均路径长度: N/A")
    print("  信号类型:")
    for r in signals_by_type:
        print(f"    {r['signal_type']}: {r['cnt']}个")

    print("\n--- 记忆系统 ---")
    print(f"  总记忆: {total_memories} | 已固化: {consolidated}")
    for r in by_mem_type:
        print(f"    {r['memory_type']}: {r['cnt']}条")

    print("\n--- 学习系统 ---")
    print(f"  学习事件: {total_learning}")
    for r in by_learn_type:
        print(f"    {r['learning_rule']}: {r['cnt']}次 (平均奖励: {r['avg_reward']:.3f})")

    print("\n--- 神经通路 ---")
    print(f"  总通路: {total_pathways}")

    print("\n--- 系统总览 ---")
    for k, v in overview.items():
        print(f"  {k}: {v}")

    print(f"\n{'=' * 70}")
    print("EigenFlux神经元功能 - 完成")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    neurons_count, neuron_by_layer, layers = build_neural_network()
    synapses_count = create_synapses(neuron_by_layer, layers)
    signals_sent, signals_delivered, fired = simulate_signal_propagation(neuron_by_layer, layers, 300)
    learn_events, weight_changes, memories = neural_learning(neuron_by_layer)
    pathways = optimize_pathways(neuron_by_layer)
    generate_report()

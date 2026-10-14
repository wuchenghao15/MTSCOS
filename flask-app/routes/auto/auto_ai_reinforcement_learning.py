"""自动生成的路由蓝图 - ai_reinforcement_learning"""
from flask import Blueprint, jsonify, request
from services.ai_reinforcement_learning import SimpleEnvironment
from app.middlewares.system_container import system_container

ai_reinforcement_learning_bp = Blueprint('ai_reinforcement_learning_bp', __name__, url_prefix='/api/ai/reinforcement/learning')

@ai_reinforcement_learning_bp.route('/reset/<int:item_id>', methods=['PUT'])
@system_container()
def reset(item_id):
    """"""
    data = request.get_json() or {}
    try:
        service = SimpleEnvironment()
        result = service.reset()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ai_reinforcement_learning_bp.route('/step', methods=['POST'])
@system_container()
def step():
    """执行动作: 0=上 1=下 2=左 3=右"""
    data = request.get_json() or {}
    kwargs = {'action': data.get('action')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = SimpleEnvironment()
        result = service.step(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ai_reinforcement_learning_bp.route('/n_actions', methods=['POST'])
@system_container()
def n_actions():
    """"""
    data = request.get_json() or {}
    try:
        service = SimpleEnvironment()
        result = service.n_actions()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ai_reinforcement_learning_bp.route('/n_states', methods=['POST'])
@system_container()
def n_states():
    """"""
    data = request.get_json() or {}
    try:
        service = SimpleEnvironment()
        result = service.n_states()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ai_reinforcement_learning_bp.route('/state_to_id', methods=['POST'])
@system_container()
def state_to_id():
    """"""
    data = request.get_json() or {}
    kwargs = {'state': data.get('state')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = SimpleEnvironment()
        result = service.state_to_id(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

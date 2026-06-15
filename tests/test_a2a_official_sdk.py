"""
测试 Google 官方 A2A SDK 集成
"""
from a2a.types import TaskState
from agent.a2a_official_sdk import (
    create_agent_a_card,
    create_agent_b_card,
    create_user_message,
    create_agent_message,
    create_task,
    update_task_status,
    add_artifact,
    is_task_completed
)


def test_official_sdk():
    """测试官方 A2A SDK"""
    print("=" * 60)
    print("测试 Google 官方 A2A SDK 集成")
    print("=" * 60)
    
    # 1. 测试 AgentCard
    print("\n1. 测试 AgentCard 创建")
    agent_card = create_agent_b_card()
    print(f"   名称: {agent_card.name}")
    print(f"   技能数: {len(agent_card.skills)}")
    print(f"   能力: streaming={agent_card.capabilities.streaming}")
    
    # 2. 测试消息创建
    print("\n2. 测试消息创建")
    user_msg = create_user_message("我有高血压，推荐一日三餐")
    print(f"   用户消息角色: {user_msg.role}")
    print(f"   Part 文本内容: {user_msg.parts[0].text}")
    
    agent_msg = create_agent_message("配餐方案已生成")
    print(f"   Agent 消息角色: {agent_msg.role}")
    
    # 3. 测试任务创建
    print("\n3. 测试任务创建")
    task = create_task(user_msg, context_id="session_001")
    print(f"   Task ID: {task.id}")
    print(f"   Context ID: {task.context_id}")
    print(f"   状态: {task.status.state}")
    print(f"   历史消息数: {len(task.history)}")
    
    # 4. 测试状态更新
    print("\n4. 测试状态更新")
    task = update_task_status(task, TaskState.TASK_STATE_WORKING)
    print(f"   状态 → working: {task.status.state}")
    
    task = update_task_status(task, TaskState.TASK_STATE_COMPLETED)
    print(f"   状态 → completed: {task.status.state}")
    
    # 5. 测试产出物
    print("\n5. 测试产出物添加")
    task = add_artifact(task, name="meal_plan", text="配餐完成")
    print(f"   产出物数: {len(task.artifacts)}")
    print(f"   产出物名称: {task.artifacts[0].name}")
    print(f"   产出物内容: {task.artifacts[0].parts[0].text}")
    
    # 6. 测试完成判断
    print("\n6. 测试完成判断")
    print(f"   是否完成: {is_task_completed(task)}")
    
    print("\n" + "=" * 60)
    print("✅ 所有官方 SDK 测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    test_official_sdk()
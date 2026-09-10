"""本地跑一遍 Knowledge Agent 全链路。

    python main.py [owner] [repo]

不传参数就用 example/demo-project —— 底层 Tool 目前全是 mock 数据，不访问
GitHub，所以 owner/repo 填什么都不影响结果（只影响 State.source.url 和提案的
title）。

需要项目根目录下有 .env（照 .env.example 填），否则这里报 ConfigError。
"""

import sys

from app.agents.knowledge_agent import KnowledgeAgent
from app.config import ConfigError
from app.llm import create_llm_client

DEFAULT_OWNER = "example"
DEFAULT_REPO = "demo-project"


def main() -> int:
    # print 中文时别让控制台编码把脚本搞崩。errors="replace" 保证最差也只是
    # 显示成问号，而不是抛 UnicodeEncodeError 把整次运行的结果吞掉。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    owner = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OWNER
    repo = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPO

    try:
        llm = create_llm_client()
    except ConfigError as error:
        print(f".env 有问题：{error}")
        return 1

    agent = KnowledgeAgent(owner, repo, llm=llm)
    state = agent.run()

    # mode 是 OpenAIClient 自己的实现细节（LLMClient 协议里没有它），换一家
    # 实现可能就没有，所以取不到时不要报错。
    mode = getattr(llm, "mode", "未知")

    print(f"process_id : {state.process_id}")
    print(f"来源       : {state.source.url}")
    print(f"状态       : {state.status}")
    print(f"结构化输出 : 第「{mode}」档")
    print(f"Tool 调用  : {state.tool_call_count} 次 / 上限 5")
    print(f"Evidence   : {len(state.evidence)} 条")
    for index, evidence in enumerate(state.evidence, start=1):
        print(f"  [{index}] {evidence.evidence_type:<9} {evidence.location}")
    print()

    # generate_proposal() 失败时不抛错，而是落成 failed 状态，所以必须先看
    # status/error，不能只等着捕异常。
    if state.status == "failed" or state.proposal is None:
        print(f"没有生成提案：{state.error}")
        return 1

    print(state.proposal.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

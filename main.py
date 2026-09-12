"""本地跑一遍 Knowledge Agent 全链路。

    python main.py [仓库地址 | owner repo]

不传参数就用 example/demo-project。仓库地址支持 https://github.com/owner/repo、
git@github.com:owner/repo.git 这类写法，也支持直接写 owner/repo。
地址解析交给 ghrepo（见 GHRepo.parse），它只认纯粹的仓库地址：像
https://github.com/owner/repo/tree/main 这种子页面地址会被判为非法。

底层 Tool 目前全是 mock 数据，不访问 GitHub，所以 owner/repo 填什么都不影响
结果（只影响 State.source.url 和提案的 title）。

需要项目根目录下有 .env（照 .env.example 填），否则这里报 ConfigError。
"""

import sys

from ghrepo import GHRepo

from app.agents.knowledge_agent import KnowledgeAgent
from app.config import ConfigError, load_log_settings
from app.llm import create_llm_client
from app.logging import configure_logging

DEFAULT_OWNER = "example"
DEFAULT_REPO = "demo-project"


def main() -> int:
    # print 中文时别让控制台编码把脚本搞崩。errors="replace" 保证最差也只是
    # 显示成问号，而不是抛 UnicodeEncodeError 把整次运行的结果吞掉。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 日志只在这一处配置（幂等，重复调用不会叠加 handler）。级别来自 .env 的
    # LOG_LEVEL —— configure_logging 自己不读 env，这一行把两者接上。
    # 日志走 stderr，stdout 留给下面那份中文报告。
    #
    # LOG_LEVEL 写错不该把整次运行拖垮：退回默认级别继续，并说一声 —— 和下面
    # 「先打印原因再 return 1」是同一种透明，只是这条不值得中断运行。
    try:
        configure_logging(load_log_settings())
    except ConfigError as error:
        print(f"LOG_LEVEL 有问题，改用默认级别：{error}")
        configure_logging()

    args = sys.argv[1:]

    if not args:
        owner, repo = DEFAULT_OWNER, DEFAULT_REPO
    else:
        # 一个参数既可以是完整地址，也可以是 owner/repo；两个参数是老写法。
        # 都先拼成 "owner/repo" 再解析，省得多一套分支。
        raw = args[0] if len(args) == 1 else "/".join(args[:2])
        try:
            ref = GHRepo.parse(raw)
        except ValueError as error:
            print(f"仓库地址有问题：{error}")
            return 1

        # GHRepo 的字段叫 name 不叫 repo，别顺手写错。
        owner, repo = ref.owner, ref.name

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

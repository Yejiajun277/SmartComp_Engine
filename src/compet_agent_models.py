from langchain_openai import ChatOpenAI

agent_llm = ChatOpenAI(
    model="mimo-v2.5",
    base_url="https://token-plan-cn.xiaomimimo.com/v1",
    max_retries=3,
    extra_body = {"thinking": {"type": "disabled"}}
)
sub_agent_llm = ChatOpenAI(
    model="mimo-v2.5",
    base_url="https://token-plan-cn.xiaomimimo.com/v1",
    max_retries=3,
    extra_body = {"thinking": {"type": "disabled"}}
)

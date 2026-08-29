const PROVIDER_NAMES = {
  mimo: 'MiMo',
  tavily: 'Tavily',
};

export function formatProviderName(provider) {
  if (!provider) return '';
  return PROVIDER_NAMES[String(provider).toLowerCase()] || provider;
}

export function getRuntimeStatusMeta(runtimeConfig) {
  if (!runtimeConfig?.llm || typeof runtimeConfig.llm.configured !== 'boolean') {
    return {
      state: 'unknown',
      tone: 'neutral',
      title: '运行配置暂不可用',
      compactLabel: '配置状态待确认',
      detail: '提交任务时将由服务端确认实际执行模式',
      executionLabel: '执行模式待确认',
      forceRuleEngine: false,
      searchConfigured: null,
      searchLabel: '联网搜索状态待确认',
    };
  }

  const searchConfigured = runtimeConfig.search?.configured === true;
  const searchProvider = formatProviderName(runtimeConfig.search?.provider) || '联网搜索';
  const searchLabel = searchConfigured
    ? `${searchProvider} 联网搜索已配置`
    : '联网搜索未配置';

  if (!runtimeConfig.llm.configured) {
    return {
      state: 'rule',
      tone: 'warning',
      title: '未配置模型 API',
      compactLabel: '规则引擎 · 未配置 API',
      detail: '当前使用规则引擎，不会调用大模型',
      executionLabel: '规则引擎',
      forceRuleEngine: true,
      searchConfigured,
      searchLabel,
    };
  }

  const provider = formatProviderName(runtimeConfig.llm.provider) || '模型';
  const modelLabel = runtimeConfig.llm.model
    ? `${provider} · ${runtimeConfig.llm.model}`
    : provider;

  return {
    state: 'model',
    tone: 'ready',
    title: '模型 API 已配置',
    compactLabel: modelLabel,
    detail: modelLabel,
    executionLabel: modelLabel,
    forceRuleEngine: false,
    searchConfigured,
    searchLabel,
  };
}

import test from 'node:test';
import assert from 'node:assert/strict';
import { formatProviderName, getRuntimeStatusMeta } from '../src/utils/runtime.js';

test('describes a missing model API as forced rule-engine mode', () => {
  const meta = getRuntimeStatusMeta({
    llm: { configured: false, provider: 'mimo', model: null },
    search: { configured: false, provider: 'tavily', model: null },
    default_mode: 'rule',
  });

  assert.deepEqual(meta, {
    state: 'rule',
    tone: 'warning',
    title: '未配置模型 API',
    compactLabel: '规则引擎 · 未配置 API',
    detail: '当前使用规则引擎，不会调用大模型',
    executionLabel: '规则引擎',
    forceRuleEngine: true,
    searchConfigured: false,
    searchLabel: '联网搜索未配置',
  });
});

test('shows the configured provider and exact model without claiming connectivity', () => {
  const meta = getRuntimeStatusMeta({
    llm: { configured: true, provider: 'mimo', model: 'mimo-v2.5-pro' },
    search: { configured: true, provider: 'tavily', model: null },
    default_mode: 'model',
  });

  assert.deepEqual(meta, {
    state: 'model',
    tone: 'ready',
    title: '模型 API 已配置',
    compactLabel: 'MiMo · mimo-v2.5-pro',
    detail: 'MiMo · mimo-v2.5-pro',
    executionLabel: 'MiMo · mimo-v2.5-pro',
    forceRuleEngine: false,
    searchConfigured: true,
    searchLabel: 'Tavily 联网搜索已配置',
  });
});

test('keeps an unavailable runtime status honest and formats known providers', () => {
  assert.deepEqual(getRuntimeStatusMeta(null), {
    state: 'unknown',
    tone: 'neutral',
    title: '运行配置暂不可用',
    compactLabel: '配置状态待确认',
    detail: '提交任务时将由服务端确认实际执行模式',
    executionLabel: '执行模式待确认',
    forceRuleEngine: false,
    searchConfigured: null,
    searchLabel: '联网搜索状态待确认',
  });
  assert.equal(formatProviderName('mimo'), 'MiMo');
  assert.equal(formatProviderName('tavily'), 'Tavily');
  assert.equal(formatProviderName('custom-provider'), 'custom-provider');
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { formatLlmTokenUsage } from '../src/utils/llmLogs.js';

test('missing provider usage remains unknown even when legacy counters contain zero', () => {
  assert.equal(formatLlmTokenUsage({ usage_known: false, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }), '未知');
  assert.equal(formatLlmTokenUsage({ usage_known: true, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }), '0');
  for (const usage_known of [undefined, null]) {
    assert.equal(formatLlmTokenUsage({ usage_known, finish_reason: 'content_filter', prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }), '未知');
  }
});

test('known and historical usage retain counts without inventing missing values', () => {
  assert.equal(formatLlmTokenUsage({ prompt_tokens: 100, completion_tokens: 25 }), '125');
  assert.equal(formatLlmTokenUsage({ usage_known: null, prompt_tokens: 100, completion_tokens: 25, total_tokens: 0 }), '125');
  assert.equal(formatLlmTokenUsage({ usage_known: true, total_tokens: 125 }), '125');
  assert.equal(formatLlmTokenUsage({}), '未知');
  assert.equal(formatLlmTokenUsage({ type: 'search' }), '-');
});

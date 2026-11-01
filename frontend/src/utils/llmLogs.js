export const INITIAL_LLM_LOG_PAGINATION = { current: 1, pageSize: 10 };

export function formatLlmTokenUsage(record) {
  if (record.type === 'search') return '-';
  if (record.usage_known === false) return '未知';
  const valid = value => Number.isInteger(value) && value >= 0;
  const format = value => value > 0 || record.usage_known === true ? String(value) : '未知';
  if (valid(record.prompt_tokens) && valid(record.completion_tokens)) {
    return format(record.prompt_tokens + record.completion_tokens);
  }
  if (valid(record.total_tokens)) return format(record.total_tokens);
  return '未知';
}

export function updateLlmLogPagination(current, next) {
  const currentPageSize = Number(current?.pageSize) || INITIAL_LLM_LOG_PAGINATION.pageSize;
  const nextPageSize = Number(next?.pageSize) || currentPageSize;
  const pageSizeChanged = nextPageSize !== currentPageSize;

  return {
    current: pageSizeChanged ? 1 : (Number(next?.current) || Number(current?.current) || 1),
    pageSize: nextPageSize,
  };
}

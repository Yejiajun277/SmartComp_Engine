export const INITIAL_LLM_LOG_PAGINATION = { current: 1, pageSize: 10 };

export function updateLlmLogPagination(current, next) {
  const currentPageSize = Number(current?.pageSize) || INITIAL_LLM_LOG_PAGINATION.pageSize;
  const nextPageSize = Number(next?.pageSize) || currentPageSize;
  const pageSizeChanged = nextPageSize !== currentPageSize;

  return {
    current: pageSizeChanged ? 1 : (Number(next?.current) || Number(current?.current) || 1),
    pageSize: nextPageSize,
  };
}

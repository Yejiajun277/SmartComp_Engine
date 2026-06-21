import { useState, useEffect } from 'react';
import { Table, Tag, Typography, Spin, Empty, Collapse } from 'antd';
import { getLlmLogs } from '../api/client';

const { Text, Paragraph } = Typography;

export default function LlmLogs({ taskId, refreshKey = 0 }) {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    getLlmLogs(taskId)
      .then((data) => setLogs(data.logs || []))
      .catch(() => setLogs([]))
      .finally(() => setLoading(false));
  }, [taskId, refreshKey]);

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', padding: 20 }} />;
  if (!logs.length) return <Empty description="暂无调用日志" />;

  const columns = [
    {
      title: 'Agent',
      dataIndex: 'agent',
      key: 'agent',
      width: 130,
      render: (v) => <Tag>{v || '-'}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 70,
      render: (v) => v === 'search'
        ? <Tag color="cyan">搜索</Tag>
        : <Tag color="blue">LLM</Tag>,
    },
    {
      title: '状态',
      key: 'status',
      width: 70,
      render: (_, record) => record.success
        ? <Tag color="green">成功</Tag>
        : <Tag color="red">失败</Tag>,
    },
    {
      title: 'Token',
      key: 'tokens',
      width: 110,
      render: (_, record) => {
        if (record.type === 'search') return '-';
        const total = record.total_tokens || (record.prompt_tokens || 0) + (record.completion_tokens || 0);
        return total ? `${total}` : '-';
      },
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      width: 80,
      render: (v) => v ? `${(v / 1000).toFixed(1)}s` : '-',
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      width: 120,
      ellipsis: true,
      render: (v) => v || '-',
    },
    {
      title: '摘要',
      key: 'summary',
      ellipsis: true,
      render: (_, record) => {
        if (record.type === 'search') return record.query || '-';
        return record.user_message ? record.user_message.slice(0, 80) + (record.user_message.length > 80 ? '...' : '') : '-';
      },
    },
  ];

  return (
    <Table
      dataSource={logs.map((log, i) => ({ ...log, key: i }))}
      columns={columns}
      size="small"
      pagination={{ pageSize: 10 }}
      expandable={{
        expandedRowRender: (record) => <LogDetail record={record} />,
      }}
    />
  );
}

function LogDetail({ record }) {
  if (record.type === 'search') {
    return (
      <div style={{ fontSize: 13 }}>
        <DetailSection label="搜索词" content={record.query} />
        <div style={{ marginTop: 8 }}>
          <Text strong>结果: </Text>
          <Text>{record.result_count} 条引用, {record.result_text_len} 字符</Text>
        </div>
        {record.error && <DetailSection label="错误" content={record.error} />}
      </div>
    );
  }

  return (
    <div style={{ fontSize: 13 }}>
      <div style={{ marginBottom: 8, color: '#888' }}>
        {record.timestamp && <Text type="secondary">{record.timestamp}</Text>}
        {record.prompt_tokens ? (
          <Text type="secondary" style={{ marginLeft: 16 }}>
            Prompt: {record.prompt_tokens} | Completion: {record.completion_tokens} | Total: {record.total_tokens}
          </Text>
        ) : null}
        {record.temperature ? <Text type="secondary" style={{ marginLeft: 16 }}>temp={record.temperature}</Text> : null}
        {record.max_tokens ? <Text type="secondary" style={{ marginLeft: 16 }}>max_tokens={record.max_tokens}</Text> : null}
        {record.finish_reason ? <Text type="secondary" style={{ marginLeft: 16 }}>finish={record.finish_reason}</Text> : null}
      </div>
      <DetailSection label="System Prompt" content={record.system_prompt} />
      <DetailSection label="User Message" content={record.user_message} />
      <DetailSection label="LLM Output" content={record.result} />
      {record.parse_error && <DetailSection label="解析错误" content={record.parse_error} />}
    </div>
  );
}

function DetailSection({ label, content }) {
  if (!content) return null;
  return (
    <Collapse
      size="small"
      style={{ marginBottom: 8 }}
      items={[{
        key: '1',
        label: <Text strong>{label} <Text type="secondary">({content.length} chars)</Text></Text>,
        children: <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 300, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{content}</pre>,
      }]}
    />
  );
}

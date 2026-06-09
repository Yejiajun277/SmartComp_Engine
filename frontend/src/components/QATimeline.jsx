import { Timeline, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

export default function QATimeline({ results }) {
  if (!results || results.length === 0) {
    return <Text type="secondary">暂无质检记录</Text>;
  }

  return (
    <Timeline
      items={results.map((r) => ({
        dot: r.passed
          ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
          : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
        children: (
          <div>
            <Tag color={r.passed ? 'success' : 'error'}>
              {r.phase}
            </Tag>
            <Text>{r.message}</Text>
            {r.score != null && (
              <Text type="secondary" style={{ marginLeft: 8 }}>
                分数: {r.score.toFixed(0)}
              </Text>
            )}
          </div>
        ),
      }))}
    />
  );
}

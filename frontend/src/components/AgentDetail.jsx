import { Drawer, Descriptions, Tag, Collapse, Typography, Spin } from 'antd';
import { useState, useEffect } from 'react';
import { getArtifact } from '../api/client';

const { Text, Paragraph } = Typography;

export default function AgentDetail({ taskId, phase, open, onClose, agentLabel }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !taskId || !phase) return;
    setLoading(true);
    getArtifact(taskId, phase)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [open, taskId, phase]);

  return (
    <Drawer
      title={`${agentLabel || phase} - 详细信息`}
      open={open}
      onClose={onClose}
      size="large"
    >
      {loading ? (
        <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />
      ) : data ? (
        <Collapse
          defaultActiveKey={['output']}
          items={[
            {
              key: 'output',
              label: '输出数据',
              children: (
                <Paragraph>
                  <pre style={{
                    background: '#f5f5f5',
                    padding: 12,
                    borderRadius: 8,
                    maxHeight: 400,
                    overflow: 'auto',
                    fontSize: 12,
                  }}>
                    {JSON.stringify(data, null, 2)}
                  </pre>
                </Paragraph>
              ),
            },
          ]}
        />
      ) : (
        <Text type="secondary">暂无数据</Text>
      )}
    </Drawer>
  );
}

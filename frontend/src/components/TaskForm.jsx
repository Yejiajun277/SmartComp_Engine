import { useState } from 'react';
import { Form, Input, InputNumber, Switch, Button, Card } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';

export default function TaskForm({ onSubmit, loading }) {
  const [form] = Form.useForm();

  const handleSubmit = (values) => {
    onSubmit(values);
  };

  return (
    <Card title="提交分析任务" style={{ height: '100%' }}>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ maxCompetitors: 5, skipQa: false, useRuleEngine: false }}
      >
        <Form.Item
          name="productDescription"
          label="产品描述"
          rules={[{ required: true, message: '请输入产品名称或描述' }]}
        >
          <Input placeholder="例：飞书文档、Notion、钉钉" size="large" />
        </Form.Item>

        <Form.Item name="maxCompetitors" label="竞品数量">
          <InputNumber min={1} max={8} style={{ width: '100%' }} size="large" />
        </Form.Item>

        <Form.Item name="useRuleEngine" label="规则引擎模式（不调 LLM）" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item name="skipQa" label="跳过质检" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            icon={<ThunderboltOutlined />}
            size="large"
            block
          >
            开始分析
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}

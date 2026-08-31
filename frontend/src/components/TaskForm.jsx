import { useEffect } from 'react';
import { Button, Collapse, Form, Input, InputNumber, Switch } from 'antd';
import { SafetyCertificateOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { getRuntimeStatusMeta } from '../utils/runtime';
import { DEFAULT_MAX_COMPETITORS } from '../utils/taskCreation';
import RuntimeStatus from './RuntimeStatus';

export default function TaskForm({
  initialProduct,
  onSubmit,
  loading,
  runtimeConfig,
  runtimeLoading,
}) {
  const [form] = Form.useForm();
  const runtimeMeta = getRuntimeStatusMeta(runtimeConfig);

  useEffect(() => {
    if (initialProduct) form.setFieldValue('productDescription', initialProduct);
  }, [form, initialProduct]);

  useEffect(() => {
    if (runtimeMeta.forceRuleEngine) {
      form.setFieldValue('useRuleEngine', true);
    }
  }, [form, runtimeMeta.forceRuleEngine]);

  const advancedSettings = (
    <div className="advanced-settings">
      <Form.Item
        name="useRuleEngine"
        label="规则引擎模式（不调用 LLM）"
        valuePropName="checked"
        extra={runtimeMeta.forceRuleEngine ? '未检测到模型 API，当前已锁定为规则引擎' : null}
      >
        <Switch disabled={runtimeMeta.forceRuleEngine} />
      </Form.Item>
      <Form.Item
        name="skipQa"
        label="关闭质量检查（不建议）"
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <p className="advanced-warning">
        <SafetyCertificateOutlined />
        关闭 QA 后将不再执行结论打回、修正与引用覆盖检查。
      </p>
    </div>
  );

  return (
    <aside className="surface-card task-launcher" aria-labelledby="task-launcher-title">
      <span className="section-eyebrow">New analysis</span>
      <h2 id="task-launcher-title">启动分析任务</h2>
      <p>描述产品，系统将自动组建 Agent 团队并生成可核验策略报告。</p>

      <RuntimeStatus config={runtimeConfig} loading={runtimeLoading} />

      <Form
        form={form}
        layout="vertical"
        onFinish={(values) => onSubmit({
          ...values,
          useRuleEngine: runtimeMeta.forceRuleEngine || values.useRuleEngine,
        })}
        initialValues={{
          maxCompetitors: DEFAULT_MAX_COMPETITORS,
          skipQa: false,
          useRuleEngine: false,
        }}
        requiredMark={false}
      >
        <Form.Item
          name="productDescription"
          label="要分析的产品"
          rules={[{ required: true, message: '请输入产品名称或描述' }]}
        >
          <Input
            autoComplete="off"
            placeholder="例如：飞书、小米汽车、IPhone17"
            size="large"
          />
        </Form.Item>

        <Form.Item
          name="maxCompetitors"
          label="竞品数量"
          extra="建议 3–5 个，兼顾分析深度与演示节奏"
        >
          <InputNumber min={1} max={8} size="large" />
        </Form.Item>

        <Collapse
          className="advanced-settings-collapse"
          ghost
          items={[{
            key: 'advanced',
            label: '高级设置',
            children: advancedSettings,
          }]}
        />

        <Form.Item className="task-launcher-submit">
          <Button
            className="primary-action"
            type="primary"
            htmlType="submit"
            loading={loading}
            icon={<ThunderboltOutlined />}
            size="large"
            block
          >
            {runtimeMeta.forceRuleEngine ? '使用规则引擎启动' : '组建 Agent 团队'}
          </Button>
        </Form.Item>
      </Form>

      <div className="launcher-trust-note">
        <SafetyCertificateOutlined />
        <span><strong>默认开启 QualityAgent</strong> · 对关键结论执行检查与打回</span>
      </div>
    </aside>
  );
}
